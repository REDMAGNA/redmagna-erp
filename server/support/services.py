from hashlib import sha256
from urllib.parse import urljoin, urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core import signing
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.db.models import Prefetch
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from .models import SupportTicket, SupportTicketEvent, SupportTicketMessage, SupportTicketNotification


SUPPORT_PORTAL_SALT = "redmagna.support.portal.v1"
SUPPORT_PORTAL_MAX_AGE = 30 * 24 * 60 * 60


def _support_portal_token(ticket):
    return signing.dumps({
        "ticket_id": str(ticket.pk),
        "link_version": ticket.portal_link_version,
        "customer_email_hash": sha256(ticket.customer.email.strip().lower().encode("utf-8")).hexdigest(),
    }, salt=SUPPORT_PORTAL_SALT, compress=True)


@transaction.atomic
def _begin_portal_link_send(ticket_id, actor):
    ticket = SupportTicket.objects.select_for_update().select_related("customer").get(pk=ticket_id)
    if not ticket.customer.is_active:
        raise ValidationError("El cliente está archivado; no se puede enviar acceso al portal.")
    recipient = ticket.customer.email.strip().lower()
    if not recipient:
        raise ValidationError("Registra un correo en la ficha del cliente antes de enviar el enlace.")
    public_url = settings.ERP_PUBLIC_URL.strip()
    parsed_url = urlsplit(public_url)
    if parsed_url.scheme != "https" or not parsed_url.netloc or parsed_url.username or parsed_url.password:
        raise ValidationError("Configura ERP_PUBLIC_URL con una dirección HTTPS válida antes de enviar enlaces a clientes.")
    if not settings.EMAIL_HOST or not settings.DEFAULT_FROM_EMAIL:
        raise ValidationError("Configura el servidor SMTP y el correo remitente antes de enviar enlaces.")
    ticket.portal_link_version += 1
    ticket.save(update_fields=["portal_link_version", "updated_at"])
    SupportTicketEvent.objects.create(ticket=ticket, action="portal_link_email_attempt", detail=f"Destinatario: {recipient}", actor=actor)
    token = _support_portal_token(ticket)
    path = reverse("support-ticket-portal", kwargs={"token": token})
    link = urljoin(public_url.rstrip("/") + "/", path.lstrip("/"))
    return ticket, recipient, link


def send_ticket_portal_link(ticket_id, actor):
    ticket, recipient, link = _begin_portal_link_send(ticket_id, actor)
    subject = f"Seguimiento de soporte {ticket.number} · Redmagna"
    text_body = (
        f"Hola {ticket.customer.name},\n\n"
        f"Puedes consultar el estado y los datos básicos del ticket {ticket.number} en este enlace privado:\n{link}\n\n"
        f"El enlace vence en 30 días. Este portal no muestra notas internas del equipo.\n"
        "Si no solicitaste este seguimiento, puedes ignorar este correo."
    )
    safe_name = escape(ticket.customer.name)
    safe_number = escape(ticket.number)
    safe_link = escape(link, quote=True)
    html_body = (
        f"<p>Hola {safe_name},</p><p>Puedes consultar el estado y los datos básicos del ticket "
        f"<strong>{safe_number}</strong> en este enlace privado:</p><p><a href=\"{safe_link}\">Ver seguimiento del ticket</a></p>"
        "<p>El enlace vence en 30 días. Este portal no muestra notas internas del equipo.</p>"
        "<p>Si no solicitaste este seguimiento, puedes ignorar este correo.</p>"
    )
    try:
        message = EmailMultiAlternatives(subject, text_body, to=[recipient])
        message.attach_alternative(html_body, "text/html")
        sent_count = message.send(fail_silently=False)
    except Exception as error:
        SupportTicketEvent.objects.create(ticket=ticket, action="portal_link_email_uncertain", detail=f"El resultado del envío es incierto ({type(error).__name__}); revisar el correo antes de reintentar.", actor=actor)
        raise ValidationError("El resultado del correo es incierto. Revisa la bandeja de enviados antes de volver a intentarlo.") from error
    if sent_count != 1:
        SupportTicketEvent.objects.create(ticket=ticket, action="portal_link_email_failed", detail=f"SMTP confirmó {sent_count} mensajes enviados.", actor=actor)
        raise ValidationError("El servidor SMTP no confirmó el envío del enlace.")
    SupportTicketEvent.objects.create(ticket=ticket, action="portal_link_email_sent", detail=f"Enlace privado enviado a {recipient}; vence en 30 días.", actor=actor)
    return {"ticket_number": ticket.number, "recipient_email": recipient}


def support_ticket_from_portal_token(token):
    try:
        payload = signing.loads(token, salt=SUPPORT_PORTAL_SALT, max_age=SUPPORT_PORTAL_MAX_AGE)
    except signing.SignatureExpired as error:
        raise ValidationError("Este enlace de seguimiento venció.") from error
    except signing.BadSignature as error:
        raise ValidationError("El enlace de seguimiento no es válido.") from error
    ticket = SupportTicket.objects.select_related("customer").prefetch_related(
        Prefetch("messages", queryset=SupportTicketMessage.objects.filter(is_public=True), to_attr="portal_messages"),
    ).filter(pk=payload.get("ticket_id")).first()
    if not ticket or not ticket.customer.is_active:
        raise ValidationError("No se encontró el ticket.")
    current_email_hash = sha256(ticket.customer.email.strip().lower().encode("utf-8")).hexdigest()
    if payload.get("link_version") != ticket.portal_link_version or payload.get("customer_email_hash") != current_email_hash:
        raise ValidationError("Este enlace ya no está vigente. Solicita uno nuevo a Redmagna.")
    return ticket


@transaction.atomic
def add_portal_ticket_reply(ticket_id, sender_name, sender_email, body):
    ticket = SupportTicket.objects.select_for_update().select_related("customer", "assigned_to", "created_by").get(pk=ticket_id)
    if ticket.status not in {SupportTicket.Status.NEW, SupportTicket.Status.IN_PROGRESS, SupportTicket.Status.WAITING_CUSTOMER}:
        raise ValidationError("Este ticket no recibe respuestas en línea. Contacta al equipo de Redmagna.")
    normalized_email = sender_email.strip().lower()
    if not normalized_email or normalized_email != ticket.customer.email.strip().lower():
        raise ValidationError("Escribe el correo registrado para este cliente.")
    normalized_name = sender_name.strip()
    if not normalized_name or len(normalized_name) > 160:
        raise ValidationError("Escribe tu nombre (máximo 160 caracteres).")
    normalized_body = body.strip()
    if not normalized_body or len(normalized_body) > 4000:
        raise ValidationError("Escribe un mensaje de hasta 4,000 caracteres.")
    message = SupportTicketMessage.objects.create(
        ticket=ticket,
        author=None,
        sender_name=normalized_name,
        sender_email=normalized_email,
        is_public=True,
        body=normalized_body,
    )
    ticket.save(update_fields=["updated_at"])
    if ticket.status in {SupportTicket.Status.NEW, SupportTicket.Status.WAITING_CUSTOMER}:
        before = ticket.status
        if before == SupportTicket.Status.WAITING_CUSTOMER:
            ticket.finish_sla_pause(timezone.now())
        ticket.status = SupportTicket.Status.IN_PROGRESS
        ticket.save(update_fields=["status", "sla_paused_seconds", "sla_paused_working_seconds", "sla_paused_since", "updated_at"])
        SupportTicketEvent.objects.create(
            ticket=ticket,
            action="status_changed",
            from_status=before,
            to_status=ticket.status,
            actor_label=f"Cliente: {normalized_email}",
        )
    SupportTicketEvent.objects.create(
        ticket=ticket,
        action="portal_reply_received",
        detail=f"Respuesta del cliente recibida desde el portal: {normalized_email}",
        actor_label=f"Cliente: {normalized_email}",
    )
    recipient = ticket.assigned_to if ticket.assigned_to_id and ticket.assigned_to.is_active else ticket.created_by
    recipient_email = recipient.email.strip() if recipient.is_active else ""
    notification = SupportTicketNotification.objects.create(
        ticket=ticket,
        message=message,
        recipient=recipient,
        recipient_email=recipient_email,
        status=SupportTicketNotification.Status.PENDING if recipient_email else SupportTicketNotification.Status.SKIPPED,
        last_error="" if recipient_email else "No hay correo disponible para el responsable ni para quien registró el ticket.",
    )
    SupportTicketEvent.objects.create(
        ticket=ticket,
        action="portal_reply_notification_queued" if recipient_email else "portal_reply_notification_skipped",
        detail=f"Aviso {notification.status}: {recipient_email or 'sin correo disponible'}.",
        actor_label=f"Cliente: {normalized_email}",
    )
    return message


ALLOWED_TRANSITIONS = {
    SupportTicket.Status.NEW: {SupportTicket.Status.IN_PROGRESS, SupportTicket.Status.CANCELLED},
    SupportTicket.Status.IN_PROGRESS: {SupportTicket.Status.WAITING_CUSTOMER, SupportTicket.Status.RESOLVED, SupportTicket.Status.CANCELLED},
    SupportTicket.Status.WAITING_CUSTOMER: {SupportTicket.Status.IN_PROGRESS, SupportTicket.Status.RESOLVED, SupportTicket.Status.CANCELLED},
    SupportTicket.Status.RESOLVED: {SupportTicket.Status.IN_PROGRESS, SupportTicket.Status.CLOSED},
    SupportTicket.Status.CLOSED: {SupportTicket.Status.IN_PROGRESS},
    SupportTicket.Status.CANCELLED: set(),
}


@transaction.atomic
def transition_ticket(ticket_id, target, actor):
    ticket = SupportTicket.objects.select_for_update().get(pk=ticket_id)
    if target not in SupportTicket.Status.values:
        raise ValidationError("Selecciona un estado de soporte válido.")
    if target not in ALLOWED_TRANSITIONS[ticket.status]:
        raise ValidationError(f"No se puede mover el ticket de {ticket.get_status_display()} a {dict(SupportTicket.Status.choices)[target]}.")
    before = ticket.status
    now = timezone.now()
    if before == SupportTicket.Status.WAITING_CUSTOMER and target != SupportTicket.Status.WAITING_CUSTOMER:
        ticket.finish_sla_pause(now)
    elif before != SupportTicket.Status.WAITING_CUSTOMER and target == SupportTicket.Status.WAITING_CUSTOMER:
        ticket.sla_paused_since = now
    ticket.status = target
    if target == SupportTicket.Status.RESOLVED:
        ticket.resolved_at = now
    elif before in {SupportTicket.Status.RESOLVED, SupportTicket.Status.CLOSED} and target == SupportTicket.Status.IN_PROGRESS:
        ticket.resolved_at = None
    if target == SupportTicket.Status.CLOSED:
        ticket.closed_at = now
    elif before == SupportTicket.Status.CLOSED:
        ticket.closed_at = None
    ticket.save(update_fields=["status", "resolved_at", "closed_at", "sla_paused_since", "sla_paused_seconds", "sla_paused_working_seconds", "updated_at"])
    SupportTicketEvent.objects.create(ticket=ticket, action="status_changed", from_status=before, to_status=target, actor=actor)
    return ticket


@transaction.atomic
def add_ticket_message(ticket_id, actor, body, *, is_public=False):
    ticket = SupportTicket.objects.select_for_update().get(pk=ticket_id)
    if is_public and not actor.has_perm("support.publish_supportticketmessage"):
        raise ValidationError("No tienes permiso para compartir respuestas con el cliente.")
    if is_public and ticket.status not in {SupportTicket.Status.NEW, SupportTicket.Status.IN_PROGRESS, SupportTicket.Status.WAITING_CUSTOMER}:
        raise ValidationError("Reabre el ticket antes de compartir una respuesta con el cliente.")
    if not is_public and ticket.status in {SupportTicket.Status.CLOSED, SupportTicket.Status.CANCELLED}:
        raise ValidationError("Reabre el ticket antes de agregar una nota.")
    message = SupportTicketMessage.objects.create(ticket=ticket, author=actor, body=body.strip(), is_public=is_public)
    ticket.save(update_fields=["updated_at"])
    if is_public and ticket.first_response_at is None:
        ticket.first_response_at = timezone.now()
        ticket.save(update_fields=["first_response_at", "updated_at"])
    if is_public and ticket.status == SupportTicket.Status.NEW:
        before = ticket.status
        ticket.status = SupportTicket.Status.IN_PROGRESS
        ticket.save(update_fields=["status", "updated_at"])
        SupportTicketEvent.objects.create(ticket=ticket, action="status_changed", from_status=before, to_status=ticket.status, actor=actor)
    if is_public and ticket.status == SupportTicket.Status.IN_PROGRESS:
        before = ticket.status
        ticket.status = SupportTicket.Status.WAITING_CUSTOMER
        ticket.sla_paused_since = timezone.now()
        ticket.save(update_fields=["status", "sla_paused_since", "updated_at"])
        SupportTicketEvent.objects.create(ticket=ticket, action="status_changed", from_status=before, to_status=ticket.status, actor=actor)
    SupportTicketEvent.objects.create(ticket=ticket, action="reply_shared" if is_public else "note_added", actor=actor)
    return message
