from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from sales.models import PublicLeadNotification


RETRY_DELAYS_MINUTES = (1, 5, 15, 60)
MAX_ATTEMPTS = len(RETRY_DELAYS_MINUTES) + 1


class Command(BaseCommand):
    help = "Envía avisos internos de nuevas solicitudes públicas de cotización."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50, help="Máximo de avisos por ejecución (predeterminado: 50).")

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit < 1 or limit > 500:
            raise CommandError("--limit debe estar entre 1 y 500.")
        if not settings.EMAIL_HOST or not settings.DEFAULT_FROM_EMAIL:
            raise CommandError("Configura EMAIL_HOST y EMAIL_FROM para enviar avisos de prospectos.")
        if settings.EMAIL_USE_TLS and settings.EMAIL_USE_SSL:
            raise CommandError("Activa solo una opción entre EMAIL_USE_TLS y EMAIL_USE_SSL.")
        now = timezone.now()
        pending_ids = list(PublicLeadNotification.objects.filter(
            status=PublicLeadNotification.Status.PENDING,
            next_attempt_at__lte=now,
        ).order_by("created_at", "id").values_list("pk", flat=True)[:limit])
        sent = pending = failed = skipped = 0
        for notification_id in pending_ids:
            result = self._send_one(notification_id)
            sent += result == "sent"
            pending += result == "pending"
            failed += result == "failed"
            skipped += result == "skipped"
        self.stdout.write(f"Avisos de prospectos enviados: {sent}; por reintentar: {pending}; agotados: {failed}; omitidos: {skipped}.")

    def _send_one(self, notification_id):
        with transaction.atomic():
            notification = PublicLeadNotification.objects.select_for_update().select_related(
                "submission__opportunity",
            ).get(pk=notification_id)
            if notification.status != PublicLeadNotification.Status.PENDING or notification.next_attempt_at > timezone.now():
                return "skipped"

            opportunity = notification.submission.opportunity
            notification.attempt_count += 1
            notification.last_attempt_at = timezone.now()
            try:
                validate_email(notification.recipient_email)
                subject = f"Nueva solicitud web: {' '.join(opportunity.name.split())}"[:250]
                body = (
                    "Se recibió una nueva solicitud de cotización en el sitio de Redmagna.\n\n"
                    f"Empresa: {opportunity.company_name}\n"
                    f"Contacto: {opportunity.contact_name}\n"
                    f"Correo: {opportunity.email}\n"
                    f"Teléfono: {opportunity.phone or 'No indicado'}\n"
                    f"Solicitud: {opportunity.name}\n\n"
                    f"Detalles:\n{opportunity.description}\n\n"
                    f"Campaña: {opportunity.utm_campaign or 'Sin campaña'}\n"
                    f"Origen / medio: {' / '.join(value for value in (opportunity.utm_source, opportunity.utm_medium) if value) or 'Sin atribución'}\n"
                )
                if settings.ERP_PUBLIC_URL:
                    body += f"\nAbre REDMAGNA ERP para revisar la oportunidad: {settings.ERP_PUBLIC_URL}\n"
                delivered = send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [notification.recipient_email], fail_silently=False)
                if delivered != 1:
                    raise RuntimeError("El servidor de correo no confirmó el envío.")
            except Exception as error:
                notification.last_error = f"{type(error).__name__}"[:120]
                if notification.attempt_count >= MAX_ATTEMPTS:
                    notification.status = PublicLeadNotification.Status.FAILED
                    result = "failed"
                else:
                    notification.next_attempt_at = timezone.now() + timedelta(minutes=RETRY_DELAYS_MINUTES[notification.attempt_count - 1])
                    result = "pending"
                notification.save(update_fields=["attempt_count", "last_attempt_at", "last_error", "status", "next_attempt_at"])
                self.stderr.write(f"No se pudo enviar el aviso de prospecto {notification.pk} ({notification.last_error}).")
                return result

            notification.status = PublicLeadNotification.Status.SENT
            notification.sent_at = timezone.now()
            notification.last_error = ""
            notification.save(update_fields=["attempt_count", "last_attempt_at", "status", "sent_at", "last_error"])
            return "sent"
