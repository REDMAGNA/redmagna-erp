import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Product(models.Model):
    class Kind(models.TextChoices):
        STOCKABLE = "stockable", "Producto con existencias"
        SERVICE = "service", "Servicio"

    class TrackingPolicy(models.TextChoices):
        QUANTITY = "quantity", "Por cantidad"
        SERIAL = "serial", "Por número de serie"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sku = models.CharField(max_length=64, unique=True)
    barcode = models.CharField(max_length=128, blank=True, default="")
    name = models.CharField(max_length=200)
    description = models.CharField(max_length=500, blank=True)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.STOCKABLE)
    tracking_policy = models.CharField(max_length=12, choices=TrackingPolicy.choices, default=TrackingPolicy.QUANTITY)
    unit = models.CharField(max_length=16, default="pza")
    sat_product_service_key = models.CharField(max_length=8, blank=True, default="")
    sat_unit_key = models.CharField(max_length=3, blank=True, default="")
    sat_tax_object = models.CharField(max_length=2, choices=[("01", "No objeto"), ("02", "Sí objeto")], default="02")
    sat_tax_factor = models.CharField(max_length=8, choices=[("Tasa", "Tasa"), ("Exento", "Exento")], default="Tasa")
    sat_border_8_eligible = models.BooleanField(
        default=False,
        help_text="Solo marca si Contabilidad verificó que esta ClaveProdServ tiene la marca SAT para el estímulo fronterizo al 8%.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sku"]
        constraints = [models.UniqueConstraint(fields=["barcode"], condition=~models.Q(barcode=""), name="inventory_product_barcode_uniq")]

    def save(self, *args, **kwargs):
        self.sku = self.sku.strip().upper()
        self.barcode = self.barcode.strip()
        if not self.sku:
            raise ValidationError({"sku": "El código del producto es obligatorio."})
        if self.barcode and StockLocation.objects.filter(barcode=self.barcode).exists():
            raise ValidationError({"barcode": "Este código de barras ya está asignado a una ubicación."})
        if self.kind not in self.Kind.values:
            raise ValidationError({"kind": "Tipo de producto no reconocido."})
        if self.sat_border_8_eligible:
            from billing.fiscal.catalogs import is_sat_catalog_value

            if len(self.sat_product_service_key) != 8 or not self.sat_product_service_key.isdigit() or not is_sat_catalog_value("c_ClaveProdServ", self.sat_product_service_key):
                raise ValidationError({"sat_border_8_eligible": "La elegibilidad al 8% solo puede marcarse con una clave SAT de producto o servicio existente."})
        if not self._state.adding:
            previous = Product.objects.get(pk=self.pk)
            if previous.sat_product_service_key != self.sat_product_service_key and self.sat_border_8_eligible:
                self.sat_border_8_eligible = False
                if kwargs.get("update_fields") is not None:
                    kwargs["update_fields"] = set(kwargs["update_fields"]) | {"sat_border_8_eligible"}
            has_history = self.stock_movements.exists() or self.stock_balances.exists() or self.inventory_count_lines.exists() or self.work_order_material_requirements.exists()
            if (previous.sku != self.sku or previous.kind != self.kind) and has_history:
                raise ValidationError("No se puede cambiar el código o tipo de un producto con historial de inventario.")
            if previous.tracking_policy != self.tracking_policy and has_history:
                raise ValidationError("No se puede cambiar el seguimiento después de registrar movimientos de inventario.")
        if self.kind == self.Kind.SERVICE and self.tracking_policy != self.TrackingPolicy.QUANTITY:
            raise ValidationError({"tracking_policy": "Los servicios no pueden tener seguimiento de inventario por serie."})
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.sku} · {self.name}"


class StockLocation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=24, unique=True)
    barcode = models.CharField(max_length=128, blank=True, default="")
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        constraints = [models.UniqueConstraint(fields=["barcode"], condition=~models.Q(barcode=""), name="inventory_location_barcode_uniq")]

    def clean(self):
        if self.pk and not self.is_active and self.stock_balances.filter(quantity__gt=0).exists():
            raise ValidationError({"is_active": "No puedes desactivar una ubicación con existencias; traspásalas primero."})
        if self.pk and not self.is_active and self.expected_purchase_order_lines.filter(
            purchase_order__status__in=["ordered", "partial"],
            received_quantity__lt=models.F("quantity"),
        ).exists():
            raise ValidationError({"is_active": "No puedes desactivar una ubicación con compras pendientes de recibir."})
        if self.pk and not self.is_active and self.work_order_material_requirements.filter(
            work_order__status__in=["planned", "in_progress", "blocked"],
        ).exists():
            raise ValidationError({"is_active": "No puedes desactivar una ubicación asignada a materiales pendientes de órdenes activas."})

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        self.barcode = self.barcode.strip()
        if self.barcode and Product.objects.filter(barcode=self.barcode).exists():
            raise ValidationError({"barcode": "Este código de barras ya está asignado a un producto."})
        if not self._state.adding:
            previous = StockLocation.objects.get(pk=self.pk)
            if previous.code != self.code and self.stock_movements.exists():
                raise ValidationError("No cambies el código de una ubicación con historial de movimientos.")
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} · {self.name}"


class StockBalance(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="stock_balances")
    location = models.ForeignKey(StockLocation, on_delete=models.PROTECT, related_name="stock_balances")
    quantity = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["product__sku", "location__code"]
        constraints = [
            models.UniqueConstraint(fields=["product", "location"], name="inventory_balance_product_location_uniq"),
            models.CheckConstraint(condition=models.Q(quantity__gte=0), name="inventory_balance_nonnegative"),
        ]


class ReorderRule(models.Model):
    """Location-specific min/max replenishment threshold for a stockable product."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="reorder_rules")
    location = models.ForeignKey(StockLocation, on_delete=models.PROTECT, related_name="reorder_rules")
    minimum_quantity = models.DecimalField(max_digits=14, decimal_places=3)
    target_quantity = models.DecimalField(max_digits=14, decimal_places=3)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["product__sku", "location__code"]
        constraints = [
            models.UniqueConstraint(fields=["product", "location"], name="inventory_reorder_product_location_uniq"),
            models.CheckConstraint(condition=models.Q(minimum_quantity__gte=0), name="inventory_reorder_min_nonnegative"),
            models.CheckConstraint(condition=models.Q(target_quantity__gt=models.F("minimum_quantity")), name="inventory_reorder_target_gt_min"),
        ]

    def clean(self):
        if self.product_id and self.product.kind != Product.Kind.STOCKABLE:
            raise ValidationError({"product": "Solo los productos con control de existencias pueden tener regla de reabastecimiento."})
        if self.is_active and self.product_id and not self.product.is_active:
            raise ValidationError({"product": "Activa primero el producto antes de habilitar su regla de reabastecimiento."})
        if self.is_active and self.location_id and not self.location.is_active:
            raise ValidationError({"location": "Activa primero la ubicación antes de habilitar su regla de reabastecimiento."})
        if self.minimum_quantity < 0:
            raise ValidationError({"minimum_quantity": "El mínimo no puede ser negativo."})
        if self.target_quantity <= self.minimum_quantity:
            raise ValidationError({"target_quantity": "El objetivo debe ser mayor que el mínimo."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def on_hand_quantity(self):
        return StockBalance.objects.filter(product=self.product, location=self.location).values_list("quantity", flat=True).first() or 0

    @property
    def incoming_quantity(self):
        from purchasing.models import PurchaseOrderLine

        pending = PurchaseOrderLine.objects.filter(
            product=self.product,
            expected_location=self.location,
            purchase_order__status__in=["ordered", "partial"],
            received_quantity__lt=models.F("quantity"),
        ).aggregate(total=models.Sum(models.F("quantity") - models.F("received_quantity")))["total"]
        return pending or 0

    @property
    def projected_quantity(self):
        reserved = StockReservation.objects.filter(
            product=self.product, location=self.location, state=StockReservation.State.ACTIVE,
        ).aggregate(total=models.Sum("remaining_quantity"))["total"] or 0
        reserved_serials = StockUnit.objects.filter(
            product=self.product, location=self.location, state=StockUnit.State.RESERVED,
        ).count()
        projected = self.on_hand_quantity - reserved - reserved_serials + self.incoming_quantity
        from .services import unreserved_work_order_demand

        projected -= unreserved_work_order_demand(self.product_id, self.location_id)
        return projected

    @property
    def suggested_quantity(self):
        projected = self.projected_quantity
        return max(0, self.target_quantity - projected) if self.is_active and self.product.is_active and self.location.is_active and projected < self.minimum_quantity else 0


class StockMovement(models.Model):
    class Kind(models.TextChoices):
        RECEIPT = "receipt", "Entrada"
        ISSUE = "issue", "Salida a trabajo"
        RETURN = "return", "Devolución de trabajo"
        ADJUSTMENT_IN = "adjustment_in", "Ajuste positivo"
        ADJUSTMENT_OUT = "adjustment_out", "Ajuste negativo"
        TRANSFER_IN = "transfer_in", "Traspaso recibido"
        TRANSFER_OUT = "transfer_out", "Traspaso enviado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=16, choices=Kind.choices, db_index=True)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="stock_movements")
    location = models.ForeignKey(StockLocation, on_delete=models.PROTECT, related_name="stock_movements")
    work_order = models.ForeignKey("sales.WorkOrder", null=True, blank=True, on_delete=models.PROTECT, related_name="stock_movements")
    reservation = models.ForeignKey("StockReservation", null=True, blank=True, on_delete=models.PROTECT, related_name="movements")
    transfer_line = models.ForeignKey("StockTransferLine", null=True, blank=True, on_delete=models.PROTECT, related_name="movements")
    counterpart_location = models.ForeignKey(StockLocation, null=True, blank=True, on_delete=models.PROTECT, related_name="counterpart_movements")
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    reference = models.CharField(max_length=120, blank=True)
    note = models.CharField(max_length=240, blank=True)
    idempotency_key = models.UUIDField(null=True, blank=True, unique=True)
    request_fingerprint = models.CharField(max_length=64, blank=True, default="", editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="redmagna_stock_movements")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = [
            ("receive_stock", "Puede registrar entradas de inventario"),
            ("issue_stock", "Puede entregar materiales a órdenes de trabajo"),
            ("adjust_stock", "Puede realizar ajustes de inventario"),
            ("transfer_stock", "Puede realizar traspasos entre ubicaciones"),
        ]
        constraints = [models.CheckConstraint(condition=models.Q(quantity__gt=0), name="inventory_movement_positive")]

    def clean(self):
        if self.quantity <= 0:
            raise ValidationError({"quantity": "La cantidad debe ser mayor que cero."})
        if bool(self.idempotency_key) != bool(self.request_fingerprint):
            raise ValidationError("La clave de reintento y su huella deben guardarse juntas.")
        if self.kind == self.Kind.RECEIPT and not (self.reference or "").strip():
            raise ValidationError({"reference": "Indica la orden, remisión o referencia que origina la entrada al almacén."})
        if self.kind in {self.Kind.RETURN, self.Kind.ADJUSTMENT_IN, self.Kind.ADJUSTMENT_OUT} and not (self.note or "").strip():
            raise ValidationError({"note": "Indica el motivo de la devolución o del ajuste para conservar la bitácora."})
        if self.product_id and self.product.kind != Product.Kind.STOCKABLE:
            raise ValidationError({"product": "Los servicios no tienen movimientos de inventario."})
        work_kinds = {self.Kind.ISSUE, self.Kind.RETURN}
        transfer_kinds = {self.Kind.TRANSFER_IN, self.Kind.TRANSFER_OUT}
        if self.kind in work_kinds and not self.work_order_id:
            raise ValidationError({"work_order": "La salida o devolución debe ligarse a una orden de trabajo."})
        if self.reservation_id:
            reservation = self.reservation
            if self.kind != self.Kind.ISSUE or reservation.product_id != self.product_id or reservation.location_id != self.location_id or reservation.work_order_id != self.work_order_id:
                raise ValidationError("La reserva del movimiento debe coincidir con su producto, ubicación y orden de trabajo.")
        if self.kind not in work_kinds and self.work_order_id:
            raise ValidationError({"work_order": "Este tipo de movimiento no puede ligarse a una orden de trabajo."})
        if self.kind in transfer_kinds and (not self.transfer_line_id or not self.counterpart_location_id):
            raise ValidationError("Los movimientos de traspaso requieren su renglón y ubicación contraparte.")
        if self.kind in transfer_kinds and self.transfer_line_id:
            line = self.transfer_line
            transfer = line.transfer
            expected_location = transfer.destination_location_id if self.kind == self.Kind.TRANSFER_IN else transfer.source_location_id
            expected_counterpart = transfer.source_location_id if self.kind == self.Kind.TRANSFER_IN else transfer.destination_location_id
            if self.product_id != line.product_id or self.quantity != line.quantity or self.location_id != expected_location or self.counterpart_location_id != expected_counterpart:
                raise ValidationError("El movimiento no coincide con el producto, cantidad u origen/destino de su traspaso.")
        if self.kind not in transfer_kinds and (self.transfer_line_id or self.counterpart_location_id):
            raise ValidationError("Solo los traspasos pueden indicar una ubicación contraparte.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Los movimientos de inventario son inmutables.")
        self.clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los movimientos de inventario no se pueden eliminar.")

    def __str__(self):
        return f"{self.get_kind_display()} · {self.product.sku} · {self.quantity}"


class StockReservation(models.Model):
    class State(models.TextChoices):
        ACTIVE = "active", "Activa"
        FULFILLED = "fulfilled", "Surtida"
        RELEASED = "released", "Liberada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    work_order = models.ForeignKey("sales.WorkOrder", on_delete=models.PROTECT, related_name="stock_reservations")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="stock_reservations")
    location = models.ForeignKey(StockLocation, on_delete=models.PROTECT, related_name="stock_reservations")
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    remaining_quantity = models.DecimalField(max_digits=14, decimal_places=3)
    state = models.CharField(max_length=12, choices=State.choices, default=State.ACTIVE, db_index=True)
    idempotency_key = models.UUIDField(unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="redmagna_stock_reservations")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="inventory_reservation_quantity_positive"),
            models.CheckConstraint(condition=models.Q(remaining_quantity__gte=0) & models.Q(remaining_quantity__lte=models.F("quantity")), name="inventory_reservation_remaining_valid"),
            models.UniqueConstraint(fields=["work_order", "product", "location"], condition=models.Q(state="active"), name="inventory_active_reservation_unique"),
        ]

    def clean(self):
        if self.product_id and (self.product.kind != Product.Kind.STOCKABLE or self.product.tracking_policy != Product.TrackingPolicy.QUANTITY):
            raise ValidationError({"product": "Las reservas iniciales requieren un producto activo con control por cantidad; los números de serie se asignan al entregar."})
        if self.state == self.State.ACTIVE and self.remaining_quantity <= 0:
            raise ValidationError({"remaining_quantity": "Una reserva activa debe conservar cantidad pendiente."})
        if self.state in {self.State.FULFILLED, self.State.RELEASED} and self.remaining_quantity != 0:
            raise ValidationError({"remaining_quantity": "Una reserva surtida o liberada debe tener cantidad pendiente igual a cero."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class StockReservationEvent(models.Model):
    class Action(models.TextChoices):
        RESERVED = "reserved", "Reservada"
        ISSUED = "issued", "Entregada"
        RELEASED = "released", "Liberada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reservation = models.ForeignKey(StockReservation, on_delete=models.PROTECT, related_name="events")
    movement = models.ForeignKey(StockMovement, null=True, blank=True, on_delete=models.PROTECT, related_name="reservation_events")
    action = models.CharField(max_length=12, choices=Action.choices)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    remaining_after = models.DecimalField(max_digits=14, decimal_places=3)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="redmagna_stock_reservation_events")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [models.CheckConstraint(condition=models.Q(quantity__gt=0), name="inventory_res_event_quantity_positive")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("El historial de reservas es inmutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("El historial de reservas no se puede eliminar.")


class InventoryCount(models.Model):
    class State(models.TextChoices):
        DRAFT = "draft", "En captura"
        SUBMITTED = "submitted", "Pendiente de revisión"
        APPLIED = "applied", "Aplicado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    location = models.ForeignKey(StockLocation, on_delete=models.PROTECT, related_name="inventory_counts")
    reason = models.CharField(max_length=240)
    state = models.CharField(max_length=12, choices=State.choices, default=State.DRAFT, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_inventory_counts")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="reviewed_inventory_counts")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = [("review_inventorycount", "Puede revisar y aplicar conteos físicos")]

    def __str__(self):
        return f"Conteo {self.pk} · {self.location.code}"


class InventoryCountLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    count = models.ForeignKey(InventoryCount, on_delete=models.PROTECT, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="inventory_count_lines")
    expected_quantity = models.DecimalField(max_digits=14, decimal_places=3)
    balance_updated_at = models.DateTimeField(null=True, blank=True)
    counted_quantity = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    expected_serials = models.JSONField(default=list, blank=True)
    counted_serials = models.JSONField(null=True, blank=True)
    counted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="inventory_count_entries")
    counted_at = models.DateTimeField(null=True, blank=True)
    movement = models.ForeignKey(StockMovement, null=True, blank=True, on_delete=models.PROTECT, related_name="inventory_count_lines")
    adjustment_in_movement = models.ForeignKey(StockMovement, null=True, blank=True, on_delete=models.PROTECT, related_name="inventory_count_in_lines")
    adjustment_out_movement = models.ForeignKey(StockMovement, null=True, blank=True, on_delete=models.PROTECT, related_name="inventory_count_out_lines")
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    adjustment_in_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    adjustment_out_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    class Meta:
        ordering = ["product__sku"]
        constraints = [models.UniqueConstraint(fields=["count", "product"], name="inventory_count_product_uniq"), models.CheckConstraint(condition=models.Q(expected_quantity__gte=0), name="inventory_count_expected_nonnegative"), models.CheckConstraint(condition=models.Q(counted_quantity__isnull=True) | models.Q(counted_quantity__gte=0), name="inventory_count_actual_nonnegative")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = type(self).objects.get(pk=self.pk)
            immutable_fields = ("count_id", "product_id", "expected_quantity", "balance_updated_at", "expected_serials", "idempotency_key", "adjustment_in_key", "adjustment_out_key")
            if any(getattr(self, field) != getattr(previous, field) for field in immutable_fields):
                raise ValidationError("La línea y su fotografía inicial del conteo son inmutables.")
            mutable_fields = ("counted_quantity", "counted_serials", "counted_by_id", "counted_at")
            if previous.count.state != InventoryCount.State.DRAFT and any(getattr(self, field) != getattr(previous, field) for field in mutable_fields):
                raise ValidationError("Las líneas de un conteo enviado no se pueden modificar.")
            movement_fields = ("movement_id", "adjustment_in_movement_id", "adjustment_out_movement_id")
            if previous.count.state != InventoryCount.State.SUBMITTED and any(getattr(self, field) != getattr(previous, field) for field in movement_fields):
                raise ValidationError("Los movimientos de una línea solo se pueden ligar al aplicar el conteo.")
            if previous.count.state == InventoryCount.State.SUBMITTED and any(getattr(self, field) != getattr(previous, field) for field in mutable_fields):
                raise ValidationError("Las líneas de un conteo enviado no se pueden modificar.")
        if self.product_id and (self.product.kind != Product.Kind.STOCKABLE or self.product.tracking_policy != Product.TrackingPolicy.QUANTITY):
            if not (self.product.kind == Product.Kind.STOCKABLE and self.product.tracking_policy == Product.TrackingPolicy.SERIAL and isinstance(self.expected_serials, list)):
                raise ValidationError({"product": "Los conteos requieren un producto con existencias controladas por cantidad o número de serie."})
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las líneas del conteo se conservan como historial.")


class StockUnit(models.Model):
    class State(models.TextChoices):
        IN_STOCK = "in_stock", "En almacén"
        RESERVED = "reserved", "Reservado para orden"
        ASSIGNED = "assigned", "Entregado a una orden"
        INSTALLED = "installed", "Instalado con el cliente"
        RETIRED = "retired", "Retirado del inventario"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="serial_units")
    serial_number = models.CharField(max_length=120)
    state = models.CharField(max_length=16, choices=State.choices, default=State.IN_STOCK, db_index=True)
    location = models.ForeignKey(StockLocation, null=True, blank=True, on_delete=models.PROTECT, related_name="serial_units")
    work_order = models.ForeignKey("sales.WorkOrder", null=True, blank=True, on_delete=models.PROTECT, related_name="serial_units")
    customer = models.ForeignKey("sales.Customer", null=True, blank=True, on_delete=models.PROTECT, related_name="installed_serial_units")
    installed_at = models.DateField(null=True, blank=True)
    warranty_until = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["product__sku", "serial_number"]
        constraints = [models.UniqueConstraint(fields=["product", "serial_number"], name="inventory_product_serial_uniq")]
        indexes = [models.Index(fields=["state", "location"], name="inventory_serial_state_loc_idx")]

    def clean(self):
        self.serial_number = self.serial_number.strip()
        if not self.serial_number:
            raise ValidationError({"serial_number": "El número de serie es obligatorio."})
        if self.product_id and (self.product.kind != Product.Kind.STOCKABLE or self.product.tracking_policy != Product.TrackingPolicy.SERIAL):
            raise ValidationError({"product": "El producto no está configurado para seguimiento por serie."})
        if self.state == self.State.IN_STOCK and (not self.location_id or self.work_order_id or self.customer_id or self.installed_at or self.warranty_until):
            raise ValidationError("Un equipo en almacén debe tener ubicación y no estar asignado a una orden.")
        if self.state == self.State.RESERVED and (not self.location_id or not self.work_order_id or self.customer_id or self.installed_at or self.warranty_until):
            raise ValidationError("Un equipo reservado debe conservar ubicación y orden destino, sin estar entregado ni instalado.")
        if self.state == self.State.ASSIGNED and (self.location_id or not self.work_order_id or self.customer_id or self.installed_at or self.warranty_until):
            raise ValidationError("Un equipo entregado debe estar ligado a una orden y no a una ubicación de almacén.")
        if self.state == self.State.INSTALLED and (self.location_id or not self.work_order_id or not self.customer_id or not self.installed_at):
            raise ValidationError("Un equipo instalado debe conservar orden, cliente y fecha de instalación.")
        if self.state == self.State.INSTALLED and self.work_order_id and self.customer_id and self.work_order.sales_order.quote.customer_id != self.customer_id:
            raise ValidationError("El cliente del equipo instalado debe coincidir con la orden de trabajo.")
        if self.warranty_until and (not self.installed_at or self.warranty_until < self.installed_at):
            raise ValidationError({"warranty_until": "La garantía no puede vencer antes de la instalación."})
        if self.state == self.State.RETIRED and (self.location_id or self.work_order_id or self.customer_id or self.installed_at or self.warranty_until):
            raise ValidationError("Un equipo retirado no puede estar en almacén ni asignado a una orden.")

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product.sku} · {self.serial_number}"


class StockUnitEvent(models.Model):
    class Action(models.TextChoices):
        MOVEMENT = "movement", "Movimiento de inventario"
        RESERVED = "reserved", "Reservado para orden"
        RELEASED = "released", "Reserva liberada"
        INSTALLED = "installed", "Instalación"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    unit = models.ForeignKey(StockUnit, on_delete=models.PROTECT, related_name="events")
    movement = models.ForeignKey(StockMovement, null=True, blank=True, on_delete=models.PROTECT, related_name="serial_events")
    action = models.CharField(max_length=16, choices=Action.choices, default=Action.MOVEMENT)
    state_before = models.CharField(max_length=16, blank=True)
    state_after = models.CharField(max_length=16)
    from_location = models.ForeignKey(StockLocation, null=True, blank=True, on_delete=models.PROTECT, related_name="serial_events_from")
    to_location = models.ForeignKey(StockLocation, null=True, blank=True, on_delete=models.PROTECT, related_name="serial_events_to")
    work_order = models.ForeignKey("sales.WorkOrder", null=True, blank=True, on_delete=models.PROTECT, related_name="serial_events")
    customer = models.ForeignKey("sales.Customer", null=True, blank=True, on_delete=models.PROTECT, related_name="serial_events")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="redmagna_stock_unit_events")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "id"]
        constraints = [models.UniqueConstraint(fields=["unit", "movement"], name="inventory_serial_event_unit_movement_uniq")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("El historial de números de serie es inmutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("El historial de números de serie no se puede eliminar.")


class StockTransfer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_location = models.ForeignKey(StockLocation, on_delete=models.PROTECT, related_name="outgoing_transfers")
    destination_location = models.ForeignKey(StockLocation, on_delete=models.PROTECT, related_name="incoming_transfers")
    idempotency_key = models.UUIDField(unique=True)
    reference = models.CharField(max_length=120, blank=True)
    note = models.CharField(max_length=240, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="redmagna_stock_transfers")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.CheckConstraint(condition=~models.Q(source_location=models.F("destination_location")), name="inventory_transfer_distinct_locations")]

    def clean(self):
        if self.source_location_id and self.source_location_id == self.destination_location_id:
            raise ValidationError({"destination_location": "El origen y destino deben ser distintos."})
        if not (self.note or "").strip():
            raise ValidationError({"note": "Describe el motivo del traspaso para conservar la bitácora."})

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Los traspasos confirmados son inmutables.")
        self.clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los traspasos confirmados no se pueden eliminar.")


class StockTransferLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transfer = models.ForeignKey(StockTransfer, on_delete=models.PROTECT, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="transfer_lines")
    quantity = models.DecimalField(max_digits=14, decimal_places=3)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(quantity__gt=0), name="inventory_transfer_line_positive")]

    def clean(self):
        if self.quantity <= 0:
            raise ValidationError({"quantity": "La cantidad debe ser mayor que cero."})
        if self.product_id and self.product.kind != Product.Kind.STOCKABLE:
            raise ValidationError({"product": "Los servicios no se pueden traspasar."})

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Los renglones de traspaso son inmutables.")
        self.clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los renglones de traspaso no se pueden eliminar.")
