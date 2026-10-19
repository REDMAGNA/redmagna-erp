import uuid
from pathlib import PurePosixPath
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import connection
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone


class Customer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField("nombre comercial", max_length=200)
    legal_name = models.CharField("razón social", max_length=250, blank=True)
    rfc = models.CharField(max_length=13, blank=True, db_index=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    fiscal_regime = models.CharField(max_length=3, blank=True)
    fiscal_postal_code = models.CharField(max_length=5, blank=True)
    payment_term_days = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MaxValueValidator(3650)], help_text="Días naturales de crédito sugeridos al crear cotizaciones; vacío significa sin plazo predeterminado.")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class CustomerContact(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="contacts")
    name = models.CharField(max_length=160)
    role = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    is_primary = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["customer__name", "-is_primary", "name"]
        constraints = [models.UniqueConstraint(fields=["customer"], condition=Q(is_primary=True, is_active=True), name="sales_customer_contact_primary_uniq")]

    def clean(self):
        self.name = self.name.strip()
        self.role = self.role.strip()
        self.email = self.email.strip()
        self.phone = self.phone.strip()
        if not self.name:
            raise ValidationError({"name": "Indica el nombre del contacto."})
        if self.customer_id and not self.customer.is_active:
            raise ValidationError({"customer": "No se pueden agregar contactos a un cliente inactivo."})

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = CustomerContact.objects.get(pk=self.pk)
            if previous.customer_id != self.customer_id:
                raise ValidationError({"customer": "No se puede cambiar un contacto a otro cliente."})
        self.clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los contactos de clientes se archivan; no se eliminan.")

    def __str__(self):
        return f"{self.customer.name} · {self.name}"


class Opportunity(models.Model):
    class Stage(models.TextChoices):
        NEW = "new", "Nueva"
        QUALIFIED = "qualified", "Calificada"
        PROPOSAL = "proposal", "Cotización enviada"
        WON = "won", "Ganada"
        LOST = "lost", "Perdida"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=240)
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.PROTECT, related_name="opportunities")
    company_name = models.CharField(max_length=200, blank=True)
    contact_name = models.CharField(max_length=160, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    stage = models.CharField(max_length=16, choices=Stage.choices, default=Stage.NEW, db_index=True)
    expected_revenue = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    probability = models.PositiveSmallIntegerField(default=10)
    expected_close_date = models.DateField(null=True, blank=True)
    source = models.CharField(max_length=120, blank=True)
    utm_source = models.CharField(max_length=120, blank=True)
    utm_medium = models.CharField(max_length=120, blank=True)
    utm_campaign = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="redmagna_opportunities")
    lost_reason = models.CharField(max_length=120, blank=True)
    closing_note = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="created_redmagna_opportunities")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        permissions = [
            ("transition_opportunity", "Puede cambiar etapa y cerrar oportunidades"),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(probability__gte=0, probability__lte=100), name="sales_opportunity_probability_valid"),
            models.CheckConstraint(condition=models.Q(expected_revenue__gte=0), name="sales_opportunity_revenue_nonnegative"),
        ]

    def clean(self):
        if self.customer_id and self.company_name and self.company_name.strip().casefold() != self.customer.name.strip().casefold():
            raise ValidationError({"company_name": "El prospecto debe coincidir con el cliente relacionado."})
        if self.stage == self.Stage.LOST and not self.lost_reason.strip():
            raise ValidationError({"lost_reason": "Indica por qué se perdió la oportunidad."})
        if self.stage != self.Stage.LOST and self.lost_reason:
            raise ValidationError({"lost_reason": "El motivo de pérdida solo aplica a oportunidades perdidas."})

    def __str__(self):
        return self.name


class OpportunityActivity(models.Model):
    class ActivityType(models.TextChoices):
        CALL = "call", "Llamada"
        EMAIL = "email", "Correo"
        MEETING = "meeting", "Reunión"
        TASK = "task", "Tarea"

    class Status(models.TextChoices):
        PLANNED = "planned", "Pendiente"
        DONE = "done", "Completada"
        CANCELLED = "cancelled", "Cancelada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    opportunity = models.ForeignKey(Opportunity, on_delete=models.PROTECT, related_name="activities")
    activity_type = models.CharField(max_length=12, choices=ActivityType.choices, default=ActivityType.TASK)
    title = models.CharField(max_length=240)
    due_at = models.DateTimeField(db_index=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PLANNED, db_index=True)
    note = models.TextField(blank=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="assigned_redmagna_activities")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_redmagna_activities")
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="completed_redmagna_activities")
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["status", "due_at", "created_at"]
        permissions = [
            ("complete_opportunityactivity", "Puede completar actividades comerciales"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = OpportunityActivity.objects.only("status").get(pk=self.pk)
            if previous.status != self.Status.PLANNED:
                raise ValidationError("Las actividades completadas o canceladas son inmutables.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las actividades comerciales no se pueden eliminar.")

    def __str__(self):
        return f"{self.get_activity_type_display()}: {self.title}"


class OpportunityActivityReminder(models.Model):
    class Kind(models.TextChoices):
        UPCOMING = "upcoming", "Próximo"
        OVERDUE = "overdue", "Vencido"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    activity = models.ForeignKey(OpportunityActivity, on_delete=models.PROTECT, related_name="reminder_logs")
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="redmagna_activity_reminders")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    due_at = models.DateTimeField()
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-sent_at", "-due_at"]
        constraints = [
            models.UniqueConstraint(fields=["activity", "recipient", "kind", "due_at"], name="sales_activity_reminder_once"),
        ]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.activity.title}"


class Quote(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Borrador"
        SENT = "sent", "Enviada"
        APPROVED = "approved", "Aprobada"
        CANCELLED = "cancelled", "Cancelada"
        EXPIRED = "expired", "Vencida"
        SUPERSEDED = "superseded", "Reemplazada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=24, unique=True, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="quotes")
    customer_contact = models.ForeignKey(CustomerContact, null=True, blank=True, on_delete=models.PROTECT, related_name="quotes")
    recipient_name_snapshot = models.CharField(max_length=160, blank=True)
    recipient_email_snapshot = models.EmailField(blank=True)
    opportunity = models.ForeignKey(Opportunity, null=True, blank=True, on_delete=models.PROTECT, related_name="quotes")
    customer_site = models.ForeignKey("CustomerSite", null=True, blank=True, on_delete=models.PROTECT, related_name="quotes")
    service_site_name = models.CharField(max_length=160, blank=True)
    service_address = models.CharField(max_length=500, blank=True)
    service_contact_name = models.CharField(max_length=160, blank=True)
    service_contact_phone = models.CharField(max_length=40, blank=True)
    service_contact_email = models.EmailField(blank=True)
    title = models.CharField("proyecto o servicio", max_length=240)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True)
    issue_date = models.DateField(default=timezone.localdate)
    valid_until = models.DateField(null=True, blank=True)
    payment_term_days = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MaxValueValidator(3650)])
    notes = models.TextField(blank=True)
    revision_of = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="revisions")
    revision_number = models.PositiveSmallIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_quotes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = [
            ("send_quote", "Puede enviar cotizaciones"),
            ("approve_quote", "Puede aprobar cotizaciones"),
            ("cancel_quote", "Puede cancelar cotizaciones"),
            ("revise_quote", "Puede crear una revisión de cotización enviada"),
        ]
        constraints = [models.UniqueConstraint(fields=["revision_of", "revision_number"], condition=Q(revision_of__isnull=False), name="sales_quote_revision_number_uniq")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            with transaction.atomic():
                previous = Quote.objects.select_for_update().only("status", "customer_id", "customer_contact_id", "recipient_name_snapshot", "recipient_email_snapshot", "customer_site_id", "service_site_name", "service_address", "service_contact_name", "service_contact_phone", "service_contact_email", "title", "issue_date", "valid_until", "payment_term_days", "notes").get(pk=self.pk)
                protected_fields = ["customer_id", "customer_contact_id", "recipient_name_snapshot", "recipient_email_snapshot", "opportunity_id", "customer_site_id", "service_site_name", "service_address", "service_contact_name", "service_contact_phone", "service_contact_email", "title", "issue_date", "valid_until", "payment_term_days", "notes"]
                if previous.status != self.Status.DRAFT and any(getattr(previous, field) != getattr(self, field) for field in protected_fields):
                    raise ValidationError("Una cotización enviada o aprobada no se puede editar.")
                return super().save(*args, **kwargs)
        if not self.number:
            year = timezone.localdate().year
            with transaction.atomic():
                # Serialize number assignment across app workers. PostgreSQL is the
                # only supported database in this deployment.
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [year])
                last = Quote.objects.filter(number__startswith=f"RM-{year}-").order_by("-number").values_list("number", flat=True).first()
                sequence = int(last.rsplit("-", 1)[1]) + 1 if last else 1
                self.number = f"RM-{year}-{sequence:05d}"
                return super().save(*args, **kwargs)
        return super().save(*args, **kwargs)

    @property
    def subtotal(self):
        return sum((line.line_subtotal for line in self.lines.filter(is_optional=False)), Decimal("0.00"))

    @property
    def tax_total(self):
        return sum((line.tax_amount for line in self.lines.filter(is_optional=False)), Decimal("0.00"))

    @property
    def optional_subtotal(self):
        return sum((line.line_subtotal for line in self.lines.filter(is_optional=True)), Decimal("0.00"))

    @property
    def optional_tax_total(self):
        return sum((line.tax_amount for line in self.lines.filter(is_optional=True)), Decimal("0.00"))

    @property
    def optional_total(self):
        return self.optional_subtotal + self.optional_tax_total

    @property
    def total(self):
        return self.subtotal + self.tax_total

    def __str__(self):
        return self.number or str(self.id)


class QuoteLine(models.Model):
    class Kind(models.TextChoices):
        EQUIPMENT = "equipment", "Equipo"
        MATERIAL = "material", "Material"
        INSTALLATION = "installation", "Instalación"
        SERVICE = "service", "Servicio"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name="lines")
    catalog_product = models.ForeignKey("inventory.Product", null=True, blank=True, on_delete=models.PROTECT, related_name="quote_lines")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    description = models.CharField(max_length=300)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))])
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("16.00"))
    is_optional = models.BooleanField(default=False)
    approved_quantity = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [models.CheckConstraint(condition=models.Q(discount_percent__gte=0, discount_percent__lte=100), name="sales_quote_discount_percent_range")]

    @property
    def line_subtotal(self):
        return (self.quantity * self.unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) - self.discount_amount

    @property
    def discount_amount(self):
        gross = (self.quantity * self.unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return (gross * self.discount_percent / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def tax_amount(self):
        return (self.line_subtotal * self.tax_rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def clean(self):
        if self.quantity <= 0:
            raise ValidationError({"quantity": "La cantidad debe ser mayor que cero."})
        if self.unit_price < 0:
            raise ValidationError({"unit_price": "El precio no puede ser negativo."})
        if not Decimal("0") <= self.discount_percent <= Decimal("100"):
            raise ValidationError({"discount_percent": "El descuento debe estar entre 0 y 100 por ciento."})
        if self.tax_rate < 0 or self.tax_rate > 100:
            raise ValidationError({"tax_rate": "La tasa debe estar entre 0 y 100."})
        if self.approved_quantity is not None and not Decimal("0") <= self.approved_quantity <= self.quantity:
            raise ValidationError({"approved_quantity": "La cantidad aceptada debe estar entre cero y la cantidad propuesta."})
        if self.catalog_product_id:
            stock_line = self.kind in {self.Kind.EQUIPMENT, self.Kind.MATERIAL}
            expected_kind = "stockable" if stock_line else "service"
            if self.catalog_product.kind != expected_kind:
                raise ValidationError({"catalog_product": "El tipo de producto del catálogo no corresponde a este concepto de la cotización."})

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.quote_id:
                quote = Quote.objects.select_for_update().only("status").get(pk=self.quote_id)
                if quote.status != Quote.Status.DRAFT:
                    raise ValidationError("Los conceptos de una cotización enviada no se pueden editar.")
            self.clean()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            quote = Quote.objects.select_for_update().get(pk=self.quote_id)
            if quote.status != Quote.Status.DRAFT:
                raise ValidationError("Los conceptos de una cotización enviada no se pueden eliminar.")
            return super().delete(*args, **kwargs)

    @property
    def billable_quantity(self):
        return self.quantity if self.approved_quantity is None else self.approved_quantity


class QuoteDiscountPolicy(models.Model):
    """One-company policy for discounts that require an explicit manager review."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    enabled = models.BooleanField(default=False)
    maximum_discount_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
    )
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="updated_quote_discount_policies")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(id=1), name="sales_qdisc_singleton"),
            models.CheckConstraint(condition=models.Q(maximum_discount_percent__gte=0, maximum_discount_percent__lte=100), name="sales_qdisc_range"),
        ]

    def save(self, *args, **kwargs):
        if self.pk != 1:
            raise ValidationError("Solo existe una política de descuentos para esta empresa.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("La política de descuentos no se elimina; desactívala para conservar su configuración.")


class QuoteDiscountApproval(models.Model):
    """Immutable approval tied to the exact commercial lines that were reviewed."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quote = models.ForeignKey(Quote, on_delete=models.PROTECT, related_name="discount_approvals")
    quote_snapshot_hash = models.CharField(max_length=64)
    threshold_percent = models.DecimalField(max_digits=5, decimal_places=2)
    maximum_discount_percent = models.DecimalField(max_digits=5, decimal_places=2)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="approved_quote_discount_exceptions")
    approved_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-approved_at", "-id"]
        indexes = [models.Index(fields=["quote", "quote_snapshot_hash"], name="sales_qdisc_approv_idx")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("La autorización de descuento es inmutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("La autorización de descuento no se elimina.")


class QuoteCostSheet(models.Model):
    """Private internal estimate kept separate from the customer-facing quote."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quote = models.OneToOneField(Quote, on_delete=models.PROTECT, related_name="cost_sheet")
    target_margin_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("99.99"))],
        help_text="Margen bruto objetivo opcional. No modifica los precios de la cotización.",
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="created_quote_cost_sheets")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="updated_quote_cost_sheets")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["quote__number"]
        constraints = [
            models.CheckConstraint(
                condition=Q(target_margin_percent__isnull=True) | Q(target_margin_percent__gte=0, target_margin_percent__lt=100),
                name="sales_costsheet_margin_below_100",
            ),
        ]


class QuoteCostItem(models.Model):
    class Category(models.TextChoices):
        EQUIPMENT = "equipment", "Equipo"
        MATERIAL = "material", "Material"
        LABOR = "labor", "Mano de obra"
        TRAVEL = "travel", "Traslado"
        SUBCONTRACT = "subcontract", "Subcontratación"
        OTHER = "other", "Otro costo"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cost_sheet = models.ForeignKey(QuoteCostSheet, on_delete=models.CASCADE, related_name="items")
    category = models.CharField(max_length=16, choices=Category.choices)
    description = models.CharField(max_length=240)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, validators=[MinValueValidator(Decimal("0.001"))])
    unit_cost = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    is_optional = models.BooleanField(default=False)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="sales_costitem_quantity_positive"),
            models.CheckConstraint(condition=Q(unit_cost__gte=0), name="sales_costitem_cost_nonnegative"),
        ]

    @property
    def line_total(self):
        return (self.quantity * self.unit_cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

class QuoteTemplate(models.Model):
    """Reusable commercial defaults; quote lines copy their values as a snapshot."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=160, unique=True)
    title = models.CharField(max_length=240)
    validity_days = models.PositiveSmallIntegerField(default=30)
    notes = models.TextField(blank=True)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("16.00"))
    lines = models.JSONField(default=list)
    is_active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_quote_templates")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def delete(self, *args, **kwargs):
        raise ValidationError("Las plantillas de cotización se conservan; desactívalas para dejar de usarlas.")


class SalesOrder(models.Model):
    class ConfirmationSource(models.TextChoices):
        STAFF = "staff", "Personal de Redmagna"
        CUSTOMER = "customer", "Cliente"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quote = models.OneToOneField(Quote, on_delete=models.PROTECT, related_name="sales_order")
    confirmed_at = models.DateTimeField(default=timezone.now)
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    confirmation_source = models.CharField(max_length=12, choices=ConfirmationSource.choices, default=ConfirmationSource.STAFF)


class CustomerSite(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="sites")
    name = models.CharField(max_length=160)
    address = models.CharField(max_length=500)
    contact_name = models.CharField(max_length=160, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    notes = models.CharField(max_length=500, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["customer__name", "name"]
        constraints = [models.UniqueConstraint(fields=["customer", "name"], name="sales_customer_site_name_uniq")]

    def clean(self):
        self.name = self.name.strip()
        self.address = self.address.strip()
        if not self.name:
            raise ValidationError({"name": "Indica un nombre para el sitio del cliente."})
        if not self.address:
            raise ValidationError({"address": "Indica el domicilio del sitio."})
        if self.customer_id and not self.customer.is_active:
            raise ValidationError({"customer": "No se pueden agregar sitios a un cliente inactivo."})

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los sitios de cliente no se eliminan; desactívalos para conservar el historial.")

    def __str__(self):
        return f"{self.customer.name} · {self.name}"


class QuoteAcceptance(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quote = models.OneToOneField(Quote, on_delete=models.PROTECT, related_name="acceptance")
    accepted_by_name = models.CharField(max_length=160)
    accepted_by_email = models.EmailField()
    accepted_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-accepted_at"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("La aceptación de una cotización es inmutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("La aceptación de una cotización no se puede eliminar.")


class WorkOrder(models.Model):
    class Status(models.TextChoices):
        PLANNED = "planned", "Programada"
        IN_PROGRESS = "in_progress", "En curso"
        BLOCKED = "blocked", "Bloqueada"
        DONE = "done", "Terminada"
        CANCELLED = "cancelled", "Cancelada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sales_order = models.OneToOneField(SalesOrder, on_delete=models.PROTECT, related_name="work_order")
    customer_site = models.ForeignKey(CustomerSite, null=True, blank=True, on_delete=models.PROTECT, related_name="work_orders")
    service_site_name = models.CharField(max_length=160, blank=True)
    title = models.CharField(max_length=240)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PLANNED, db_index=True)
    scheduled_start = models.DateTimeField(null=True, blank=True)
    scheduled_end = models.DateTimeField(null=True, blank=True)
    service_address = models.CharField(max_length=500, blank=True)
    service_contact_name = models.CharField(max_length=160, blank=True)
    service_contact_phone = models.CharField(max_length=40, blank=True)
    service_contact_email = models.EmailField(blank=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="assigned_work_orders")
    completion_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        permissions = [
            ("transition_workorder", "Puede cambiar el estado de órdenes de trabajo"),
            ("schedule_workorder", "Puede programar y asignar órdenes de trabajo"),
            ("log_workorder_hours", "Puede registrar horas de trabajo en órdenes"),
            ("record_workorder_acceptance", "Puede registrar conformidad del cliente en órdenes de trabajo"),
        ]


class WorkOrderMaterialRequirement(models.Model):
    """Immutable snapshot of stockable quote lines accepted for a work order."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    work_order = models.ForeignKey(WorkOrder, on_delete=models.PROTECT, related_name="material_requirements")
    source_quote_line = models.OneToOneField(QuoteLine, on_delete=models.PROTECT, related_name="work_order_material_requirement")
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT, related_name="work_order_material_requirements")
    supply_location = models.ForeignKey("inventory.StockLocation", on_delete=models.PROTECT, related_name="work_order_material_requirements")
    required_quantity = models.DecimalField(max_digits=12, decimal_places=3)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["product__sku", "created_at"]
        constraints = [models.CheckConstraint(condition=models.Q(required_quantity__gt=0), name="sales_wo_material_req_positive")]

    def clean(self):
        if self.required_quantity <= 0:
            raise ValidationError({"required_quantity": "La cantidad requerida debe ser mayor que cero."})
        if self.product_id and self.product.kind != "stockable":
            raise ValidationError({"product": "Un requerimiento de material debe usar un producto con existencias."})
        if (self.product_id and self.product.tracking_policy == "serial"
                and self.required_quantity != self.required_quantity.to_integral_value()):
            raise ValidationError({"required_quantity": "La cantidad aprobada de un producto serializado debe ser entera."})
        if self.supply_location_id and not self.supply_location.is_active:
            raise ValidationError({"supply_location": "El destino de surtido debe ser una ubicación activa."})
        if self.work_order_id and self.source_quote_line_id and self.work_order.sales_order.quote_id != self.source_quote_line.quote_id:
            raise ValidationError("El requerimiento debe provenir de la cotización aprobada para esta orden.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Los requerimientos aprobados de material son inmutables.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los requerimientos aprobados de material no se pueden eliminar.")


def work_order_evidence_upload_to(instance, filename):
    safe_name = filename.replace("\\", "/").split("/")[-1]
    suffix = PurePosixPath(safe_name).suffix.lower()
    return f"work-orders/{instance.work_order_id}/{uuid.uuid4().hex}{suffix}"


def inspect_work_order_evidence(filename, uploaded_file):
    suffix = PurePosixPath(filename.replace("\\", "/").split("/")[-1]).suffix.lower()
    allowed = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".pdf": "application/pdf"}
    if suffix not in allowed:
        raise ValidationError({"file": "Adjunta una foto JPG, PNG o WEBP, o un documento PDF."})
    if uploaded_file.size < 1 or uploaded_file.size > 10 * 1024 * 1024:
        raise ValidationError({"file": "El archivo debe pesar entre 1 byte y 10 MB."})
    stream = getattr(uploaded_file, "file", uploaded_file)
    position = stream.tell() if hasattr(stream, "tell") else 0
    header = stream.read(16)
    if hasattr(stream, "seek"):
        stream.seek(position)
    valid = (
        (suffix in {".jpg", ".jpeg"} and header.startswith(b"\xff\xd8\xff"))
        or (suffix == ".png" and header.startswith(b"\x89PNG\r\n\x1a\n"))
        or (suffix == ".webp" and header.startswith(b"RIFF") and header[8:12] == b"WEBP")
        or (suffix == ".pdf" and header.startswith(b"%PDF-"))
    )
    if not valid:
        raise ValidationError({"file": "El contenido no coincide con el formato permitido."})
    return allowed[suffix]


class WorkOrderEvidence(models.Model):
    MAX_BYTES = 10 * 1024 * 1024

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    work_order = models.ForeignKey(WorkOrder, on_delete=models.PROTECT, related_name="evidence")
    file = models.FileField(upload_to=work_order_evidence_upload_to, max_length=300)
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=40)
    file_size = models.PositiveBigIntegerField()
    description = models.CharField(max_length=500, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="redmagna_work_order_evidence")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self):
        if self.file:
            self.content_type = inspect_work_order_evidence(self.original_name or self.file.name, self.file)
            self.file_size = self.file.size

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("La evidencia guardada es inmutable; carga una nueva versión para corregirla.")
        self.clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("La evidencia de servicio no se puede eliminar.")


class WorkLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    work_order = models.ForeignKey(WorkOrder, on_delete=models.PROTECT, related_name="time_logs")
    work_date = models.DateField(default=timezone.localdate, db_index=True)
    hours = models.DecimalField(max_digits=5, decimal_places=2)
    description = models.CharField(max_length=500)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="redmagna_work_logs")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-work_date", "-created_at"]
        constraints = [models.CheckConstraint(condition=models.Q(hours__gt=0, hours__lte=24), name="sales_worklog_hours_valid")]

    def clean(self):
        if self.hours <= 0 or self.hours > 24:
            raise ValidationError({"hours": "Registra entre 0.01 y 24 horas por entrada."})
        if not self.description.strip():
            raise ValidationError({"description": "Describe el trabajo realizado."})

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Las entradas de horas son inmutables; solicita una corrección administrativa.")
        self.clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las entradas de horas no se pueden eliminar.")


class WorkOrderChecklistItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    work_order = models.ForeignKey(WorkOrder, on_delete=models.PROTECT, related_name="checklist_items")
    label = models.CharField(max_length=240)
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="completed_work_checklist_items")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_work_checklist_items")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def save(self, *args, **kwargs):
        if self.work_order.status in {WorkOrder.Status.DONE, WorkOrder.Status.CANCELLED}:
            raise ValidationError("No se puede cambiar la lista de una orden terminada o cancelada.")
        if not self.label.strip():
            raise ValidationError({"label": "Describe el punto que debe revisarse."})
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los puntos de la lista de trabajo no se pueden eliminar.")


class WorkOrderChecklistTemplate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=160, unique=True)
    items = models.JSONField(default=list)
    is_active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_work_order_checklist_templates")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def clean(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValidationError({"name": "Indica un nombre para la plantilla."})
        if not isinstance(self.items, list) or not self.items or len(self.items) > 50:
            raise ValidationError({"items": "La plantilla debe tener de 1 a 50 puntos."})
        normalized = []
        for item in self.items:
            if not isinstance(item, str) or not item.strip() or len(item.strip()) > 240:
                raise ValidationError({"items": "Cada punto debe tener entre 1 y 240 caracteres."})
            normalized.append(item.strip())
        if len({item.casefold() for item in normalized}) != len(normalized):
            raise ValidationError({"items": "La plantilla no puede repetir puntos."})
        self.items = normalized

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las plantillas de trabajo no se eliminan; desactívalas para conservar el historial.")

    def __str__(self):
        return self.name


class WorkOrderCustomerAcceptance(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    work_order = models.OneToOneField(WorkOrder, on_delete=models.PROTECT, related_name="customer_acceptance")
    customer_contact_name = models.CharField(max_length=160)
    customer_contact_email = models.EmailField(blank=True)
    notes = models.CharField(max_length=500, blank=True)
    accepted_at = models.DateTimeField(default=timezone.now, db_index=True)
    captured_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="recorded_work_order_acceptances")

    class Meta:
        ordering = ["-accepted_at"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("El acuse de conformidad es inmutable.")
        if not self.customer_contact_name.strip():
            raise ValidationError({"customer_contact_name": "Registra el nombre de la persona del cliente que confirmó."})
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("El acuse de conformidad no se puede eliminar.")


class AuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity_type = models.CharField(max_length=60)
    entity_id = models.UUIDField()
    action = models.CharField(max_length=60)
    from_value = models.CharField(max_length=32, blank=True)
    to_value = models.CharField(max_length=32, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Los eventos de auditoría son inmutables.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los eventos de auditoría no se pueden eliminar.")


class PublicLeadSubmission(models.Model):
    """Minimal deduplication/rate-limit record for public quote requests."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nonce = models.UUIDField(unique=True)
    email_digest = models.CharField(max_length=64, db_index=True)
    opportunity = models.OneToOneField(Opportunity, on_delete=models.PROTECT, related_name="public_submission")
    consent_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("El registro de solicitud pública es inmutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("El registro de solicitud pública no se puede eliminar.")


class PublicLeadNotification(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        SENT = "sent", "Enviado"
        FAILED = "failed", "Fallido"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submission = models.OneToOneField(PublicLeadSubmission, on_delete=models.PROTECT, related_name="notification")
    recipient_email = models.EmailField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    manual_retry_count = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = PublicLeadNotification.objects.get(pk=self.pk)
            if previous.submission_id != self.submission_id or previous.recipient_email != self.recipient_email:
                raise ValidationError("El prospecto y el destinatario del aviso no se pueden cambiar.")
            if previous.status in {self.Status.SENT, self.Status.FAILED}:
                raise ValidationError("Un aviso enviado o agotado no se puede modificar.")
        return super().save(*args, **kwargs)

    def retry_failed(self):
        with transaction.atomic():
            notification = PublicLeadNotification.objects.select_for_update().get(pk=self.pk)
            if notification.status != self.Status.FAILED:
                return False
            PublicLeadNotification.objects.filter(pk=self.pk, status=self.Status.FAILED).update(
                status=self.Status.PENDING,
                attempt_count=0,
                manual_retry_count=models.F("manual_retry_count") + 1,
                next_attempt_at=timezone.now(),
                sent_at=None,
                last_error="",
            )
            self.refresh_from_db()
            return True

    def delete(self, *args, **kwargs):
        raise ValidationError("Los avisos a Ventas se conservan como bitácora.")
