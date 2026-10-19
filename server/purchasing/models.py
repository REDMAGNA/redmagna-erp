import uuid
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import connection, models, transaction
from django.utils import timezone


class Supplier(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField("nombre comercial", max_length=200)
    legal_name = models.CharField("razón social", max_length=250, blank=True)
    rfc = models.CharField(max_length=13, blank=True, db_index=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    lead_time_days = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(365)])
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.CheckConstraint(condition=models.Q(lead_time_days__isnull=True) | models.Q(lead_time_days__lte=365), name="purch_supplier_lead_days_valid")]

    def __str__(self):
        return self.name


class SupplierProduct(models.Model):
    """Current commercial reference for one product from one supplier.

    Purchase order lines keep their own price snapshot; changing this catalog
    never rewrites historical or already prepared orders.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="product_terms")
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT, related_name="supplier_terms")
    supplier_reference = models.CharField(max_length=120, blank=True)
    unit_cost = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    minimum_order_quantity = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True, validators=[MinValueValidator(Decimal("0.001"))])
    lead_time_days = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(365)])
    last_verified_on = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["supplier__name", "product__sku"]
        constraints = [
            models.UniqueConstraint(fields=["supplier", "product"], name="purch_supplier_product_uniq"),
            models.CheckConstraint(condition=models.Q(unit_cost__gte=0), name="purch_supplier_product_cost_valid"),
            models.CheckConstraint(condition=models.Q(lead_time_days__isnull=True) | models.Q(lead_time_days__lte=365), name="purch_supplier_product_lead_valid"),
            models.CheckConstraint(condition=models.Q(minimum_order_quantity__isnull=True) | models.Q(minimum_order_quantity__gt=0), name="purch_supplier_product_moq_valid"),
        ]

    def clean(self):
        if self.product_id and (not self.product.is_active or self.product.kind != self.product.Kind.STOCKABLE):
            raise ValidationError({"product": "Solo se permiten productos activos con control de existencias."})
        if self.supplier_id and not self.supplier.is_active:
            raise ValidationError({"supplier": "El proveedor debe estar activo."})

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.full_clean()
            return super().save(*args, **kwargs)
        with transaction.atomic():
            previous = SupplierProduct.objects.select_for_update().filter(pk=self.pk).values("supplier_id", "product_id").first()
            if previous and (previous["supplier_id"] != self.supplier_id or previous["product_id"] != self.product_id):
                raise ValidationError("El proveedor y el producto identifican la ficha y no se pueden cambiar; archívala y crea otra.")
            self.full_clean()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las condiciones de proveedor no se eliminan; desactívalas para conservar el historial.")


class SupplierProductRevision(models.Model):
    """Immutable snapshot of a supplier's commercial terms after each change."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    supplier_product = models.ForeignKey(SupplierProduct, on_delete=models.PROTECT, related_name="history")
    revision = models.PositiveIntegerField()
    supplier_reference = models.CharField(max_length=120, blank=True)
    unit_cost = models.DecimalField(max_digits=14, decimal_places=2)
    minimum_order_quantity = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    lead_time_days = models.PositiveSmallIntegerField(null=True, blank=True)
    last_verified_on = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    change_reason = models.CharField(max_length=500)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="supplier_product_revisions")
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-revision"]
        constraints = [models.UniqueConstraint(fields=["supplier_product", "revision"], name="purch_supplier_product_revision_uniq")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Las revisiones de condiciones comerciales son inmutables.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las revisiones de condiciones comerciales no se eliminan.")


class PurchaseSourcingRequest(models.Model):
    class State(models.TextChoices):
        OPEN = "open", "Solicitando ofertas"
        PARTIAL = "partial", "Adjudicación parcial"
        AWARDED = "awarded", "Oferta seleccionada"
        CANCELLED = "cancelled", "Cancelada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=24, unique=True, blank=True)
    requested_date = models.DateField(default=timezone.localdate)
    desired_date = models.DateField(null=True, blank=True)
    target_location = models.ForeignKey("inventory.StockLocation", on_delete=models.PROTECT, related_name="purchase_sourcing_requests")
    state = models.CharField(max_length=12, choices=State.choices, default=State.OPEN, db_index=True)
    notes = models.CharField(max_length=500, blank=True)
    selected_offer = models.ForeignKey("purchasing.PurchaseOffer", null=True, blank=True, on_delete=models.PROTECT, related_name="awarded_requests")
    purchase_order = models.OneToOneField("purchasing.PurchaseOrder", null=True, blank=True, on_delete=models.PROTECT, related_name="sourcing_request_record")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="purchase_sourcing_requests")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = [
            ("award_purchaseoffer", "Puede seleccionar una oferta de compra"),
            ("send_purchasingsourcingrequest", "Puede enviar solicitudes de cotización a proveedores"),
        ]

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self._state.adding and not self.number:
                year = self.requested_date.year
                prefix = f"SOL-C-RM-{year}-"
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [prefix])
                last = PurchaseSourcingRequest.objects.filter(number__startswith=prefix).order_by("-number").values_list("number", flat=True).first()
                sequence = int(last.rsplit("-", 1)[1]) + 1 if last else 1
                self.number = f"{prefix}{sequence:05d}"
            elif not self._state.adding:
                previous = PurchaseSourcingRequest.objects.select_for_update().get(pk=self.pk)
                if previous.state != self.State.OPEN and any(getattr(previous, field) != getattr(self, field) for field in ("state", "selected_offer_id", "purchase_order_id")):
                    raise ValidationError("Una solicitud atendida es inmutable.")
                if previous.state == self.State.OPEN and previous.offers.exists() and any(
                    getattr(previous, field) != getattr(self, field)
                    for field in ("requested_date", "desired_date", "target_location_id", "notes", "created_by_id")
                ):
                    raise ValidationError("No cambies la necesidad después de recibir ofertas; crea otra solicitud.")
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las solicitudes de compra no se eliminan; cancélalas para conservar el historial.")


class PurchaseSourcingLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.ForeignKey(PurchaseSourcingRequest, on_delete=models.PROTECT, related_name="lines")
    line_number = models.PositiveSmallIntegerField()
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT, related_name="purchase_sourcing_lines")
    description = models.CharField(max_length=300, blank=True)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)

    class Meta:
        ordering = ["line_number"]
        constraints = [
            models.UniqueConstraint(fields=["request", "line_number"], name="purch_sourcing_line_number_uniq"),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="purch_sourcing_line_qty_positive"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding or self.request.state != PurchaseSourcingRequest.State.OPEN:
            raise ValidationError("Los renglones de una solicitud abierta no se modifican después de registrar ofertas.")
        if not self.product.is_active or self.product.kind != self.product.Kind.STOCKABLE:
            raise ValidationError({"product": "Solo se puede cotizar un producto activo con control de existencias."})
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los renglones de compra no se eliminan.")


class PurchaseOffer(models.Model):
    class State(models.TextChoices):
        RECEIVED = "received", "Oferta recibida"
        PARTIAL = "partial", "Seleccionada parcialmente"
        SELECTED = "selected", "Seleccionada"
        REJECTED = "rejected", "No seleccionada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.ForeignKey(PurchaseSourcingRequest, on_delete=models.PROTECT, related_name="offers")
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchase_offers")
    supplier_reference = models.CharField(max_length=120, blank=True)
    quote_date = models.DateField(default=timezone.localdate)
    valid_until = models.DateField(null=True, blank=True)
    expected_date = models.DateField(null=True, blank=True)
    currency = models.CharField(max_length=3, default="MXN")
    notes = models.CharField(max_length=500, blank=True)
    state = models.CharField(max_length=10, choices=State.choices, default=State.RECEIVED, db_index=True)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="recorded_purchase_offers")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["supplier__name", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["request", "supplier"], name="purch_sourcing_supplier_unique"),
            models.CheckConstraint(condition=models.Q(currency="MXN"), name="purch_offer_currency_mxn"),
        ]

    def clean(self):
        if self.currency != "MXN":
            raise ValidationError({"currency": "La comparación inicial de ofertas se limita a MXN."})
        if self._state.adding and self.request_id and self.request.state not in {PurchaseSourcingRequest.State.OPEN, PurchaseSourcingRequest.State.PARTIAL}:
            raise ValidationError({"request": "Solo se reciben ofertas para solicitudes abiertas o parcialmente adjudicadas."})
        if self._state.adding and self.supplier_id and not self.supplier.is_active:
            raise ValidationError({"supplier": "El proveedor debe estar activo."})
        if self.valid_until and self.valid_until < self.quote_date:
            raise ValidationError({"valid_until": "La vigencia no puede terminar antes de la fecha de la oferta."})
        if self.expected_date and self.expected_date < self.quote_date:
            raise ValidationError({"expected_date": "La fecha de entrega no puede preceder a la fecha de la oferta."})

    @property
    def total(self):
        return sum((line.line_total for line in self.lines.all()), Decimal("0.00"))

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = PurchaseOffer.objects.get(pk=self.pk)
            if any(getattr(previous, field) != getattr(self, field) for field in ("request_id", "supplier_id", "supplier_reference", "quote_date", "valid_until", "expected_date", "currency", "notes", "received_by_id", "created_at")):
                raise ValidationError("Los importes y condiciones de una oferta recibida son inmutables.")
            if (previous.state, self.state) not in [(self.State.RECEIVED, self.State.PARTIAL), (self.State.RECEIVED, self.State.SELECTED), (self.State.RECEIVED, self.State.REJECTED), (self.State.PARTIAL, self.State.SELECTED), (self.State.PARTIAL, self.State.REJECTED)]:
                raise ValidationError("El estado solo cambia al seleccionar o descartar la oferta.")
            self.full_clean()
            return super().save(*args, **kwargs)
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las ofertas recibidas no se eliminan.")


class PurchaseOfferLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    offer = models.ForeignKey(PurchaseOffer, on_delete=models.PROTECT, related_name="lines")
    sourcing_line = models.ForeignKey(PurchaseSourcingLine, on_delete=models.PROTECT, related_name="offers")
    quoted_quantity = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0.000"))
    unit_cost = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ["sourcing_line__line_number"]
        constraints = [
            models.UniqueConstraint(fields=["offer", "sourcing_line"], name="purch_offer_line_unique"),
            models.CheckConstraint(condition=models.Q(quoted_quantity__gt=0), name="purch_offer_qty_positive"),
            models.CheckConstraint(condition=models.Q(unit_cost__gte=0), name="purch_offer_cost_nonnegative"),
        ]

    @property
    def line_total(self):
        return (self.quoted_quantity * self.unit_cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def save(self, *args, **kwargs):
        if self.quoted_quantity <= 0:
            raise ValidationError({"quoted_quantity": "La cantidad cotizada debe ser mayor que cero."})
        if not self._state.adding or self.offer.request_id != self.sourcing_line.request_id:
            raise ValidationError("El concepto debe pertenecer a la solicitud y las ofertas recibidas son inmutables.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los renglones de las ofertas recibidas no se eliminan.")


class PurchaseSourcingEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.ForeignKey(PurchaseSourcingRequest, on_delete=models.PROTECT, related_name="events")
    offer = models.ForeignKey(PurchaseOffer, null=True, blank=True, on_delete=models.PROTECT, related_name="events")
    supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.PROTECT, related_name="purchase_sourcing_events")
    recipient_email = models.EmailField(blank=True)
    action = models.CharField(max_length=32)
    detail = models.CharField(max_length=500, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="purchase_sourcing_events")
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["occurred_at", "id"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Los eventos de cotización de compra son inmutables.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los eventos de cotización de compra no se eliminan.")


class PurchaseFrameworkAgreement(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Borrador"
        ACTIVE = "active", "Vigente"
        CLOSED = "closed", "Cerrado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(max_length=80)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="framework_agreements")
    valid_from = models.DateField()
    valid_until = models.DateField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_purchase_framework_agreements")
    activated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="activated_purchase_framework_agreements")
    activated_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="closed_purchase_framework_agreements")
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["supplier", "reference"], name="purch_framework_supplier_ref_uniq")]
        permissions = [("activate_purchaseframeworkagreement", "Puede activar acuerdos marco de compra"), ("close_purchaseframeworkagreement", "Puede cerrar acuerdos marco de compra"), ("order_purchaseframeworkagreement", "Puede generar órdenes desde acuerdos marco")]

    def clean(self):
        if self.valid_until < self.valid_from:
            raise ValidationError({"valid_until": "La vigencia final no puede ser anterior a la fecha inicial."})

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if not self._state.adding:
                previous = PurchaseFrameworkAgreement.objects.select_for_update().get(pk=self.pk)
                if previous.status != self.Status.DRAFT and any(getattr(previous, field) != getattr(self, field) for field in ("reference", "supplier_id", "valid_from", "valid_until", "notes")):
                    raise ValidationError("Los términos de un acuerdo activado no se editan; ciérralo y crea otro acuerdo.")
            self.clean()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los acuerdos marco no se eliminan; conserva su historial.")


class PurchaseFrameworkAgreementLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agreement = models.ForeignKey(PurchaseFrameworkAgreement, on_delete=models.PROTECT, related_name="lines")
    line_number = models.PositiveSmallIntegerField()
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT, related_name="purchase_framework_lines")
    description = models.CharField(max_length=300, blank=True)
    unit_cost = models.DecimalField(max_digits=14, decimal_places=2)
    quantity_limit = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)

    class Meta:
        ordering = ["line_number"]
        constraints = [models.UniqueConstraint(fields=["agreement", "line_number"], name="purch_framework_line_no_uniq"), models.UniqueConstraint(fields=["agreement", "product"], name="purch_framework_product_uniq"), models.CheckConstraint(condition=models.Q(unit_cost__gte=0), name="purch_framework_cost_nonnegative"), models.CheckConstraint(condition=models.Q(quantity_limit__isnull=True) | models.Q(quantity_limit__gt=0), name="purch_framework_limit_positive")]

    def clean(self):
        if self.product_id and self.product.kind != self.product.Kind.STOCKABLE:
            raise ValidationError({"product": "El acuerdo marco solo admite productos con control de existencias."})

    def save(self, *args, **kwargs):
        with transaction.atomic():
            agreement = PurchaseFrameworkAgreement.objects.select_for_update().get(pk=self.agreement_id)
            if agreement.status != PurchaseFrameworkAgreement.Status.DRAFT:
                raise ValidationError("Los renglones de un acuerdo activado son inmutables.")
            self.clean()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.agreement.status != PurchaseFrameworkAgreement.Status.DRAFT:
            raise ValidationError("Los renglones de un acuerdo activado son inmutables.")
        return super().delete(*args, **kwargs)


class PurchaseOrder(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Borrador"
        ORDERED = "ordered", "Solicitada"
        PARTIAL = "partial", "Recibida parcialmente"
        RECEIVED = "received", "Recibida"
        CANCELLED = "cancelled", "Cancelada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=24, unique=True, blank=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchase_orders")
    order_date = models.DateField(default=timezone.localdate)
    expected_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True)
    notes = models.TextField(blank=True)
    sourcing_request = models.ForeignKey(PurchaseSourcingRequest, null=True, blank=True, on_delete=models.PROTECT, related_name="purchase_orders")
    sourcing_offer = models.ForeignKey(PurchaseOffer, null=True, blank=True, on_delete=models.PROTECT, related_name="purchase_orders")
    framework_agreement = models.ForeignKey(PurchaseFrameworkAgreement, null=True, blank=True, on_delete=models.PROTECT, related_name="purchase_orders")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_purchase_orders")
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="confirmed_purchase_orders")
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = [
            ("confirm_purchaseorder", "Puede confirmar órdenes de compra"),
            ("receive_purchaseorder", "Puede registrar recepciones de compra"),
            ("cancel_purchaseorder", "Puede cancelar órdenes de compra"),
        ]

    def clean(self):
        if self.expected_date and self.expected_date < self.order_date:
            raise ValidationError({"expected_date": "La fecha esperada no puede ser anterior a la fecha de la orden."})
        if self.sourcing_offer_id and (
            self.sourcing_offer.request_id != self.sourcing_request_id
            or self.sourcing_offer.supplier_id != self.supplier_id
        ):
            raise ValidationError("La orden debe conservar el proveedor y la solicitud de su oferta de origen.")
        if self.sourcing_request_id and not self.sourcing_offer_id:
            raise ValidationError({"sourcing_offer": "Una orden originada en una solicitud debe enlazar la oferta seleccionada."})
        if self.framework_agreement_id and (self.framework_agreement.supplier_id != self.supplier_id or self.sourcing_request_id or self.sourcing_offer_id):
            raise ValidationError({"framework_agreement": "La orden debe conservar el proveedor del acuerdo y no combinar orígenes de compra."})

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if not self._state.adding:
                previous = PurchaseOrder.objects.select_for_update().get(pk=self.pk)
                if previous.status != self.Status.DRAFT and any(
                    getattr(previous, field) != getattr(self, field)
                    for field in ("supplier_id", "order_date", "expected_date", "notes", "framework_agreement_id")
                ):
                    raise ValidationError("Una orden de compra solicitada ya no se puede editar.")
                self.clean()
                return super().save(*args, **kwargs)
            if not self.number:
                year = self.order_date.year
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [year + 1_000_000])
                prefix = f"OC-RM-{year}-"
                last = PurchaseOrder.objects.filter(number__startswith=prefix).order_by("-number").values_list("number", flat=True).first()
                sequence = int(last.rsplit("-", 1)[1]) + 1 if last else 1
                self.number = f"{prefix}{sequence:05d}"
            self.clean()
            return super().save(*args, **kwargs)

    @property
    def subtotal(self):
        return sum((line.line_total for line in self.lines.all()), Decimal("0.00"))

    def __str__(self):
        return self.number or str(self.id)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las órdenes de compra no se eliminan; cancélalas para conservar el historial.")


class PurchaseOrderLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    line_number = models.PositiveSmallIntegerField()
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT, related_name="purchase_order_lines")
    sourcing_line = models.ForeignKey(PurchaseSourcingLine, null=True, blank=True, on_delete=models.PROTECT, related_name="awarded_order_lines")
    framework_line = models.ForeignKey(PurchaseFrameworkAgreementLine, null=True, blank=True, on_delete=models.PROTECT, related_name="purchase_order_lines")
    expected_location = models.ForeignKey("inventory.StockLocation", null=True, blank=True, on_delete=models.PROTECT, related_name="expected_purchase_order_lines")
    description = models.CharField(max_length=300, blank=True)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    received_quantity = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0.000"))
    unit_cost = models.DecimalField(max_digits=14, decimal_places=2)
    award_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["line_number"]
        constraints = [
            models.UniqueConstraint(fields=["purchase_order", "line_number"], name="purch_order_line_no_uniq"),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="po_line_qty_positive"),
            models.CheckConstraint(condition=models.Q(unit_cost__gte=0), name="po_line_cost_nonnegative"),
            models.CheckConstraint(condition=models.Q(received_quantity__gte=0) & models.Q(received_quantity__lte=models.F("quantity")), name="po_recv_lte_ordered"),
        ]

    @property
    def line_total(self):
        return (self.quantity * self.unit_cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def clean(self):
        if self.quantity <= 0:
            raise ValidationError({"quantity": "La cantidad debe ser mayor que cero."})
        if self.unit_cost < 0:
            raise ValidationError({"unit_cost": "El costo unitario no puede ser negativo."})
        if self.product_id and self.product.kind != self.product.Kind.STOCKABLE:
            raise ValidationError({"product": "La orden de compra inicial solo admite productos con control de existencias."})
        if self.expected_location_id and not self.expected_location.is_active:
            raise ValidationError({"expected_location": "Selecciona una ubicación activa para recibir el producto."})
        if self.sourcing_line_id:
            order = self.purchase_order
            if not order.sourcing_request_id or self.sourcing_line.request_id != order.sourcing_request_id:
                raise ValidationError({"sourcing_line": "El renglón adjudicado debe pertenecer a la solicitud de la orden."})
            if self.sourcing_line.product_id != self.product_id:
                raise ValidationError({"sourcing_line": "El producto debe coincidir con el renglón adjudicado."})
        elif self.purchase_order_id and self.purchase_order.sourcing_request_id:
            raise ValidationError({"sourcing_line": "Una orden creada desde una solicitud debe conservar el renglón de origen."})
        if self.framework_line_id:
            order = self.purchase_order
            if not order.framework_agreement_id or self.framework_line.agreement_id != order.framework_agreement_id or self.framework_line.product_id != self.product_id or self.unit_cost != self.framework_line.unit_cost:
                raise ValidationError({"framework_line": "El renglón debe conservar el producto y precio acordados en el origen."})
        elif self.purchase_order_id and self.purchase_order.framework_agreement_id:
            raise ValidationError({"framework_line": "Una orden de acuerdo marco debe conservar su renglón de origen."})
        if self.received_quantity < 0 or self.received_quantity > self.quantity:
            raise ValidationError({"received_quantity": "La cantidad recibida debe estar entre cero y la cantidad solicitada."})

    def save(self, *args, **kwargs):
        with transaction.atomic():
            order = PurchaseOrder.objects.select_for_update().get(pk=self.purchase_order_id)
            if order.status != PurchaseOrder.Status.DRAFT:
                raise ValidationError("No se pueden editar conceptos de una orden ya solicitada.")
            if order.framework_agreement_id and self.framework_line_id:
                agreement = PurchaseFrameworkAgreement.objects.select_for_update().get(pk=order.framework_agreement_id)
                limit = self.framework_line.quantity_limit
                if limit is not None:
                    committed = PurchaseOrderLine.objects.filter(framework_line_id=self.framework_line_id).exclude(purchase_order__status=PurchaseOrder.Status.CANCELLED)
                    if not self._state.adding:
                        committed = committed.exclude(pk=self.pk)
                    total = committed.aggregate(total=models.Sum("quantity"))["total"] or Decimal("0.000")
                    if total + self.quantity > limit:
                        raise ValidationError({"quantity": "La cantidad excede el saldo disponible del acuerdo marco."})
            if not self._state.adding and self.sourcing_line_id:
                previous = PurchaseOrderLine.objects.get(pk=self.pk)
                fields = ("purchase_order_id", "line_number", "product_id", "sourcing_line_id", "framework_line_id", "expected_location_id", "description", "quantity", "unit_cost", "award_reason")
                if any(getattr(previous, field) != getattr(self, field) for field in fields):
                    raise ValidationError("El renglón adjudicado conserva su cantidad, costo y motivo originales.")
            if not self._state.adding and self.framework_line_id:
                previous = PurchaseOrderLine.objects.get(pk=self.pk)
                fields = ("purchase_order_id", "line_number", "product_id", "sourcing_line_id", "framework_line_id", "expected_location_id", "description", "quantity", "unit_cost", "award_reason")
                if any(getattr(previous, field) != getattr(self, field) for field in fields):
                    raise ValidationError("El renglón de acuerdo marco conserva sus términos originales; cancela la orden para liberar saldo.")
            self.clean()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            order = PurchaseOrder.objects.select_for_update().get(pk=self.purchase_order_id)
            if order.status != PurchaseOrder.Status.DRAFT:
                raise ValidationError("No se pueden quitar conceptos de una orden ya solicitada.")
            if self.sourcing_line_id or self.framework_line_id:
                raise ValidationError("Los renglones con origen no se eliminan; cancela la orden para liberar la cantidad.")
            return super().delete(*args, **kwargs)


class PurchaseReceipt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="receipts")
    idempotency_key = models.UUIDField(unique=True)
    receipt_date = models.DateTimeField(default=timezone.now)
    note = models.CharField(max_length=240, blank=True)
    request_payload = models.JSONField(default=dict)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="purchase_receipts")

    class Meta:
        ordering = ["-receipt_date"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Una recepción de compra es inmutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las recepciones de compra no se eliminan; conserva la bitácora de existencias.")


class PurchaseReceiptLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    receipt = models.ForeignKey(PurchaseReceipt, on_delete=models.PROTECT, related_name="lines")
    purchase_order_line = models.ForeignKey(PurchaseOrderLine, on_delete=models.PROTECT, related_name="receipt_lines")
    stock_movement = models.OneToOneField("inventory.StockMovement", on_delete=models.PROTECT, related_name="purchase_receipt_line")
    quantity = models.DecimalField(max_digits=14, decimal_places=3)

    class Meta:
        ordering = ["purchase_order_line__line_number"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Los renglones de recepción son inmutables.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los renglones de recepción no se eliminan.")


class SupplierBill(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="bills")
    purchase_order = models.ForeignKey(PurchaseOrder, null=True, blank=True, on_delete=models.PROTECT, related_name="supplier_bills")
    invoice_number = models.CharField(max_length=120)
    invoice_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)
    subtotal = models.DecimalField(max_digits=16, decimal_places=2)
    tax_total = models.DecimalField(max_digits=16, decimal_places=2)
    total = models.DecimalField(max_digits=16, decimal_places=2)
    registered_at = models.DateTimeField(default=timezone.now)
    registered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="registered_supplier_bills")
    opening_balance_batch_id = models.UUIDField(null=True, blank=True, db_index=True)
    opening_source_system = models.CharField(max_length=120, blank=True)
    opening_cutoff_date = models.DateField(null=True, blank=True)
    opening_original_total = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    opening_paid_before_cutoff = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["-invoice_date", "invoice_number"]
        constraints = [models.UniqueConstraint(fields=["supplier", "invoice_number"], name="supplier_bill_invoice_uniq")]
        permissions = [
            ("register_supplierbill", "Puede registrar facturas de proveedor"),
            ("attach_cfdi_supplierbill", "Puede adjuntar CFDI de proveedor"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Una factura de proveedor registrada es inmutable.")
        if self.opening_balance_batch_id:
            if self.purchase_order_id or not self.opening_source_system or not self.opening_cutoff_date or not self.opening_original_total:
                raise ValidationError("La partida de apertura necesita sistema origen, corte e importe original, y no puede ligarse a una orden de compra.")
            if self.opening_original_total <= self.opening_paid_before_cutoff or self.opening_paid_before_cutoff < 0 or self.total != self.opening_original_total:
                raise ValidationError("Los importes de apertura deben conservar saldo positivo y el total original.")
        elif self.purchase_order_id is None or any([self.opening_source_system, self.opening_cutoff_date, self.opening_original_total, self.opening_paid_before_cutoff != Decimal("0.00")]):
            raise ValidationError("La factura debe ligarse a una orden de compra o tener datos de lote de apertura completos.")
        if self.purchase_order_id and self.supplier_id != self.purchase_order.supplier_id:
            raise ValidationError({"supplier": "El proveedor debe coincidir con la orden de compra."})
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las facturas de proveedor registradas no se eliminan; conserva el historial.")

    @property
    def paid_amount(self):
        current = self.payment_applications.filter(payment__state=SupplierPayment.State.POSTED).aggregate(total=models.Sum("amount"))["total"] or Decimal("0.00")
        return self.opening_paid_before_cutoff + current

    @property
    def balance_due(self):
        return self.total - self.paid_amount

    @property
    def is_opening_balance(self):
        return bool(self.opening_balance_batch_id)

    @property
    def payment_status(self):
        paid = self.paid_amount
        if paid <= 0:
            return "open"
        return "paid" if paid >= self.total else "partial"


def supplier_bill_cfdi_upload_to(instance, filename):
    return f"purchasing/supplier-bills/{instance.supplier_bill_id}/{uuid.uuid4().hex}.xml"


class SupplierBillCFDI(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    supplier_bill = models.OneToOneField(SupplierBill, on_delete=models.PROTECT, related_name="cfdi_record")
    cfdi_uuid = models.UUIDField(unique=True)
    xml_file = models.FileField(max_length=300, upload_to=supplier_bill_cfdi_upload_to)
    sha256 = models.CharField(max_length=64)
    issuer_rfc = models.CharField(max_length=13)
    receiver_rfc = models.CharField(max_length=13)
    invoice_number = models.CharField(max_length=80, blank=True)
    invoice_date = models.DateField()
    subtotal = models.DecimalField(max_digits=16, decimal_places=2)
    tax_total = models.DecimalField(max_digits=16, decimal_places=2)
    total = models.DecimalField(max_digits=16, decimal_places=2)
    xsd_validated_at = models.DateTimeField(default=timezone.now, db_index=True)
    issuer_seal_verified = models.BooleanField(default=False)
    issuer_seal_verified_at = models.DateTimeField(null=True, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="uploaded_supplier_bills_cfdi")

    class Meta:
        ordering = ["-xsd_validated_at"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("El XML CFDI adjunto es inmutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("El XML CFDI adjunto no se puede eliminar.")


class SupplierBillLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bill = models.ForeignKey(SupplierBill, on_delete=models.PROTECT, related_name="lines")
    purchase_order_line = models.ForeignKey(PurchaseOrderLine, on_delete=models.PROTECT, related_name="supplier_bill_lines")
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=14, decimal_places=2)
    subtotal = models.DecimalField(max_digits=16, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=16, decimal_places=2)

    class Meta:
        ordering = ["purchase_order_line__line_number"]
        constraints = [
            models.UniqueConstraint(fields=["bill", "purchase_order_line"], name="supplier_bill_po_line_uniq"),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="supplier_bill_qty_positive"),
            models.CheckConstraint(condition=models.Q(unit_cost__gte=0) & models.Q(subtotal__gte=0) & models.Q(tax_amount__gte=0), name="supplier_bill_amounts_nonnegative"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Los renglones de una factura de proveedor registrada son inmutables.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los renglones de factura de proveedor no se eliminan.")


class SupplierPayment(models.Model):
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
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    currency = models.CharField(max_length=3, default="MXN")
    method = models.CharField(max_length=12, choices=Method.choices)
    paid_at = models.DateTimeField(default=timezone.now)
    reference = models.CharField(max_length=120, blank=True)
    memo = models.CharField(max_length=240, blank=True)
    state = models.CharField(max_length=8, choices=State.choices, default=State.DRAFT, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_supplier_payments")
    created_at = models.DateTimeField(auto_now_add=True)
    posted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="posted_supplier_payments")
    posted_at = models.DateTimeField(null=True, blank=True)
    reversal_reason = models.CharField(max_length=500, blank=True)
    reversed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="reversed_supplier_payments")
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversal_entry = models.ForeignKey("accounting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="supplier_payment_reversals")

    class Meta:
        ordering = ["-paid_at", "-number"]
        permissions = [
            ("post_supplierpayment", "Puede aplicar pagos a facturas de proveedor"),
            ("reverse_supplierpayment", "Puede revertir pagos aplicados a proveedores"),
        ]
        constraints = [models.CheckConstraint(condition=models.Q(currency="MXN"), name="purch_supplier_payment_mxn")]

    def save(self, *args, **kwargs):
        if self.currency != "MXN":
            raise ValidationError({"currency": "La primera versión opera únicamente en MXN."})
        if self.amount <= 0:
            raise ValidationError({"amount": "El importe pagado debe ser mayor que cero."})
        if not self._state.adding:
            previous = SupplierPayment.objects.get(pk=self.pk)
            payment_fields = ("supplier_id", "amount", "currency", "method", "paid_at", "reference", "memo", "created_by_id", "posted_by_id", "posted_at")
            reversal_fields = ("reversal_reason", "reversed_by_id", "reversed_at", "reversal_entry_id")
            if previous.state in {self.State.POSTED, self.State.REVERSED} and any(
                getattr(previous, field) != getattr(self, field)
                for field in payment_fields
            ):
                raise ValidationError("Un pago aplicado es inmutable; requiere una reversa autorizada.")
            if previous.state == self.State.POSTED:
                if self.state not in {self.State.POSTED, self.State.REVERSED}:
                    raise ValidationError("Un pago aplicado solo puede pasar a estado revertido.")
                if self.state == self.State.REVERSED and (not self.reversal_reason.strip() or not self.reversed_by_id or not self.reversed_at):
                    raise ValidationError("La reversa debe guardar motivo, autor y fecha.")
                if self.state == self.State.POSTED and any(getattr(previous, field) != getattr(self, field) for field in reversal_fields):
                    raise ValidationError("La información de reversa solo se registra al revertir el pago.")
            if previous.state == self.State.DRAFT and self.state != self.State.DRAFT:
                if self.state != self.State.POSTED or not self.posted_by_id or not self.posted_at:
                    raise ValidationError("Un borrador solo puede pasar a aplicado al registrar autor y fecha.")
            if previous.state == self.State.REVERSED and (
                self.state != self.State.REVERSED or any(getattr(previous, field) != getattr(self, field) for field in reversal_fields)
            ):
                raise ValidationError("La reversa del pago es inmutable.")
        if not self.number:
            year = self.paid_at.year
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [750000 + year])
                prefix = f"RM-PAG-{year}-"
                last = SupplierPayment.objects.filter(number__startswith=prefix).order_by("-number").values_list("number", flat=True).first()
                sequence = int(last.rsplit("-", 1)[1]) + 1 if last else 1
                self.number = f"{prefix}{sequence:06d}"
        return super().save(*args, **kwargs)


class SupplierPaymentApplication(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.ForeignKey(SupplierPayment, on_delete=models.PROTECT, related_name="applications")
    bill = models.ForeignKey(SupplierBill, on_delete=models.PROTECT, related_name="payment_applications")
    amount = models.DecimalField(max_digits=16, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["payment", "bill"], name="supplier_payment_bill_uniq"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="supplier_payment_amount_positive"),
        ]

    def clean(self):
        if self.amount <= 0:
            raise ValidationError({"amount": "El importe aplicado debe ser mayor que cero."})
        if self.payment_id and self.bill_id and self.payment.supplier_id != self.bill.supplier_id:
            raise ValidationError("El pago y la factura deben pertenecer al mismo proveedor.")

    def save(self, *args, **kwargs):
        with transaction.atomic():
            payment = SupplierPayment.objects.select_for_update().get(pk=self.payment_id)
            if payment.state != SupplierPayment.State.DRAFT:
                raise ValidationError("Las aplicaciones de un pago aplicado son inmutables.")
            self.clean()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        payment = SupplierPayment.objects.get(pk=self.payment_id)
        if payment.state != SupplierPayment.State.DRAFT:
            raise ValidationError("Las aplicaciones de un pago aplicado no se pueden borrar.")
        return super().delete(*args, **kwargs)


class PurchaseOrderEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="events")
    action = models.CharField(max_length=24)
    state_before = models.CharField(max_length=12, blank=True)
    state_after = models.CharField(max_length=12, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="purchase_order_events")
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["occurred_at"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Los eventos de compra son inmutables.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los eventos de compra no se pueden eliminar.")
