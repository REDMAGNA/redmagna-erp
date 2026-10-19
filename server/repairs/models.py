import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, models, transaction
from django.utils import timezone

from inventory.models import StockUnit
from sales.models import Customer
from support.models import SupportTicket


class RepairCase(models.Model):
    class Status(models.TextChoices):
        RECEIVED = "received", "Recibido"
        DIAGNOSIS = "diagnosis", "En diagnóstico"
        WAITING_AUTHORIZATION = "waiting_authorization", "Espera autorización"
        AUTHORIZED = "authorized", "Autorizado"
        IN_REPAIR = "in_repair", "En reparación"
        READY = "ready", "Listo"
        CLOSED = "closed", "Cerrado"
        UNREPAIRABLE = "unrepairable", "No reparable"
        CANCELLED = "cancelled", "Cancelado"

    class WarrantyReview(models.TextChoices):
        PENDING = "pending", "Pendiente de revisión"
        COVERED = "covered", "Cobertura confirmada"
        NOT_COVERED = "not_covered", "Sin cobertura confirmada"
        UNKNOWN = "unknown", "No determinada"

    class CustodyStatus(models.TextChoices):
        NOT_RECEIVED = "not_received", "No recibido físicamente"
        IN_CUSTODY = "in_custody", "En custodia de Redmagna"
        RETURNED = "returned", "Devuelto al cliente"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=24, unique=True, blank=True)
    ticket = models.OneToOneField(SupportTicket, on_delete=models.PROTECT, related_name="repair_case")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="repair_cases")
    serial_unit = models.ForeignKey(StockUnit, on_delete=models.PROTECT, related_name="repair_cases")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.RECEIVED, db_index=True)
    warranty_review = models.CharField(max_length=16, choices=WarrantyReview.choices, default=WarrantyReview.PENDING)
    custody_status = models.CharField(max_length=16, choices=CustodyStatus.choices, default=CustodyStatus.NOT_RECEIVED, db_index=True)
    intake_condition = models.TextField(blank=True)
    custody_received_at = models.DateTimeField(null=True, blank=True)
    custody_received_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="received_repair_cases")
    return_condition = models.TextField(blank=True)
    custody_returned_at = models.DateTimeField(null=True, blank=True)
    custody_returned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="returned_repair_cases")
    reported_issue = models.TextField()
    diagnosis = models.TextField(blank=True)
    proposed_work = models.TextField(blank=True)
    authorization_record = models.TextField(blank=True)
    authorized_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="authorized_repair_cases")
    authorized_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_repair_cases")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "number"]
        permissions = [
            ("transition_repaircase", "Puede cambiar el estado de expedientes de reparación"),
        ]

    def save(self, *args, **kwargs):
        if self.ticket_id and self.customer_id and self.serial_unit_id:
            ticket = self.ticket
            if ticket.customer_id != self.customer_id:
                raise ValidationError({"customer": "El cliente debe coincidir con el ticket relacionado."})
            if ticket.serial_unit_id != self.serial_unit_id:
                raise ValidationError({"serial_unit": "El equipo debe coincidir con el ticket relacionado."})
            if self.serial_unit.state != StockUnit.State.INSTALLED or self.serial_unit.customer_id != self.customer_id:
                raise ValidationError({"serial_unit": "El equipo debe seguir instalado y pertenecer al cliente."})
        if not self._state.adding:
            with transaction.atomic():
                previous = RepairCase.objects.select_for_update().get(pk=self.pk)
                immutable = ("ticket_id", "customer_id", "serial_unit_id", "reported_issue", "created_by_id", "number")
                if any(getattr(previous, field) != getattr(self, field) for field in immutable):
                    raise ValidationError("El ticket, cliente, equipo y reporte de origen son inmutables.")
                if previous.status in {self.Status.CLOSED, self.Status.CANCELLED}:
                    raise ValidationError("Un expediente cerrado o cancelado es inmutable.")
                if self.status != previous.status or self.authorization_record != previous.authorization_record or self.authorized_by_id != previous.authorized_by_id or self.authorized_at != previous.authorized_at:
                    raise ValidationError("El estado y la autorización solo cambian mediante la acción auditada.")
                custody_fields = ("custody_status", "intake_condition", "custody_received_at", "custody_received_by_id", "return_condition", "custody_returned_at", "custody_returned_by_id")
                if any(getattr(previous, field) != getattr(self, field) for field in custody_fields):
                    raise ValidationError("La custodia solo cambia mediante la acción auditada.")
                return super().save(*args, **kwargs)
        if not self.number:
            year = timezone.localdate().year
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [780000 + year])
                prefix = f"RM-REP-{year}-"
                last = RepairCase.objects.filter(number__startswith=prefix).order_by("-number").values_list("number", flat=True).first()
                sequence = int(last.rsplit("-", 1)[1]) + 1 if last else 1
                self.number = f"{prefix}{sequence:06d}"
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los expedientes de reparación se conservan; usa una transición para cancelarlos.")

    def __str__(self):
        return self.number or str(self.pk)


class RepairCaseEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repair_case = models.ForeignKey(RepairCase, on_delete=models.PROTECT, related_name="events")
    action = models.CharField(max_length=32)
    from_status = models.CharField(max_length=24, blank=True)
    to_status = models.CharField(max_length=24, blank=True)
    detail = models.CharField(max_length=1000, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="repair_case_events")
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["occurred_at", "id"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("La bitácora de reparación es inmutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("La bitácora de reparación no se puede eliminar.")
