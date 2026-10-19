from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from support.models import SupportTicketEvent, SupportTicketNotification


RETRY_DELAYS_MINUTES = (1, 5, 15, 60)
MAX_ATTEMPTS = len(RETRY_DELAYS_MINUTES) + 1


class Command(BaseCommand):
    help = "Envía avisos internos de respuestas recibidas en el portal de soporte."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50, help="Máximo de avisos por ejecución (predeterminado: 50).")

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit < 1 or limit > 500:
            raise CommandError("--limit debe estar entre 1 y 500.")
        if not settings.EMAIL_HOST or not settings.DEFAULT_FROM_EMAIL:
            raise CommandError("Configura EMAIL_HOST y EMAIL_FROM para enviar avisos de soporte.")
        if settings.EMAIL_USE_TLS and settings.EMAIL_USE_SSL:
            raise CommandError("Activa solo una opción entre EMAIL_USE_TLS y EMAIL_USE_SSL.")

        now = timezone.now()
        pending = SupportTicketNotification.objects.filter(
            status=SupportTicketNotification.Status.PENDING,
            next_attempt_at__lte=now,
        ).order_by("created_at", "id").values_list("pk", flat=True)[:limit]
        sent = pending_count = failed = skipped = 0
        for notification_id in pending:
            result = self._send_one(notification_id)
            sent += result == "sent"
            pending_count += result == "pending"
            failed += result == "failed"
            skipped += result == "skipped"
        self.stdout.write(f"Avisos de soporte enviados: {sent}; por reintentar: {pending_count}; agotados: {failed}; omitidos: {skipped}.")

    def _send_one(self, notification_id):
        with transaction.atomic():
            notification = SupportTicketNotification.objects.select_for_update().select_related(
                "ticket__customer", "message", "recipient",
            ).get(pk=notification_id)
            if notification.status != SupportTicketNotification.Status.PENDING or notification.next_attempt_at > timezone.now():
                return "skipped"
            notification.attempt_count += 1
            notification.last_attempt_at = timezone.now()
            try:
                recipient_email = notification.recipient_email.strip()
                if not recipient_email:
                    raise ValueError("No hay correo de destino.")
                subject = f"Respuesta del cliente en soporte {notification.ticket.number}"[:250]
                body = (
                    f"El cliente {notification.ticket.customer.name} respondió al ticket {notification.ticket.number}.\n\n"
                    f"Asunto: {notification.ticket.title}\n"
                    f"Remitente: {notification.message.sender_name} <{notification.message.sender_email}>\n\n"
                    f"Respuesta:\n{notification.message.body}\n"
                )
                if settings.ERP_PUBLIC_URL:
                    body += f"\nAbre REDMAGNA ERP para revisar el ticket: {settings.ERP_PUBLIC_URL}\n"
                delivered = send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [recipient_email], fail_silently=False)
                if delivered != 1:
                    raise RuntimeError("El servidor no confirmó el envío.")
            except Exception as error:
                notification.last_error = f"Error SMTP: {type(error).__name__}"[:300]
                if notification.attempt_count >= MAX_ATTEMPTS:
                    notification.status = SupportTicketNotification.Status.FAILED
                    result = "failed"
                else:
                    notification.next_attempt_at = timezone.now() + timedelta(minutes=RETRY_DELAYS_MINUTES[notification.attempt_count - 1])
                    result = "pending"
                notification.save(update_fields=["attempt_count", "last_attempt_at", "last_error", "status", "next_attempt_at"])
                SupportTicketEvent.objects.create(
                    ticket=notification.ticket,
                    action="portal_reply_notification_failed",
                    detail=f"Intento {notification.attempt_count}/{MAX_ATTEMPTS} para {notification.recipient_email}: {notification.last_error}.",
                    actor_label="Sistema",
                )
                self.stderr.write(f"No se pudo enviar el aviso de soporte {notification.pk} ({notification.last_error}).")
                return result

            notification.status = SupportTicketNotification.Status.SENT
            notification.sent_at = timezone.now()
            notification.last_error = ""
            notification.save(update_fields=["attempt_count", "last_attempt_at", "status", "sent_at", "last_error"])
            SupportTicketEvent.objects.create(
                ticket=notification.ticket,
                action="portal_reply_notification_sent",
                detail=f"Aviso de respuesta enviado a {notification.recipient_email}.",
                actor_label="Sistema",
            )
            return "sent"
