import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, models, transaction
from django.utils import timezone

from inventory.models import StockUnit
from sales.models import Customer, WorkOrder
from .sla import add_working_seconds, validate_calendar, working_seconds_between


class SupportSlaPolicy(models.Model):
    priority = models.CharField(max_length=10, choices=[("low", "Baja"), ("normal", "Normal"), ("high", "Alta"), ("urgent", "Urgente")], unique=True)
    first_response_minutes = models.PositiveIntegerField()
    resolution_minutes = models.PositiveIntegerField()
    weekly_schedule = models.JSONField(
        default=dict,
        blank=True,
        help_text='Calendario local por día: 0=lunes…6=domingo. Ejemplo L-V: {"0":[["09:00","13:00"],["14:00","18:00"]],"1":[["09:00","13:00"],["14:00","18:00"]],"2":[["09:00","13:00"],["14:00","18:00"]],"3":[["09:00","13:00"],["14:00","18:00"]],"4":[["09:00","13:00"],["14:00","18:00"]]}. Vacío conserva minutos corridos.',
    )
    calendar_timezone = models.CharField(
        max_length=64,
        default="America/Mexico_City",
        help_text="Zona IANA para interpretar los horarios, por ejemplo America/Mexico_City.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["priority"]
        constraints = [
            models.CheckConstraint(condition=models.Q(first_response_minutes__gt=0), name="support_sla_response_gt_zero"),
            models.CheckConstraint(condition=models.Q(resolution_minutes__gt=0), name="support_sla_resolution_gt_zero"),
        ]

    def clean(self):
        super().clean()
        if self.first_response_minutes < 1 or self.resolution_minutes < 1:
            raise ValidationError("Configura tiempos SLA mayores que cero.")
        validate_calendar(self.weekly_schedule, self.calendar_timezone)

    def __str__(self):
        return f"SLA {self.get_priority_display()} · respuesta {self.first_response_minutes} min · resolución {self.resolution_minutes} min"


class SupportTicket(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "Nuevo"
        IN_PROGRESS = "in_progress", "En atención"
        WAITING_CUSTOMER = "waiting_customer", "En espera del cliente"
        RESOLVED = "resolved", "Resuelto"
        CLOSED = "closed", "Cerrado"
        CANCELLED = "cancelled", "Cancelado"

    class Priority(models.TextChoices):
        LOW = "low", "Baja"
        NORMAL = "normal", "Normal"
        HIGH = "high", "Alta"
        URGENT = "urgent", "Urgente"

    class Channel(models.TextChoices):
        PHONE = "phone", "Teléfono"
        EMAIL = "email", "Correo"
        WEB = "web", "Web"
        INTERNAL = "internal", "Interno"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=24, unique=True, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="support_tickets")
    work_order = models.ForeignKey(WorkOrder, null=True, blank=True, on_delete=models.PROTECT, related_name="support_tickets")
    serial_unit = models.ForeignKey(StockUnit, null=True, blank=True, on_delete=models.PROTECT, related_name="support_tickets")
    title = models.CharField(max_length=240)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW, db_index=True)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL, db_index=True)
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.INTERNAL)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_support_tickets")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_support_tickets")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    sla_response_target_minutes = models.PositiveIntegerField(null=True, blank=True, editable=False)
    sla_resolution_target_minutes = models.PositiveIntegerField(null=True, blank=True, editable=False)
    first_response_at = models.DateTimeField(null=True, blank=True, editable=False)
    sla_paused_since = models.DateTimeField(null=True, blank=True, editable=False)
    sla_paused_seconds = models.PositiveIntegerField(default=0, editable=False)
    sla_paused_working_seconds = models.PositiveIntegerField(default=0, editable=False)
    sla_weekly_schedule = models.JSONField(default=dict, blank=True, editable=False)
    sla_calendar_timezone = models.CharField(max_length=64, default="America/Mexico_City", editable=False)
    portal_link_version = models.PositiveIntegerField(default=0, editable=False)

    @property
    def sla_response_due_at(self):
        if self.sla_response_target_minutes is None:
            return None
        if self.sla_weekly_schedule:
            return add_working_seconds(
                self.created_at,
                self.sla_response_target_minutes * 60,
                self.sla_weekly_schedule,
                self.sla_calendar_timezone,
            )
        return self.created_at + timedelta(minutes=self.sla_response_target_minutes)

    @property
    def sla_resolution_due_at(self):
        if self.sla_resolution_target_minutes is None:
            return None
        if self.sla_weekly_schedule:
            paused_seconds = self.sla_paused_working_seconds
            if self.sla_paused_since and self.status == self.Status.WAITING_CUSTOMER:
                paused_seconds += working_seconds_between(
                    self.sla_paused_since,
                    timezone.now(),
                    self.sla_weekly_schedule,
                    self.sla_calendar_timezone,
                )
            return add_working_seconds(
                self.created_at,
                self.sla_resolution_target_minutes * 60 + paused_seconds,
                self.sla_weekly_schedule,
                self.sla_calendar_timezone,
            )
        paused_seconds = self.sla_paused_seconds
        if self.sla_paused_since and self.status == self.Status.WAITING_CUSTOMER:
            paused_seconds += max(0, int((timezone.now() - self.sla_paused_since).total_seconds()))
        return self.created_at + timedelta(minutes=self.sla_resolution_target_minutes, seconds=paused_seconds)

    def finish_sla_pause(self, ended_at=None):
        if not self.sla_paused_since:
            return
        ended_at = ended_at or timezone.now()
        self.sla_paused_seconds += max(0, int((ended_at - self.sla_paused_since).total_seconds()))
        if self.sla_weekly_schedule:
            self.sla_paused_working_seconds += working_seconds_between(
                self.sla_paused_since,
                ended_at,
                self.sla_weekly_schedule,
                self.sla_calendar_timezone,
            )
        self.sla_paused_since = None

    @property
    def sla_response_status(self):
        due_at = self.sla_response_due_at
        if due_at is None:
            return "unconfigured"
        if self.status == self.Status.CANCELLED:
            return "not_applicable"
        if self.first_response_at:
            return "met" if self.first_response_at <= due_at else "breached"
        if self.status in {self.Status.RESOLVED, self.Status.CLOSED}:
            return "breached"
        return "overdue" if timezone.now() > due_at else "on_track"

    @property
    def sla_resolution_status(self):
        due_at = self.sla_resolution_due_at
        if due_at is None:
            return "unconfigured"
        if self.status == self.Status.CANCELLED:
            return "not_applicable"
        if self.resolved_at:
            return "met" if self.resolved_at <= due_at else "breached"
        if self.status == self.Status.CLOSED:
            return "breached"
        return "overdue" if timezone.now() > due_at else "on_track"

    class Meta:
        ordering = ["-updated_at", "-created_at"]
        permissions = [
            ("transition_supportticket", "Puede cambiar el estado de tickets de soporte"),
            ("assign_supportticket", "Puede asignar tickets de soporte"),
            ("send_supportticket_portal_link", "Puede enviar enlaces de seguimiento de soporte a clientes"),
        ]

    def save(self, *args, **kwargs):
        if self.work_order_id and self.work_order.sales_order.quote.customer_id != self.customer_id:
            raise ValidationError({"work_order": "La orden de trabajo debe pertenecer al cliente del ticket."})
        if self.serial_unit_id and (self.serial_unit.state != StockUnit.State.INSTALLED or self.serial_unit.customer_id != self.customer_id):
            raise ValidationError({"serial_unit": "El equipo debe estar instalado y pertenecer al cliente del ticket."})
        if not self._state.adding or self.number:
            return super().save(*args, **kwargs)
        year = timezone.localdate().year
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", [year + 2_000_000])
            prefix = f"RM-SOP-{year}-"
            previous = SupportTicket.objects.filter(number__startswith=prefix).order_by("-number").values_list("number", flat=True).first()
            sequence = int(previous.rsplit("-", 1)[1]) + 1 if previous else 1
            self.number = f"{prefix}{sequence:05d}"
            return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.number}: {self.title}"


class SupportTicketMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(SupportTicket, on_delete=models.PROTECT, related_name="messages")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="support_ticket_messages")
    sender_name = models.CharField(max_length=160, blank=True)
    sender_email = models.EmailField(blank=True)
    is_public = models.BooleanField(default=False, db_index=True)
    body = models.TextField(max_length=4000)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]
        permissions = [
            ("publish_supportticketmessage", "Puede compartir respuestas de soporte con el cliente"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(author__isnull=False)
                    | (
                        models.Q(is_public=True, author__isnull=True)
                        & ~models.Q(sender_name="")
                        & ~models.Q(sender_email="")
                    )
                ),
                name="support_message_visibility_has_actor",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Las notas de soporte son inmutables.")
        if not self.body.strip():
            raise ValidationError({"body": "Escribe una nota antes de guardarla."})
        if self.is_public and not self.author_id and (not self.sender_name.strip() or not self.sender_email.strip()):
            raise ValidationError("Un mensaje público del cliente debe conservar el nombre y correo del remitente.")
        if not self.is_public and not self.author_id:
            raise ValidationError("Una nota interna debe conservar su autor interno.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las notas de soporte no se pueden eliminar.")


class SupportTicketNotification(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        SENT = "sent", "Enviado"
        FAILED = "failed", "Fallido"
        SKIPPED = "skipped", "Sin correo disponible"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(SupportTicket, on_delete=models.PROTECT, related_name="notifications")
    message = models.OneToOneField(SupportTicketMessage, on_delete=models.PROTECT, related_name="staff_notification")
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="support_ticket_notifications")
    recipient_email = models.EmailField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"Aviso de {self.ticket.number} a {self.recipient_email}: {self.get_status_display()}"


class SupportInboundEmailReceipt(models.Model):
    class Status(models.TextChoices):
        ACCEPTED = "accepted", "Agregado al ticket"
        REJECTED = "rejected", "Rechazado"
        IGNORED = "ignored", "Ignorado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    mailbox = models.CharField(max_length=200)
    uidvalidity = models.PositiveBigIntegerField()
    uid = models.PositiveBigIntegerField()
    email_message_id = models.CharField(max_length=255, blank=True)
    sender_email = models.EmailField(blank=True)
    ticket = models.ForeignKey(SupportTicket, null=True, blank=True, on_delete=models.PROTECT, related_name="inbound_emails")
    ticket_message = models.OneToOneField(SupportTicketMessage, null=True, blank=True, on_delete=models.PROTECT, related_name="inbound_email")
    status = models.CharField(max_length=10, choices=Status.choices, db_index=True)
    reason_code = models.CharField(max_length=40, blank=True)
    received_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-received_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["mailbox", "uidvalidity", "uid"], name="support_inbound_mail_uid_unique"),
            models.CheckConstraint(
                condition=(
                    models.Q(status="accepted", ticket__isnull=False, ticket_message__isnull=False, reason_code="")
                    | (models.Q(status__in=["rejected", "ignored"], ticket__isnull=True, ticket_message__isnull=True) & ~models.Q(reason_code=""))
                ),
                name="support_inbound_mail_final_state",
            ),
        ]

    def __str__(self):
        return f"Correo de soporte {self.get_status_display()} · {self.mailbox} · UID {self.uid}"


class SupportTicketEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(SupportTicket, on_delete=models.PROTECT, related_name="events")
    action = models.CharField(max_length=40)
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, blank=True)
    detail = models.CharField(max_length=500, blank=True)
    actor_label = models.CharField(max_length=160, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="support_ticket_events")
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(actor__isnull=False) | ~models.Q(actor_label=""),
                name="support_event_has_actor_label",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("La bitácora de soporte es inmutable.")
        if not self.actor_id and not self.actor_label.strip():
            raise ValidationError("La bitácora debe identificar al actor interno o externo.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("La bitácora de soporte no se puede eliminar.")
