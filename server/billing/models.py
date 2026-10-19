import uuid
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import connection, models, transaction
from django.db.models import Sum
from django.utils import timezone

from sales.models import Customer, SalesOrder


class CustomerInvoice(models.Model):
    class State(models.TextChoices):
        DRAFT = "draft", "Borrador"
        OPEN = "open", "Abierta"
        PARTIAL = "partial", "Pago parcial"
        PAID = "paid", "Pagada"
        CREDITED = "credited", "Liquidada por nota de crédito"
        CANCELLED = "cancelled", "Cancelada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=24, unique=True, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="invoices")
    sales_order = models.ForeignKey(SalesOrder, null=True, blank=True, on_delete=models.PROTECT, related_name="customer_invoices")
    currency = models.CharField(max_length=3, default="MXN")
    issue_date = models.DateField(default=timezone.localdate)
    due_date = models.DateField(null=True, blank=True)
    memo = models.CharField(max_length=240, blank=True)
    state = models.CharField(max_length=12, choices=State.choices, default=State.DRAFT, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_customer_invoices")
    created_at = models.DateTimeField(auto_now_add=True)
    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="opened_customer_invoices")
    opened_at = models.DateTimeField(null=True, blank=True)
    opening_balance_batch_id = models.UUIDField(null=True, blank=True, db_index=True)
    opening_external_number = models.CharField(max_length=120, blank=True)
    opening_source_system = models.CharField(max_length=120, blank=True)
    opening_cutoff_date = models.DateField(null=True, blank=True)
    opening_original_total = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    opening_paid_before_cutoff = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["-issue_date", "-number"]
        permissions = [("open_customerinvoice", "Puede abrir facturas en cuentas por cobrar")]
        constraints = [models.CheckConstraint(condition=models.Q(currency="MXN"), name="billing_invoice_currency_mxn")]

    def save(self, *args, **kwargs):
        if self.currency != "MXN":
            raise ValidationError({"currency": "La primera versión opera únicamente en MXN."})
        if not self._state.adding:
            with transaction.atomic():
                previous = CustomerInvoice.objects.select_for_update().get(pk=self.pk)
                if previous.state != self.State.DRAFT:
                    protected = ["customer_id", "sales_order_id", "currency", "issue_date", "due_date", "memo", "created_by_id", "opening_balance_batch_id", "opening_external_number", "opening_source_system", "opening_cutoff_date", "opening_original_total", "opening_paid_before_cutoff"]
                    if any(getattr(previous, field) != getattr(self, field) for field in protected):
                        raise ValidationError("Una factura abierta no se puede editar; corrígela con el proceso autorizado.")
                return super().save(*args, **kwargs)
        if self.opening_balance_batch_id:
            if self.sales_order_id or not self.opening_external_number or not self.opening_source_system or not self.opening_cutoff_date or not self.opening_original_total:
                raise ValidationError("La partida de apertura necesita folio, sistema origen, corte e importe original, y no puede ligarse a una orden de venta.")
            if self.opening_original_total <= self.opening_paid_before_cutoff or self.opening_paid_before_cutoff < 0:
                raise ValidationError("Los importes de apertura deben conservar un saldo positivo y pagos previos no negativos.")
        elif any([self.opening_external_number, self.opening_source_system, self.opening_cutoff_date, self.opening_original_total, self.opening_paid_before_cutoff != Decimal("0.00")]):
            raise ValidationError("Los datos de factura histórica requieren un lote de apertura.")
        if not self.number:
            year = self.issue_date.year
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [730000 + year])
                prefix = f"RM-FAC-{year}-"
                last = CustomerInvoice.objects.filter(number__startswith=prefix).order_by("-number").values_list("number", flat=True).first()
                sequence = int(last.rsplit("-", 1)[1]) + 1 if last else 1
                self.number = f"{prefix}{sequence:06d}"
                return super().save(*args, **kwargs)
        return super().save(*args, **kwargs)

    @property
    def subtotal(self):
        if self.opening_balance_batch_id:
            return Decimal("0.00")
        return sum((line.line_subtotal for line in self.lines.all()), Decimal("0.00"))

    @property
    def tax_total(self):
        if self.opening_balance_batch_id:
            return Decimal("0.00")
        return sum((line.tax_amount for line in self.lines.all()), Decimal("0.00"))

    @property
    def total(self):
        if self.opening_balance_batch_id:
            return self.opening_original_total
        return self.subtotal + self.tax_total

    @property
    def paid_amount(self):
        current = self.allocations.filter(payment__state=Payment.State.POSTED).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        return self.opening_paid_before_cutoff + current

    @property
    def is_opening_balance(self):
        return bool(self.opening_balance_batch_id)

    @property
    def balance_due(self):
        return max(Decimal("0.00"), self.total - self.paid_amount - self.credited_amount)

    @property
    def credited_amount(self):
        notes = self.credit_notes.filter(state=CustomerCreditNote.State.POSTED).prefetch_related("lines__invoice_line")
        return sum((note.total for note in notes), Decimal("0.00"))

    def __str__(self):
        return self.number or str(self.id)


class CustomerInvoiceReminder(models.Model):
    class Kind(models.TextChoices):
        UPCOMING = "upcoming", "Próximo a vencer"
        OVERDUE = "overdue", "Vencido"

    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        SENT = "sent", "Enviado"
        FAILED = "failed", "Agotó reintentos"
        SKIPPED = "skipped", "Omitido"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(CustomerInvoice, on_delete=models.PROTECT, related_name="reminders")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    recipient_email = models.EmailField(blank=True)
    balance_snapshot = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    due_date_snapshot = models.DateField(null=True, blank=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    manual_retry_count = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    next_attempt_at = models.DateTimeField(default=timezone.now, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=120, blank=True)
    manual_retried_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="retried_customer_invoice_reminders",
    )
    manual_retried_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["invoice", "kind"], name="billing_invoice_reminder_once"),
            models.CheckConstraint(condition=models.Q(balance_snapshot__isnull=True) | models.Q(balance_snapshot__gte=0), name="billing_reminder_balance_nonnegative"),
        ]

    def __str__(self):
        return f"{self.invoice} · {self.get_kind_display()}"


class InvoiceLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(CustomerInvoice, on_delete=models.CASCADE, related_name="lines")
    catalog_product = models.ForeignKey("inventory.Product", null=True, blank=True, on_delete=models.PROTECT, related_name="invoice_lines")
    quote_line = models.ForeignKey("sales.QuoteLine", null=True, blank=True, on_delete=models.PROTECT, related_name="invoice_lines")
    line_number = models.PositiveSmallIntegerField()
    description = models.CharField(max_length=300)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))])
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("16.00"))

    class Meta:
        ordering = ["line_number"]
        constraints = [
            models.UniqueConstraint(fields=["invoice", "line_number"], name="billing_invoice_line_number_uniq"),
            models.CheckConstraint(condition=models.Q(discount_percent__gte=0, discount_percent__lte=100), name="billing_invoice_discount_percent_range"),
        ]

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
        if not 0 <= self.tax_rate <= 100:
            raise ValidationError({"tax_rate": "La tasa debe estar entre 0 y 100."})
        if self.quote_line_id:
            invoice = CustomerInvoice.objects.select_related("sales_order__quote").get(pk=self.invoice_id)
            if not invoice.sales_order_id or invoice.sales_order.quote_id != self.quote_line.quote_id:
                raise ValidationError({"quote_line": "El concepto debe pertenecer a la cotización de la orden de venta de esta factura."})
            if self.discount_percent != self.quote_line.discount_percent:
                raise ValidationError({"discount_percent": "El descuento debe coincidir con el concepto aceptado de la cotización."})

    def save(self, *args, **kwargs):
        with transaction.atomic():
            invoice = CustomerInvoice.objects.select_for_update().only("state").get(pk=self.invoice_id)
            if invoice.state != CustomerInvoice.State.DRAFT:
                raise ValidationError("Los conceptos de una factura abierta no se pueden editar.")
            self.clean()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            invoice = CustomerInvoice.objects.select_for_update().get(pk=self.invoice_id)
            if invoice.state != CustomerInvoice.State.DRAFT:
                raise ValidationError("Los conceptos de una factura abierta no se pueden eliminar.")
            return super().delete(*args, **kwargs)


class CustomerCreditNote(models.Model):
    class State(models.TextChoices):
        DRAFT = "draft", "Borrador"
        POSTED = "posted", "Aplicada"
        REVERSED = "reversed", "Revertida"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=24, unique=True, blank=True)
    invoice = models.ForeignKey(CustomerInvoice, on_delete=models.PROTECT, related_name="credit_notes")
    issue_date = models.DateField(default=timezone.localdate)
    reason = models.CharField(max_length=500)
    state = models.CharField(max_length=8, choices=State.choices, default=State.DRAFT, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_customer_credit_notes")
    created_at = models.DateTimeField(auto_now_add=True)
    posted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="posted_customer_credit_notes")
    posted_at = models.DateTimeField(null=True, blank=True)
    reversed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="reversed_customer_credit_notes")
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversal_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-issue_date", "-number"]
        permissions = [
            ("post_customercreditnote", "Puede aplicar notas de crédito internas a facturas"),
            ("reverse_customercreditnote", "Puede revertir notas de crédito internas con motivo"),
        ]

    @property
    def subtotal(self):
        return sum((line.line_subtotal for line in self.lines.all()), Decimal("0.00"))

    @property
    def tax_total(self):
        return sum((line.tax_amount for line in self.lines.all()), Decimal("0.00"))

    @property
    def total(self):
        return self.subtotal + self.tax_total

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = CustomerCreditNote.objects.get(pk=self.pk)
            if previous.state == self.State.REVERSED:
                raise ValidationError("Una nota de crédito revertida es inmutable.")
            if previous.state == self.State.POSTED:
                protected = ["number", "invoice_id", "issue_date", "reason", "created_by_id", "created_at", "posted_by_id", "posted_at"]
                if any(getattr(previous, field) != getattr(self, field) for field in protected):
                    raise ValidationError("Una nota aplicada es inmutable salvo por la reversa autorizada.")
                if self.state not in [self.State.POSTED, self.State.REVERSED]:
                    raise ValidationError("La nota aplicada solo puede revertirse mediante el flujo autorizado.")
                if self.state == self.State.POSTED and any(getattr(previous, field) != getattr(self, field) for field in ["reversed_by_id", "reversed_at", "reversal_reason"]):
                    raise ValidationError("Los datos de reversa solo se guardan junto con el cambio de estado autorizado.")
                if self.state == self.State.REVERSED and (not self.reversed_by_id or not self.reversed_at or len(self.reversal_reason.strip()) < 10):
                    raise ValidationError("La reversa requiere responsable, fecha y motivo de al menos 10 caracteres.")
        if not self.number:
            year = self.issue_date.year
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [750000 + year])
                prefix = f"RM-NC-{year}-"
                last = CustomerCreditNote.objects.filter(number__startswith=prefix).order_by("-number").values_list("number", flat=True).first()
                sequence = int(last.rsplit("-", 1)[1]) + 1 if last else 1
                self.number = f"{prefix}{sequence:06d}"
        return super().save(*args, **kwargs)


class CustomerCreditNoteLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    credit_note = models.ForeignKey(CustomerCreditNote, on_delete=models.CASCADE, related_name="lines")
    invoice_line = models.ForeignKey(InvoiceLine, on_delete=models.PROTECT, related_name="credit_note_lines")
    line_number = models.PositiveSmallIntegerField()
    quantity = models.DecimalField(max_digits=12, decimal_places=3)

    class Meta:
        ordering = ["line_number"]
        constraints = [
            models.UniqueConstraint(fields=["credit_note", "line_number"], name="billing_credit_note_line_number_uniq"),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="billing_credit_note_line_quantity_positive"),
        ]

    @property
    def description(self):
        return self.invoice_line.description

    @property
    def unit_price(self):
        return self.invoice_line.unit_price

    @property
    def discount_percent(self):
        return self.invoice_line.discount_percent

    @property
    def tax_rate(self):
        return self.invoice_line.tax_rate

    @property
    def line_subtotal(self):
        gross = (self.quantity * self.unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        discount = (gross * self.discount_percent / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return gross - discount

    @property
    def tax_amount(self):
        return (self.line_subtotal * self.tax_rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def clean(self):
        if self.quantity <= 0:
            raise ValidationError({"quantity": "La cantidad debe ser mayor que cero."})
        if self.credit_note_id and self.invoice_line_id:
            if self.credit_note.invoice_id != self.invoice_line.invoice_id:
                raise ValidationError("El concepto debe pertenecer a la factura origen de la nota.")

    def save(self, *args, **kwargs):
        with transaction.atomic():
            note = CustomerCreditNote.objects.select_for_update().get(pk=self.credit_note_id)
            if note.state != CustomerCreditNote.State.DRAFT:
                raise ValidationError("Los conceptos de una nota aplicada no se pueden editar.")
            self.clean()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            note = CustomerCreditNote.objects.select_for_update().get(pk=self.credit_note_id)
            if note.state != CustomerCreditNote.State.DRAFT:
                raise ValidationError("Los conceptos de una nota aplicada no se pueden eliminar.")
            return super().delete(*args, **kwargs)


class Payment(models.Model):
    class State(models.TextChoices):
        DRAFT = "draft", "Borrador"
        POSTED = "posted", "Aplicado"
        REVERSED = "reversed", "Revertido"

    class Method(models.TextChoices):
        TRANSFER = "transfer", "Transferencia"
        CASH = "cash", "Efectivo"
        CARD = "card", "Tarjeta"
        CHECK = "check", "Cheque"
        OTHER = "other", "Otro"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=24, unique=True, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    currency = models.CharField(max_length=3, default="MXN")
    method = models.CharField(max_length=12, choices=Method.choices)
    received_at = models.DateTimeField(default=timezone.now)
    reference = models.CharField(max_length=120, blank=True)
    memo = models.CharField(max_length=240, blank=True)
    state = models.CharField(max_length=8, choices=State.choices, default=State.DRAFT, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_customer_payments")
    created_at = models.DateTimeField(auto_now_add=True)
    posted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="posted_customer_payments")
    posted_at = models.DateTimeField(null=True, blank=True)
    reversed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="reversed_customer_payments")
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversal_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-received_at", "-number"]
        permissions = [
            ("post_payment", "Puede aplicar cobros a facturas"),
            ("reverse_payment", "Puede revertir cobros de clientes con motivo"),
        ]
        constraints = [models.CheckConstraint(condition=models.Q(currency="MXN"), name="billing_payment_currency_mxn")]

    def save(self, *args, **kwargs):
        if self.currency != "MXN":
            raise ValidationError({"currency": "La primera versión opera únicamente en MXN."})
        if not self._state.adding:
            previous = Payment.objects.get(pk=self.pk)
            if previous.state == self.State.REVERSED:
                raise ValidationError("Un cobro revertido es inmutable.")
            if previous.state == self.State.POSTED:
                protected = ["customer_id", "amount", "currency", "method", "received_at", "reference", "memo", "state", "created_by_id", "posted_by_id", "posted_at"]
                immutable_fields = [field for field in protected if field != "state"]
                if self.state not in [self.State.POSTED, self.State.REVERSED] or any(getattr(previous, field) != getattr(self, field) for field in immutable_fields):
                    raise ValidationError("Un cobro aplicado es inmutable; requiere una reversa autorizada.")
                if self.state == self.State.POSTED and any(getattr(previous, field) != getattr(self, field) for field in ("reversed_by_id", "reversed_at", "reversal_reason")):
                    raise ValidationError("Los datos de reversa solo se guardan junto con el cambio de estado autorizado.")
                if self.state == self.State.REVERSED and (not self.reversed_by_id or not self.reversed_at or len(self.reversal_reason.strip()) < 10):
                    raise ValidationError("La reversa requiere responsable, fecha y motivo de al menos 10 caracteres.")
        if self.amount <= 0:
            raise ValidationError({"amount": "El importe recibido debe ser mayor que cero."})
        if not self.number:
            year = self.received_at.year
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [740000 + year])
                prefix = f"RM-COB-{year}-"
                last = Payment.objects.filter(number__startswith=prefix).order_by("-number").values_list("number", flat=True).first()
                sequence = int(last.rsplit("-", 1)[1]) + 1 if last else 1
                self.number = f"{prefix}{sequence:06d}"
                return super().save(*args, **kwargs)
        return super().save(*args, **kwargs)


class PaymentAllocation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="allocations")
    invoice = models.ForeignKey(CustomerInvoice, on_delete=models.PROTECT, related_name="allocations")
    amount = models.DecimalField(max_digits=16, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["payment", "invoice"], name="billing_payment_invoice_uniq"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="billing_allocation_positive"),
        ]

    def clean(self):
        if self.amount <= 0:
            raise ValidationError({"amount": "El importe aplicado debe ser mayor que cero."})
        if self.payment_id and self.invoice_id:
            payment = self.payment
            invoice = self.invoice
            if payment.customer_id != invoice.customer_id:
                raise ValidationError("El cobro y la factura deben pertenecer al mismo cliente.")
            if payment.currency != invoice.currency:
                raise ValidationError("El cobro y la factura deben usar la misma moneda en esta versión.")

    def save(self, *args, **kwargs):
        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(pk=self.payment_id)
            if payment.state != Payment.State.DRAFT:
                raise ValidationError("No se pueden cambiar aplicaciones de un cobro aplicado.")
            self.clean()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(pk=self.payment_id)
            if payment.state != Payment.State.DRAFT:
                raise ValidationError("No se pueden eliminar aplicaciones de un cobro aplicado.")
            return super().delete(*args, **kwargs)


class FiscalDocument(models.Model):
    class State(models.TextChoices):
        PREPARED = "prepared", "Preparado"
        SUBMITTED = "submitted", "Enviado al PAC"
        STAMPED = "stamped", "Timbrado"
        REJECTED = "rejected", "Rechazado"
        CANCEL_PENDING = "cancel_pending", "Cancelación solicitada"
        CANCELLED = "cancelled", "Cancelado"
        CANCEL_REJECTED = "cancel_rejected", "Cancelación rechazada"

    class DocumentType(models.TextChoices):
        INCOME = "I", "Ingreso"
        CREDIT_NOTE = "E", "Egreso"
        TRANSFER = "T", "Traslado"
        PAYMENT = "P", "Pago"

    class CancellationReason(models.TextChoices):
        ERROR_REPLACED = "01", "Error con relación"
        ERROR_NO_RELATION = "02", "Error sin relación"
        NO_OPERATION = "03", "Operación no realizada"
        GLOBAL_INVOICE = "04", "Operación nominativa relacionada con factura global"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(CustomerInvoice, null=True, blank=True, on_delete=models.PROTECT, related_name="fiscal_documents")
    credit_note = models.ForeignKey(CustomerCreditNote, null=True, blank=True, on_delete=models.PROTECT, related_name="fiscal_documents")
    payment = models.ForeignKey(Payment, null=True, blank=True, on_delete=models.PROTECT, related_name="fiscal_documents")
    replaces = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="replacements")
    document_type = models.CharField(max_length=1, choices=DocumentType.choices)
    cfdi_version = models.CharField(max_length=8, default="4.0")
    provider_code = models.CharField(max_length=80)
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    provider_request_id = models.CharField(max_length=120, blank=True)
    cfdi_uuid = models.UUIDField(null=True, blank=True, unique=True)
    state = models.CharField(max_length=16, choices=State.choices, default=State.PREPARED, db_index=True)
    issuer_rfc = models.CharField(max_length=13, blank=True)
    recipient_rfc = models.CharField(max_length=13)
    recipient_name = models.CharField(max_length=250)
    recipient_fiscal_regime = models.CharField(max_length=3)
    recipient_postal_code = models.CharField(max_length=5)
    cfdi_use = models.CharField(max_length=3)
    payment_method = models.CharField(max_length=3, blank=True)
    payment_form = models.CharField(max_length=2, blank=True)
    currency = models.CharField(max_length=3, default="MXN")
    request_payload = models.JSONField(default=dict)
    request_xml = models.TextField(blank=True)
    xml_content = models.TextField(blank=True)
    pdf_storage_key = models.CharField(max_length=500, blank=True)
    stamped_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=2, choices=CancellationReason.choices, blank=True)
    replacement_uuid = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = [
            ("prepare_fiscaldocument", "Puede preparar una solicitud fiscal para revisión"),
            ("generate_fiscaldocument_xml", "Puede generar el XML firmado de un CFDI preparado"),
            ("send_fiscaldocument", "Puede enviar un CFDI firmado al PAC configurado"),
            ("send_customer_copy_fiscaldocument", "Puede enviar una copia del CFDI timbrado al cliente"),
            ("query_fiscaldocument", "Puede consultar un CFDI enviado en FEL"),
            ("cancel_fiscaldocument", "Puede solicitar la cancelación de un CFDI timbrado ante FEL"),
        ]
        constraints = [models.CheckConstraint(condition=(models.Q(invoice__isnull=False, payment__isnull=True, credit_note__isnull=True) | models.Q(invoice__isnull=True, payment__isnull=False, credit_note__isnull=True) | models.Q(invoice__isnull=True, payment__isnull=True, credit_note__isnull=False)), name="billing_fiscal_one_source")]

    def clean(self):
        sources = [bool(self.invoice_id), bool(self.payment_id), bool(self.credit_note_id)]
        if sum(sources) != 1:
            raise ValidationError("Un CFDI debe corresponder exactamente a una factura, cobro o nota de crédito.")
        if self.payment_id and self.document_type != self.DocumentType.PAYMENT:
            raise ValidationError("Un CFDI ligado a un cobro debe ser de tipo Pago.")
        if self.invoice_id and self.document_type != self.DocumentType.INCOME:
            raise ValidationError("Una factura interna solo puede ligarse a un CFDI tipo Ingreso.")
        if self.credit_note_id and self.document_type != self.DocumentType.CREDIT_NOTE:
            raise ValidationError("Una nota de crédito solo puede ligarse a un CFDI tipo Egreso.")
        if self.credit_note_id and self.credit_note.state != CustomerCreditNote.State.POSTED:
            raise ValidationError("Solo una nota de crédito aplicada puede ligarse a su CFDI de egreso.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = FiscalDocument.objects.get(pk=self.pk)
            if previous.state != self.State.PREPARED:
                protected = ["invoice_id", "credit_note_id", "payment_id", "replaces_id", "document_type", "cfdi_version", "provider_code", "idempotency_key", "issuer_rfc", "recipient_rfc", "recipient_name", "recipient_fiscal_regime", "recipient_postal_code", "cfdi_use", "payment_method", "payment_form", "currency", "request_payload"]
                if any(getattr(previous, field) != getattr(self, field) for field in protected):
                    raise ValidationError("La solicitud fiscal enviada no se puede editar.")
            if previous.request_xml and previous.request_xml != self.request_xml:
                raise ValidationError("El XML firmado se conserva como evidencia y no se puede reemplazar.")
        self.clean()
        return super().save(*args, **kwargs)


class FiscalEvent(models.Model):
    class Action(models.TextChoices):
        PREPARE = "prepare", "Preparación"
        XML_GENERATE = "xml", "Generación de XML"
        SUBMIT = "submit", "Envío"
        STAMP = "stamp", "Timbrado"
        QUERY = "query", "Consulta"
        CANCEL = "cancel", "Cancelación"
        RESPONSE = "response", "Respuesta"
        ERROR = "error", "Error"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fiscal_document = models.ForeignKey(FiscalDocument, on_delete=models.PROTECT, related_name="events")
    action = models.CharField(max_length=12, choices=Action.choices)
    state_before = models.CharField(max_length=16, blank=True)
    state_after = models.CharField(max_length=16, blank=True)
    provider_request_id = models.CharField(max_length=120, blank=True)
    response_code = models.CharField(max_length=80, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["occurred_at"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Los eventos del proveedor fiscal son inmutables.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los eventos del proveedor fiscal no se pueden eliminar.")
