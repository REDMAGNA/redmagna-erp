from decimal import Decimal

from rest_framework import serializers
from django.db.models import Sum

from sales.models import WorkOrder
from billing.fiscal.catalogs import is_sat_catalog_value

from .models import InventoryCount, InventoryCountLine, Product, ReorderRule, StockBalance, StockLocation, StockMovement, StockReservation, StockTransfer, StockUnit


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ["id", "sku", "barcode", "name", "description", "kind", "tracking_policy", "unit", "sat_product_service_key", "sat_unit_key", "sat_tax_object", "sat_tax_factor", "sat_border_8_eligible", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "sat_border_8_eligible", "created_at", "updated_at"]

    def validate_sku(self, value):
        return value.strip().upper()

    def validate_barcode(self, value):
        value = value.strip()
        duplicates = Product.objects.filter(barcode=value)
        if self.instance:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if value and duplicates.exists():
            raise serializers.ValidationError("Este código de barras ya está asignado a otro producto.")
        if value and StockLocation.objects.filter(barcode=value).exists():
            raise serializers.ValidationError("Este código de barras ya está asignado a una ubicación.")
        return value

    def validate_sat_product_service_key(self, value):
        value = value.strip()
        if value and not is_sat_catalog_value("c_ClaveProdServ", value):
            raise serializers.ValidationError("La clave no existe en el catálogo SAT local de productos y servicios.")
        return value

    def validate_sat_unit_key(self, value):
        value = value.strip().upper()
        if value and not is_sat_catalog_value("c_ClaveUnidad", value):
            raise serializers.ValidationError("La clave no existe en el catálogo SAT local de unidades.")
        return value

    def validate(self, attrs):
        kind = attrs.get("kind", self.instance.kind if self.instance else Product.Kind.STOCKABLE)
        tracking_policy = attrs.get("tracking_policy", self.instance.tracking_policy if self.instance else Product.TrackingPolicy.QUANTITY)
        if kind == Product.Kind.SERVICE and tracking_policy != Product.TrackingPolicy.QUANTITY:
            raise serializers.ValidationError({"tracking_policy": "Los servicios no pueden tener seguimiento por serie."})
        if self.instance:
            sku = attrs.get("sku", self.instance.sku).strip().upper()
            kind = attrs.get("kind", self.instance.kind)
            if (sku != self.instance.sku or kind != self.instance.kind) and (self.instance.stock_movements.exists() or self.instance.stock_balances.exists() or self.instance.inventory_count_lines.exists() or self.instance.work_order_material_requirements.exists()):
                raise serializers.ValidationError("No se puede cambiar el código o tipo de un producto con historial de inventario.")
            tracking_policy = attrs.get("tracking_policy", self.instance.tracking_policy)
            if tracking_policy != self.instance.tracking_policy and (self.instance.stock_movements.exists() or self.instance.stock_balances.exists() or self.instance.inventory_count_lines.exists() or self.instance.serial_units.exists() or self.instance.work_order_material_requirements.exists()):
                raise serializers.ValidationError("No se puede cambiar el seguimiento después de registrar movimientos de inventario.")
        return attrs


class StockLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockLocation
        fields = ["id", "code", "barcode", "name", "is_active"]

    def validate_code(self, value):
        return value.strip().upper()

    def validate_barcode(self, value):
        value = value.strip()
        duplicates = StockLocation.objects.filter(barcode=value)
        if self.instance:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if value and duplicates.exists():
            raise serializers.ValidationError("Este código de barras ya está asignado a otra ubicación.")
        if value and Product.objects.filter(barcode=value).exists():
            raise serializers.ValidationError("Este código de barras ya está asignado a un producto.")
        return value


class StockBalanceSerializer(serializers.ModelSerializer):
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_unit = serializers.CharField(source="product.unit", read_only=True)
    location_code = serializers.CharField(source="location.code", read_only=True)
    location_name = serializers.CharField(source="location.name", read_only=True)
    reserved_quantity = serializers.SerializerMethodField()
    available_quantity = serializers.SerializerMethodField()

    class Meta:
        model = StockBalance
        fields = ["id", "product", "product_sku", "product_name", "product_unit", "location", "location_code", "location_name", "quantity", "reserved_quantity", "available_quantity", "updated_at"]
        read_only_fields = fields

    def get_reserved_quantity(self, obj):
        return getattr(obj, "current_reserved", 0)

    def get_available_quantity(self, obj):
        return obj.quantity - self.get_reserved_quantity(obj)


class ReorderRuleSerializer(serializers.ModelSerializer):
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_unit = serializers.CharField(source="product.unit", read_only=True)
    location_code = serializers.CharField(source="location.code", read_only=True)
    location_name = serializers.CharField(source="location.name", read_only=True)
    on_hand_quantity = serializers.SerializerMethodField()
    incoming_quantity = serializers.SerializerMethodField()
    reserved_quantity = serializers.SerializerMethodField()
    unreserved_demand = serializers.SerializerMethodField()
    projected_quantity = serializers.SerializerMethodField()
    suggested_quantity = serializers.SerializerMethodField()

    class Meta:
        model = ReorderRule
        fields = ["id", "product", "product_sku", "product_name", "product_unit", "location", "location_code", "location_name", "minimum_quantity", "target_quantity", "on_hand_quantity", "incoming_quantity", "reserved_quantity", "unreserved_demand", "projected_quantity", "suggested_quantity", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "product_sku", "product_name", "product_unit", "location_code", "location_name", "on_hand_quantity", "incoming_quantity", "reserved_quantity", "unreserved_demand", "projected_quantity", "suggested_quantity", "created_at", "updated_at"]

    def get_suggested_quantity(self, obj):
        projected = self.get_projected_quantity(obj)
        return max(0, obj.target_quantity - projected) if obj.is_active and obj.product.is_active and obj.location.is_active and projected < obj.minimum_quantity else 0

    def get_on_hand_quantity(self, obj):
        on_hand = getattr(obj, "current_on_hand", None)
        return obj.on_hand_quantity if on_hand is None else on_hand

    def get_incoming_quantity(self, obj):
        incoming = getattr(obj, "current_incoming", None)
        return obj.incoming_quantity if incoming is None else incoming

    def get_projected_quantity(self, obj):
        projected = getattr(obj, "current_on_hand", None)
        if projected is None:
            return obj.projected_quantity
        incoming = self.get_incoming_quantity(obj)
        return projected - self.get_reserved_quantity(obj) - self.get_unreserved_demand(obj) + incoming

    def get_reserved_quantity(self, obj):
        reserved = getattr(obj, "current_reserved", None)
        if reserved is not None:
            return reserved
        return StockReservation.objects.filter(product=obj.product, location=obj.location, state=StockReservation.State.ACTIVE).aggregate(total=Sum("remaining_quantity"))["total"] or 0

    def get_unreserved_demand(self, obj):
        cache = self.context.setdefault("_work_order_demand_by_product", {})
        key = (obj.product_id, obj.location_id)
        if key not in cache:
            from .services import unreserved_work_order_demand

            cache[key] = unreserved_work_order_demand(obj.product_id, obj.location_id)
        return cache[key]

    def validate(self, attrs):
        product = attrs.get("product", getattr(self.instance, "product", None))
        minimum = attrs.get("minimum_quantity", getattr(self.instance, "minimum_quantity", None))
        target = attrs.get("target_quantity", getattr(self.instance, "target_quantity", None))
        location = attrs.get("location", getattr(self.instance, "location", None))
        is_active = attrs.get("is_active", getattr(self.instance, "is_active", True))
        if product and product.kind != Product.Kind.STOCKABLE:
            raise serializers.ValidationError({"product": "Solo los productos con control de existencias pueden tener regla de reabastecimiento."})
        if is_active and product and not product.is_active:
            raise serializers.ValidationError({"product": "Activa primero el producto antes de habilitar su regla de reabastecimiento."})
        if is_active and location and not location.is_active:
            raise serializers.ValidationError({"location": "Activa primero la ubicación antes de habilitar su regla de reabastecimiento."})
        if minimum is not None and minimum < 0:
            raise serializers.ValidationError({"minimum_quantity": "El mínimo no puede ser negativo."})
        if minimum is not None and target is not None and target <= minimum:
            raise serializers.ValidationError({"target_quantity": "El objetivo debe ser mayor que el mínimo."})
        return attrs


class StockMovementSerializer(serializers.ModelSerializer):
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_unit = serializers.CharField(source="product.unit", read_only=True)
    location_code = serializers.CharField(source="location.code", read_only=True)
    counterpart_location_code = serializers.CharField(source="counterpart_location.code", read_only=True, default="")
    work_order_number = serializers.CharField(source="work_order.sales_order.quote.number", read_only=True, default="")
    created_by_name = serializers.SerializerMethodField()
    serial_numbers = serializers.SerializerMethodField()

    class Meta:
        model = StockMovement
        fields = ["id", "kind", "product", "product_sku", "product_name", "product_unit", "location", "location_code", "counterpart_location_code", "transfer_line", "work_order", "work_order_number", "reservation", "quantity", "serial_numbers", "reference", "note", "created_by", "created_by_name", "created_at"]
        read_only_fields = fields

    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() or obj.created_by.get_username()

    def get_serial_numbers(self, obj):
        return list(obj.serial_events.select_related("unit").order_by("unit__serial_number").values_list("unit__serial_number", flat=True))


class StockMovementInputSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True))
    location = serializers.PrimaryKeyRelatedField(queryset=StockLocation.objects.filter(is_active=True), required=False, allow_null=True)
    work_order = serializers.PrimaryKeyRelatedField(queryset=WorkOrder.objects.all(), required=False, allow_null=True)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"))
    idempotency_key = serializers.UUIDField()
    serial_numbers = serializers.ListField(child=serializers.CharField(max_length=120, allow_blank=False), required=False, allow_empty=True, max_length=100)
    reference = serializers.CharField(max_length=120, required=False, allow_blank=True)
    note = serializers.CharField(max_length=240, required=False, allow_blank=True)

    def validate_serial_numbers(self, value):
        value = [item.strip() for item in value]
        if len(value) != len(set(value)):
            raise serializers.ValidationError("No repitas números de serie.")
        return value

    def validate(self, attrs):
        kind = self.context.get("movement_kind")
        if kind == StockMovement.Kind.RECEIPT and not attrs.get("reference", "").strip():
            raise serializers.ValidationError({"reference": "Indica la orden, remisión o referencia de origen."})
        reason_kinds = {StockMovement.Kind.RETURN, StockMovement.Kind.ADJUSTMENT_IN, StockMovement.Kind.ADJUSTMENT_OUT}
        if kind in reason_kinds and not attrs.get("note", "").strip():
            raise serializers.ValidationError({"note": "Describe el motivo de la devolución o del ajuste."})
        return attrs


class StockUnitSerializer(serializers.ModelSerializer):
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    location_code = serializers.CharField(source="location.code", read_only=True, default="", allow_null=True)
    work_order_number = serializers.CharField(source="work_order.sales_order.quote.number", read_only=True, default="")
    customer_name = serializers.CharField(source="customer.name", read_only=True, default="")
    purchase_origin = serializers.SerializerMethodField()
    events = serializers.SerializerMethodField()

    class Meta:
        model = StockUnit
        fields = ["id", "product", "product_sku", "product_name", "serial_number", "state", "location", "location_code", "work_order", "work_order_number", "customer", "customer_name", "purchase_origin", "installed_at", "warranty_until", "updated_at", "events"]
        read_only_fields = fields

    def get_purchase_origin(self, obj):
        for event in obj.events.all():
            movement = event.movement
            if movement is None or movement.kind != StockMovement.Kind.RECEIPT:
                continue
            receipt_line = getattr(movement, "purchase_receipt_line", None)
            if receipt_line is None:
                continue
            order_line = receipt_line.purchase_order_line
            receipt = receipt_line.receipt
            return {
                "purchase_order_number": order_line.purchase_order.number,
                "supplier_name": order_line.purchase_order.supplier.name,
                "purchase_line_number": order_line.line_number,
                "receipt_date": receipt.receipt_date,
            }
        return None

    def get_events(self, obj):
        return [{
            "action": event.action,
            "state_before": event.state_before,
            "state_after": event.state_after,
            "movement": str(event.movement_id) if event.movement_id else "",
            "from_location_code": event.from_location.code if event.from_location_id else "",
            "to_location_code": event.to_location.code if event.to_location_id else "",
            "work_order_number": event.work_order.sales_order.quote.number if event.work_order_id else "",
            "customer_name": event.customer.name if event.customer_id else "",
            "actor_name": event.created_by.get_full_name() or event.created_by.get_username(),
            "created_at": event.created_at,
        } for event in obj.events.all()]


class StockUnitInstallSerializer(serializers.Serializer):
    installed_at = serializers.DateField()
    warranty_until = serializers.DateField(required=False, allow_null=True)

    def validate(self, attrs):
        warranty_until = attrs.get("warranty_until")
        if warranty_until and warranty_until < attrs["installed_at"]:
            raise serializers.ValidationError({"warranty_until": "La garantía no puede vencer antes de la instalación."})
        return attrs


class StockUnitReservationInputSerializer(serializers.Serializer):
    work_order = serializers.PrimaryKeyRelatedField(queryset=WorkOrder.objects.all())


class StockTransferLineInputSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True, kind=Product.Kind.STOCKABLE))
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"))
    serial_numbers = serializers.ListField(child=serializers.CharField(max_length=120, allow_blank=False), required=False, allow_empty=True, max_length=100)

    def validate_serial_numbers(self, value):
        value = [item.strip() for item in value]
        if len(value) != len(set(value)):
            raise serializers.ValidationError("No repitas números de serie.")
        return value


class StockTransferInputSerializer(serializers.Serializer):
    source_location = serializers.PrimaryKeyRelatedField(queryset=StockLocation.objects.filter(is_active=True))
    destination_location = serializers.PrimaryKeyRelatedField(queryset=StockLocation.objects.filter(is_active=True))
    idempotency_key = serializers.UUIDField()
    reference = serializers.CharField(max_length=120, required=False, allow_blank=True)
    note = serializers.CharField(max_length=240, required=False, allow_blank=True)
    lines = StockTransferLineInputSerializer(many=True, allow_empty=False)

    def validate(self, attrs):
        if attrs["source_location"].pk == attrs["destination_location"].pk:
            raise serializers.ValidationError({"destination_location": "El origen y destino deben ser distintos."})
        if not attrs.get("note", "").strip():
            raise serializers.ValidationError({"note": "Describe el motivo del traspaso."})
        product_ids = [line["product"].pk for line in attrs["lines"]]
        if len(product_ids) != len(set(product_ids)):
            raise serializers.ValidationError({"lines": "Cada producto debe aparecer una sola vez en el traspaso."})
        return attrs


class StockTransferLineSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    product = serializers.UUIDField(source="product_id", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    serial_numbers = serializers.SerializerMethodField()

    def get_serial_numbers(self, obj):
        return list(obj.movements.filter(kind=StockMovement.Kind.TRANSFER_OUT).values_list("serial_events__unit__serial_number", flat=True).exclude(serial_events__unit__serial_number__isnull=True))


class StockTransferSerializer(serializers.ModelSerializer):
    source_location_code = serializers.CharField(source="source_location.code", read_only=True)
    source_location_name = serializers.CharField(source="source_location.name", read_only=True)
    destination_location_code = serializers.CharField(source="destination_location.code", read_only=True)
    destination_location_name = serializers.CharField(source="destination_location.name", read_only=True)
    created_by_name = serializers.SerializerMethodField()
    lines = StockTransferLineSerializer(many=True, read_only=True)

    class Meta:
        model = StockTransfer
        fields = ["id", "source_location", "source_location_code", "source_location_name", "destination_location", "destination_location_code", "destination_location_name", "idempotency_key", "reference", "note", "created_by_name", "created_at", "lines"]
        read_only_fields = fields

    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() or obj.created_by.get_username()


class StockReservationEventSerializer(serializers.Serializer):
    action = serializers.CharField()
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3)
    remaining_after = serializers.DecimalField(max_digits=14, decimal_places=3)
    created_by_name = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField()

    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() or obj.created_by.get_username()


class StockReservationSerializer(serializers.ModelSerializer):
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_unit = serializers.CharField(source="product.unit", read_only=True)
    location_code = serializers.CharField(source="location.code", read_only=True)
    work_order_number = serializers.CharField(source="work_order.sales_order.quote.number", read_only=True)
    events = StockReservationEventSerializer(many=True, read_only=True)

    class Meta:
        model = StockReservation
        fields = ["id", "work_order", "work_order_number", "product", "product_sku", "product_name", "product_unit", "location", "location_code", "quantity", "remaining_quantity", "state", "idempotency_key", "created_by", "created_at", "updated_at", "events"]
        read_only_fields = fields


class StockReservationInputSerializer(serializers.Serializer):
    work_order = serializers.PrimaryKeyRelatedField(queryset=WorkOrder.objects.all())
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True, kind=Product.Kind.STOCKABLE, tracking_policy=Product.TrackingPolicy.QUANTITY))
    location = serializers.PrimaryKeyRelatedField(queryset=StockLocation.objects.filter(is_active=True))
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"))
    idempotency_key = serializers.UUIDField()


class InventoryCountCreateSerializer(serializers.Serializer):
    location = serializers.PrimaryKeyRelatedField(queryset=StockLocation.objects.filter(is_active=True))
    products = serializers.ListField(child=serializers.UUIDField(), allow_empty=False, max_length=500)
    reason = serializers.CharField(max_length=240, allow_blank=False)

    def validate_products(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("No repitas productos en el mismo conteo.")
        return value

    def validate(self, attrs):
        products = Product.objects.filter(pk__in=attrs["products"], is_active=True, kind=Product.Kind.STOCKABLE)
        if products.count() != len(attrs["products"]):
            raise serializers.ValidationError({"products": "Selecciona productos activos con existencias."})
        return attrs


class InventoryCountQuantitySerializer(serializers.Serializer):
    counted_quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0"), required=False)
    counted_serial_numbers = serializers.ListField(child=serializers.CharField(max_length=120, allow_blank=False), required=False, allow_empty=True, max_length=500)

    def validate_counted_serial_numbers(self, value):
        value = [serial.strip() for serial in value]
        if any(not serial for serial in value) or len(value) != len(set(value)):
            raise serializers.ValidationError("Las series deben estar completas y no repetirse.")
        return value

    def validate(self, attrs):
        if ("counted_quantity" in attrs) == ("counted_serial_numbers" in attrs):
            raise serializers.ValidationError("Captura una cantidad o la lista de números de serie, según el producto.")
        return attrs


class InventoryCountLineSerializer(serializers.ModelSerializer):
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    unit = serializers.CharField(source="product.unit", read_only=True)
    tracking_policy = serializers.CharField(source="product.tracking_policy", read_only=True)
    expected_serial_numbers = serializers.SerializerMethodField()
    difference = serializers.SerializerMethodField()

    class Meta:
        model = InventoryCountLine
        fields = ["id", "product", "product_sku", "product_name", "unit", "tracking_policy", "expected_quantity", "counted_quantity", "expected_serial_numbers", "counted_serials", "difference", "counted_by", "counted_at", "movement", "adjustment_in_movement", "adjustment_out_movement"]
        read_only_fields = fields

    def get_expected_serial_numbers(self, obj):
        return [item["serial_number"] for item in obj.expected_serials]

    def get_difference(self, obj):
        return None if obj.counted_quantity is None else obj.counted_quantity - obj.expected_quantity


class InventoryCountSerializer(serializers.ModelSerializer):
    location_code = serializers.CharField(source="location.code", read_only=True)
    created_by_name = serializers.SerializerMethodField()
    reviewed_by_name = serializers.SerializerMethodField()
    lines = InventoryCountLineSerializer(many=True, read_only=True)

    class Meta:
        model = InventoryCount
        fields = ["id", "location", "location_code", "reason", "state", "created_by", "created_by_name", "reviewed_by", "reviewed_by_name", "created_at", "submitted_at", "applied_at", "lines"]
        read_only_fields = fields

    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() or obj.created_by.get_username()

    def get_reviewed_by_name(self, obj):
        if not obj.reviewed_by_id:
            return ""
        return obj.reviewed_by.get_full_name() or obj.reviewed_by.get_username()
