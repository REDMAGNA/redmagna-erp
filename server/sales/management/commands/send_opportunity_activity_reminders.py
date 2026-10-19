from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from sales.models import Opportunity, OpportunityActivity, OpportunityActivityReminder


class Command(BaseCommand):
    help = "Envía avisos por correo de seguimientos próximos y vencidos del CRM."

    def add_arguments(self, parser):
        parser.add_argument("--window-hours", type=int, default=24, help="Anticipación para avisos de actividades próximas (predeterminado: 24 horas).")

    def handle(self, *args, **options):
        if options["window_hours"] < 0:
            raise CommandError("--window-hours debe ser cero o un número positivo.")
        if not settings.EMAIL_HOST or not settings.DEFAULT_FROM_EMAIL:
            raise CommandError("Configura EMAIL_HOST y EMAIL_FROM para enviar recordatorios.")
        if settings.EMAIL_USE_TLS and settings.EMAIL_USE_SSL:
            raise CommandError("Activa solo una opción entre EMAIL_USE_TLS y EMAIL_USE_SSL.")

        now = timezone.now()
        horizon = now + timedelta(hours=options["window_hours"])
        activities = OpportunityActivity.objects.filter(
            status=OpportunityActivity.Status.PLANNED,
            due_at__lte=horizon,
            opportunity__stage__in=[Opportunity.Stage.NEW, Opportunity.Stage.QUALIFIED, Opportunity.Stage.PROPOSAL],
        ).select_related("opportunity", "assigned_to", "created_by").order_by("due_at", "id")

        sent = missing_email = failed = 0
        for activity in activities.iterator(chunk_size=200):
            recipient = activity.assigned_to if activity.assigned_to_id and activity.assigned_to.is_active else activity.created_by
            if not recipient.is_active or not recipient.email.strip():
                missing_email += 1
                continue
            kind = OpportunityActivityReminder.Kind.OVERDUE if activity.due_at <= now else OpportunityActivityReminder.Kind.UPCOMING
            try:
                with transaction.atomic():
                    reminder, _ = OpportunityActivityReminder.objects.get_or_create(
                        activity=activity,
                        recipient=recipient,
                        kind=kind,
                        due_at=activity.due_at,
                    )
                    reminder = OpportunityActivityReminder.objects.select_for_update().get(pk=reminder.pk)
                    if reminder.sent_at:
                        continue
                    title = " ".join(activity.title.split())
                    when = timezone.localtime(activity.due_at).strftime("%d/%m/%Y %H:%M")
                    kind_label = "vencido" if kind == OpportunityActivityReminder.Kind.OVERDUE else "próximo"
                    subject = f"Seguimiento {kind_label}: {title}"[:250]
                    message = (
                        f"Tienes un seguimiento comercial {kind_label}.\n\n"
                        f"Actividad: {activity.title}\n"
                        f"Oportunidad: {activity.opportunity.name}\n"
                        f"Fecha: {when}\n"
                    )
                    if settings.ERP_PUBLIC_URL:
                        message += f"\nAbre REDMAGNA ERP para revisar el seguimiento: {settings.ERP_PUBLIC_URL}\n"
                    delivered = send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [recipient.email], fail_silently=False)
                    if delivered != 1:
                        raise RuntimeError("El servidor de correo no confirmó la entrega.")
                    reminder.sent_at = timezone.now()
                    reminder.save(update_fields=["sent_at"])
                sent += 1
            except Exception:
                failed += 1
                self.stderr.write(f"No se pudo enviar el recordatorio de actividad {activity.id}.")

        self.stdout.write(f"Recordatorios enviados: {sent}; sin correo disponible: {missing_email}; con error: {failed}.")
        if failed:
            raise CommandError("Algunos recordatorios fallaron; se pueden reintentar en la siguiente ejecución.")
