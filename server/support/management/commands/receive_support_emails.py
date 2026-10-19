import email
import imaplib
import re
from email.header import decode_header
from email.policy import default
from email.utils import parseaddr

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from support.models import SupportInboundEmailReceipt, SupportTicket
from support.services import add_portal_ticket_reply


TICKET_PATTERN = re.compile(r"\b(RM-SOP-\d{4}-\d{5})\b", re.IGNORECASE)
AUTH_PASS_PATTERN = re.compile(r"(?:^|[;\s])dmarc\s*=\s*pass(?:[;\s]|$)", re.IGNORECASE)
MAX_EMAIL_BYTES = 1_000_000


def _decode_header(value):
    pieces = []
    for part, encoding in decode_header(str(value or "")):
        if isinstance(part, bytes):
            try:
                part = part.decode(encoding or "utf-8", errors="replace")
            except LookupError:
                part = part.decode("utf-8", errors="replace")
        pieces.append(part)
    return "".join(pieces)


def _plain_body(message):
    parts = message.walk() if message.is_multipart() else [message]
    for part in parts:
        if part.get_content_type() != "text/plain" or part.get_filename():
            continue
        try:
            content = part.get_content()
        except (LookupError, UnicodeError, AttributeError):
            payload = part.get_payload(decode=True) or b""
            content = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if isinstance(content, str):
            return content.strip()[:4000]
    return ""


def _trusted_dmarc_pass(message):
    authserv_id = settings.SUPPORT_IMAP_AUTH_SERV_ID
    if not authserv_id:
        return False
    for value in message.get_all("Authentication-Results", []):
        first_token = str(value).strip().split(";", 1)[0].strip().lower().split()[0:1]
        if first_token and first_token[0] == authserv_id and AUTH_PASS_PATTERN.search(str(value)):
            return True
    return False


class Command(BaseCommand):
    help = "Recibe respuestas de clientes por IMAP y las agrega a tickets de soporte."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100, help="Máximo de mensajes por ejecución (predeterminado: 100).")

    def handle(self, *args, **options):
        if not settings.SUPPORT_IMAP_HOST:
            self.stdout.write("Recepción de correo de soporte desactivada; no hay servidor IMAP configurado.")
            return
        required = [settings.SUPPORT_IMAP_USERNAME, settings.SUPPORT_IMAP_PASSWORD, settings.SUPPORT_IMAP_AUTH_SERV_ID]
        if not all(required):
            raise CommandError("Configura usuario, contraseña y authserv-id confiable para habilitar IMAP de soporte.")
        if options["limit"] < 1 or options["limit"] > 500:
            raise CommandError("--limit debe estar entre 1 y 500.")

        client = None
        try:
            client = imaplib.IMAP4_SSL(settings.SUPPORT_IMAP_HOST, settings.SUPPORT_IMAP_PORT, timeout=30)
            client.login(settings.SUPPORT_IMAP_USERNAME, settings.SUPPORT_IMAP_PASSWORD)
            status, _ = client.select(settings.SUPPORT_IMAP_MAILBOX, readonly=True)
            if status != "OK":
                raise CommandError("No se pudo abrir el buzón IMAP de soporte en modo de solo lectura.")
            validity_response = client.response("UIDVALIDITY")[1]
            if not validity_response or not validity_response[0]:
                raise CommandError("El servidor IMAP no informó UIDVALIDITY; se cancela para evitar duplicados inseguros.")
            uidvalidity = int(validity_response[0])
            status, data = client.uid("search", None, "ALL")
            if status != "OK":
                raise CommandError("No se pudieron listar los mensajes del buzón IMAP.")
            all_uids = [int(raw_uid) for raw_uid in (data[0].split() if data and data[0] else [])]
            processed_uids = set(SupportInboundEmailReceipt.objects.filter(
                mailbox=settings.SUPPORT_IMAP_MAILBOX, uidvalidity=uidvalidity,
            ).values_list("uid", flat=True))
            pending_uids = [uid for uid in all_uids if uid not in processed_uids][:options["limit"]]
            accepted = rejected = ignored = 0
            for uid in pending_uids:
                status, fetched = client.uid("fetch", str(uid), "(RFC822.SIZE)")
                if status != "OK" or not fetched or not isinstance(fetched[0], tuple):
                    continue
                size_match = re.search(rb"RFC822\.SIZE\s+(\d+)", fetched[0][0], re.IGNORECASE)
                if not size_match:
                    continue
                if int(size_match.group(1)) > MAX_EMAIL_BYTES:
                    self._record(uidvalidity, uid, "", "", None, None, "ignored", "message_too_large")
                    ignored += 1
                    continue
                status, fetched = client.uid("fetch", str(uid), "(BODY.PEEK[])")
                if status != "OK" or not fetched or not isinstance(fetched[0], tuple):
                    continue
                raw_message = fetched[0][1]
                result = self._process(uidvalidity, uid, email.message_from_bytes(raw_message, policy=default))
                accepted += result == "accepted"
                rejected += result == "rejected"
                ignored += result == "ignored"
            self.stdout.write(f"Correo de soporte procesado: {accepted} respuestas agregadas; {rejected} rechazadas; {ignored} ignoradas; {len(all_uids) - len(pending_uids)} ya procesadas.")
        except (imaplib.IMAP4.error, OSError, ValueError) as error:
            raise CommandError(f"No se pudo procesar el buzón IMAP ({type(error).__name__}).") from error
        finally:
            if client is not None:
                try:
                    client.logout()
                except (imaplib.IMAP4.error, OSError):
                    pass

    def _process(self, uidvalidity, uid, message):
        message_id = str(message.get("Message-ID", "")).strip()[:255]
        sender_email = parseaddr(_decode_header(message.get("From")))[1].strip().lower()[:254]
        subject = _decode_header(message.get("Subject"))
        if (message.get("Auto-Submitted", "no").strip().lower() != "no"
                or str(message.get("Precedence", "")).strip().lower() in {"bulk", "list", "junk"}):
            return self._record(uidvalidity, uid, message_id, sender_email, None, None, "ignored", "automated_message")
        match = TICKET_PATTERN.search(subject)
        if not match:
            return self._record(uidvalidity, uid, message_id, sender_email, None, None, "ignored", "ticket_number_missing")
        if not _trusted_dmarc_pass(message):
            return self._record(uidvalidity, uid, message_id, sender_email, None, None, "rejected", "sender_authentication_failed")
        ticket = SupportTicket.objects.select_related("customer").filter(number__iexact=match.group(1)).first()
        if not ticket:
            return self._record(uidvalidity, uid, message_id, sender_email, None, None, "rejected", "ticket_not_found")
        body = _plain_body(message)
        if not body:
            return self._record(uidvalidity, uid, message_id, sender_email, None, None, "rejected", "plain_text_body_missing")
        if not sender_email or sender_email != ticket.customer.email.strip().lower():
            return self._record(uidvalidity, uid, message_id, sender_email, None, None, "rejected", "customer_email_mismatch")

        sender_name = parseaddr(_decode_header(message.get("From")))[0].strip() or ticket.customer.name
        sender_name = sender_name[:160]
        try:
            with transaction.atomic():
                if SupportInboundEmailReceipt.objects.filter(mailbox=settings.SUPPORT_IMAP_MAILBOX, uidvalidity=uidvalidity, uid=uid).exists():
                    return "ignored"
                reply = add_portal_ticket_reply(ticket.pk, sender_name, sender_email, body)
                SupportInboundEmailReceipt.objects.create(
                    mailbox=settings.SUPPORT_IMAP_MAILBOX, uidvalidity=uidvalidity, uid=uid,
                    email_message_id=message_id, sender_email=sender_email, ticket=ticket, ticket_message=reply,
                    status="accepted", reason_code="",
                )
            return "accepted"
        except ValidationError:
            return self._record(uidvalidity, uid, message_id, sender_email, None, None, "rejected", "ticket_not_accepting_replies")

    def _record(self, uidvalidity, uid, message_id, sender_email, ticket, reply, status, reason):
        with transaction.atomic():
            SupportInboundEmailReceipt.objects.get_or_create(
                mailbox=settings.SUPPORT_IMAP_MAILBOX,
                uidvalidity=uidvalidity,
                uid=uid,
                defaults={
                    "email_message_id": message_id,
                    "sender_email": sender_email,
                    "ticket": ticket,
                    "ticket_message": reply,
                    "status": status,
                    "reason_code": reason,
                },
            )
        return status
