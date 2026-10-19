from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from inventory.models import Product, StockLocation

from .models import PurchaseFrameworkAgreement, PurchaseFrameworkAgreementLine, PurchaseOffer, PurchaseOfferLine, PurchaseOrder, PurchaseOrderLine, PurchaseReceipt, PurchaseSourcingEvent, PurchaseSourcingLine, PurchaseSourcingRequest, Supplier, SupplierProduct, SupplierProductRevision, SupplierBill, SupplierBillCFDI, SupplierBillLine, SupplierPayment, SupplierPaymentApplication


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ["id", "name", "legal_name", "rfc", "email", "phone", "lead_time_days", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_rfc(self, value):
        return value.strip().upper()


class SupplierProductRevisionSerializer(serializers.ModelSerializer):
    changed_by_name = serializers.CharField(source="changed_by.get_full_name", read_only=True, default="Proceso del sistema")

    class Meta:
        model = SupplierProductRevision
        fields = ["revision", "supplier_reference", "unit_cost", "minimum_order_quantity", "lead_time_days", "last_verified_on", "is_active", "change_reason", "changed_by_name", "changed_at"]


class SupplierProductSerializer(serializers.ModelSerializer):
    supplier = serializers.PrimaryKeyRelatedField(queryset=Supplier.objects.filter(is_active=True))
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True, kind=Product.Kind.STOCKABLE))
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_unit = serializers.CharField(source="product.unit", read_only=True)
    history = SupplierProductRevisionSerializer(many=True, read_only=True)
    history_reason = serializers.CharField(max_length=500, write_only=True, required=False, allow_blank=True, trim_whitespace=True)

    class Meta:
        model = SupplierProduct
        fields = ["id", "supplier", "supplier_name", "product", "product_sku", "product_name", "product_unit", "supplier_reference", "unit_cost", "minimum_order_quantity", "lead_time_days", "last_verified_on", "is_active", "history", "history_reason", "created_at", "updated_at"]
        read_only_fields = ["id", "supplier_name", "product_sku", "product_name", "product_unit", "created_at", "updated_at"]

    @transaction.atomic
    def create(self, validated_data):
        reason = validated_data.pop("history_reason", "").strip() or "Alta de condición comercial"
        instance = super().create(validated_data)
        actor = getattr(self.context.get("request"), "user", None)
        SupplierProductRevision.objects.create(
            supplier_product=instance, revision=1, supplier_reference=instance.supplier_reference,
            unit_cost=instance.unit_cost, minimum_order_quantity=instance.minimum_order_quantity,
            lead_time_days=instance.lead_time_days, last_verified_on=instance.last_verified_on,
            is_active=instance.is_active, change_reason=reason, changed_by=actor,
        )
        return instance

    @transaction.atomic
    def update(self, instance, validated_data):
        reason = validated_data.pop("history_reason", "").strip()
        current = SupplierProduct.objects.select_for_update().get(pk=instance.pk)
        if any(name in validated_data and getattr(current, f"{name}_id") != validated_data[name].pk for name in ("supplier", "product")):
            raise serializers.ValidationError("El proveedor y el producto no se pueden cambiar; archiva la ficha y crea otra.")
        tracked = ["supplier_reference", "unit_cost", "minimum_order_quantity", "lead_time_days", "last_verified_on", "is_active"]
        changed = any(name in validated_data and getattr(current, name) != validated_data[name] for name in tracked)
        if changed and len(reason) < 10:
            raise serializers.ValidationError({"history_reason": "Indica el motivo del cambio (mínimo 10 caracteres)."})
        instance = super().update(current, validated_data)
        if changed:
            next_revision = (current.history.order_by("-revision").values_list("revision", flat=True).first() or 0) + 1
            actor = getattr(self.context.get("request"), "user", None)
            SupplierProductRevision.objects.create(
                supplier_product=current, revision=next_revision, supplier_reference=current.supplier_reference,
                unit_cost=current.unit_cost, minimum_order_quantity=current.minimum_order_quantity,
                lead_time_days=current.lead_time_days, last_verified_on=current.last_verified_on,
                is_active=current.is_active, change_reason=reason, changed_by=actor,
            )
        return instance


class PurchaseOrderLineSerializer(serializers.ModelSerializer):
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_unit = serializers.CharField(source="product.unit", read_only=True)
    expected_location_code = serializers.CharField(source="expected_location.code", read_only=True, default="")
    expected_location_name = serializers.CharField(source="expected_location.name", read_only=True, default="Sin destino definido")
    line_total = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)

    class Meta:
        model = PurchaseOrderLine
        fields = ["id", "line_number", "product", "product_sku", "product_name", "product_unit", "expected_location", "expected_location_code", "expected_location_name", "description", "quantity", "received_quantity", "unit_cost", "line_total", "sourcing_line", "framework_line", "award_reason"]
        read_only_fields = ["id", "line_number", "product_sku", "product_name", "product_unit", "expected_location", "expected_location_code", "expected_location_name", "received_quantity", "line_total", "sourcing_line", "framework_line", "award_reason"]


class PurchaseOrderWriteLineSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True, kind=Product.Kind.STOCKABLE))
    expected_location = serializers.PrimaryKeyRelatedField(queryset=StockLocation.objects.filter(is_active=True))
    description = serializers.CharField(max_length=300, required=False, allow_blank=True)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"))
    unit_cost = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.00"))


class PurchaseOrderSerializer(serializers.ModelSerializer):
    supplier = serializers.PrimaryKeyRelatedField(queryset=Supplier.objects.filter(is_active=True))
    lines = PurchaseOrderLineSerializer(many=True, read_only=True)
    line_inputs = PurchaseOrderWriteLineSerializer(many=True, write_only=True, required=False)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    created_by_name = serializers.SerializerMethodField()
    subtotal = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = ["id", "number", "supplier", "supplier_name", "order_date", "expected_date", "status", "notes", "sourcing_request", "sourcing_offer", "framework_agreement", "lines", "line_inputs", "subtotal", "created_by", "created_by_name", "confirmed_by", "confirmed_at", "created_at", "updated_at"]
        read_only_fields = ["id", "number", "status", "sourcing_request", "sourcing_offer", "framework_agreement", "created_by", "created_by_name", "confirmed_by", "confirmed_at", "created_at", "updated_at"]

    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() or obj.created_by.get_username()

    def validate(self, attrs):
        expected_date = attrs.get("expected_date", getattr(self.instance, "expected_date", None))
        order_date = attrs.get("order_date", getattr(self.instance, "order_date", None))
        if expected_date and order_date and expected_date < order_date:
            raise serializers.ValidationError({"expected_date": "La fecha esperada no puede ser anterior a la fecha de la orden."})
        line_inputs = attrs.get("line_inputs")
        if line_inputs is not None and self.instance and self.instance.status != PurchaseOrder.Status.DRAFT:
            raise serializers.ValidationError({"line_inputs": "Solo puedes editar conceptos de una orden en borrador."})
        if self.instance and self.instance.sourcing_request_id:
            if line_inputs is not None or "supplier" in attrs:
                raise serializers.ValidationError("La adjudicación de origen protege proveedor, renglones y cantidades; crea otra solicitud para cambiarla.")
        if self.instance and self.instance.framework_agreement_id:
            if line_inputs is not None or "supplier" in attrs:
                raise serializers.ValidationError("Una orden de acuerdo marco conserva proveedor, conceptos y precios acordados; cancélala para liberar cantidades y genera otra.")
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        lines = validated_data.pop("line_inputs", [])
        order = PurchaseOrder.objects.create(**validated_data)
        self._replace_lines(order, lines)
        return order

    @transaction.atomic
    def update(self, instance, validated_data):
        instance = PurchaseOrder.objects.select_for_update().get(pk=instance.pk)
        if instance.status != PurchaseOrder.Status.DRAFT:
            raise serializers.ValidationError("Solo se pueden editar órdenes de compra en borrador.")
        lines = validated_data.pop("line_inputs", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if lines is not None:
            instance.lines.all().delete()
            self._replace_lines(instance, lines)
        return instance

    @staticmethod
    def _replace_lines(order, lines):
        for index, line in enumerate(lines, start=1):
            PurchaseOrderLine.objects.create(purchase_order=order, line_number=index, **line)


class PurchaseFrameworkLineSerializer(serializers.ModelSerializer):
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    committed_quantity = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseFrameworkAgreementLine
        fields = ["id", "line_number", "product", "product_sku", "product_name", "description", "unit_cost", "quantity_limit", "committed_quantity"]

    def get_committed_quantity(self, obj):
        return obj.purchase_order_lines.exclude(purchase_order__status=PurchaseOrder.Status.CANCELLED).aggregate(total=Sum("quantity"))["total"] or Decimal("0.000")


class PurchaseFrameworkLineInputSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True, kind=Product.Kind.STOCKABLE))
    description = serializers.CharField(max_length=300, required=False, allow_blank=True)
    unit_cost = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.00"))
    quantity_limit = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"), required=False, allow_null=True)


class PurchaseFrameworkAgreementSerializer(serializers.ModelSerializer):
    supplier = serializers.PrimaryKeyRelatedField(queryset=Supplier.objects.filter(is_active=True))
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    lines = PurchaseFrameworkLineSerializer(many=True, read_only=True)
    line_inputs = PurchaseFrameworkLineInputSerializer(many=True, write_only=True)

    class Meta:
        model = PurchaseFrameworkAgreement
        fields = ["id", "reference", "supplier", "supplier_name", "valid_from", "valid_until", "status", "notes", "lines", "line_inputs", "created_by", "activated_by", "activated_at", "closed_by", "closed_at", "created_at"]
        read_only_fields = ["id", "status", "created_by", "activated_by", "activated_at", "closed_by", "closed_at", "created_at"]

    def validate(self, attrs):
        if self.instance and self.instance.status != PurchaseFrameworkAgreement.Status.DRAFT:
            raise serializers.ValidationError("Solo puedes editar acuerdos marco en borrador.")
        start = attrs.get("valid_from", getattr(self.instance, "valid_from", None))
        end = attrs.get("valid_until", getattr(self.instance, "valid_until", None))
        if start and end and end < start:
            raise serializers.ValidationError({"valid_until": "La fecha final debe ser igual o posterior a la inicial."})
        lines = attrs.get("line_inputs")
        if lines is not None:
            products = [line["product"].pk for line in lines]
            if len(products) != len(set(products)):
                raise serializers.ValidationError({"line_inputs": "Cada producto debe aparecer una sola vez por acuerdo para que su límite de cantidad sea único."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        lines = validated_data.pop("line_inputs")
        agreement = PurchaseFrameworkAgreement.objects.create(**validated_data)
        self.replace_lines(agreement, lines)
        return agreement

    @transaction.atomic
    def update(self, instance, validated_data):
        instance = PurchaseFrameworkAgreement.objects.select_for_update().get(pk=instance.pk)
        if instance.status != PurchaseFrameworkAgreement.Status.DRAFT:
            raise serializers.ValidationError("Solo puedes editar acuerdos marco en borrador.")
        lines = validated_data.pop("line_inputs", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if lines is not None:
            instance.lines.all().delete()
            self.replace_lines(instance, lines)
        return instance

    @staticmethod
    def replace_lines(agreement, lines):
        for index, line in enumerate(lines, start=1):
            PurchaseFrameworkAgreementLine.objects.create(agreement=agreement, line_number=index, **line)


class PurchaseFrameworkOrderLineInputSerializer(serializers.Serializer):
    framework_line = serializers.PrimaryKeyRelatedField(queryset=PurchaseFrameworkAgreementLine.objects.select_related("agreement", "product"))
    expected_location = serializers.PrimaryKeyRelatedField(queryset=StockLocation.objects.filter(is_active=True))
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"))


class PurchaseFrameworkOrderInputSerializer(serializers.Serializer):
    expected_date = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    lines = PurchaseFrameworkOrderLineInputSerializer(many=True, allow_empty=False)


class PurchaseSourcingLineInputSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True, kind=Product.Kind.STOCKABLE))
    description = serializers.CharField(max_length=300, required=False, allow_blank=True)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"))


class PurchaseSourcingRequestInputSerializer(serializers.Serializer):
    desired_date = serializers.DateField(required=False, allow_null=True)
    target_location = serializers.PrimaryKeyRelatedField(queryset=StockLocation.objects.filter(is_active=True))
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)
    lines = PurchaseSourcingLineInputSerializer(many=True, allow_empty=False)

    def validate(self, attrs):
        if attrs.get("desired_date") and attrs["desired_date"] < timezone.localdate():
            raise serializers.ValidationError({"desired_date": "La fecha requerida no puede ser anterior a hoy."})
        product_ids = [line["product"].id for line in attrs["lines"]]
        if len(product_ids) != len(set(product_ids)):
            raise serializers.ValidationError({"lines": "Agrupa cada producto una sola vez; suma las cantidades requeridas."})
        return attrs


class PurchaseSourcingRFQSerializer(serializers.Serializer):
    supplier = serializers.PrimaryKeyRelatedField(queryset=Supplier.objects.filter(is_active=True))
    confirm_send = serializers.BooleanField(required=True)

    def validate_supplier(self, supplier):
        if not supplier.email.strip():
            raise serializers.ValidationError("El proveedor no tiene correo registrado.")
        return supplier


class PurchaseSourcingLineSerializer(serializers.ModelSerializer):
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_unit = serializers.CharField(source="product.unit", read_only=True)
    awarded_quantity = serializers.SerializerMethodField()
    remaining_quantity = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseSourcingLine
        fields = ["id", "line_number", "product", "product_sku", "product_name", "product_unit", "description", "quantity", "awarded_quantity", "remaining_quantity"]
        read_only_fields = fields

    def get_awarded_quantity(self, obj):
        return obj.awarded_order_lines.filter(purchase_order__status__in=["draft", "ordered", "partial", "received"]).aggregate(total=Sum("quantity"))["total"] or Decimal("0.000")

    def get_remaining_quantity(self, obj):
        return max(Decimal("0.000"), obj.quantity - self.get_awarded_quantity(obj))


class PurchaseSourcingEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()
    supplier_name = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseSourcingEvent
        fields = ["action", "detail", "supplier_name", "recipient_email", "actor_name", "occurred_at"]
        read_only_fields = fields

    def get_actor_name(self, obj):
        return obj.actor.get_full_name() or obj.actor.get_username()

    def get_supplier_name(self, obj):
        return obj.supplier.name if obj.supplier_id else ""


class PurchaseOfferLineSerializer(serializers.ModelSerializer):
    sourcing_line = serializers.UUIDField(source="sourcing_line_id", read_only=True)
    product_sku = serializers.CharField(source="sourcing_line.product.sku", read_only=True)
    product_name = serializers.CharField(source="sourcing_line.product.name", read_only=True)
    requested_quantity = serializers.DecimalField(source="sourcing_line.quantity", max_digits=14, decimal_places=3, read_only=True)
    quantity = serializers.DecimalField(source="quoted_quantity", max_digits=14, decimal_places=3, read_only=True)
    unit_cost = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    line_total = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    awarded_quantity = serializers.SerializerMethodField()
    available_quantity = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOfferLine
        fields = ["sourcing_line", "product_sku", "product_name", "requested_quantity", "quantity", "unit_cost", "line_total", "awarded_quantity", "available_quantity"]
        read_only_fields = fields

    def get_awarded_quantity(self, obj):
        return PurchaseOrderLine.objects.filter(
            purchase_order__sourcing_offer=obj.offer, sourcing_line_id=obj.sourcing_line_id,
            purchase_order__status__in=["draft", "ordered", "partial", "received"],
        ).aggregate(total=Sum("quantity"))["total"] or Decimal("0.000")

    def get_available_quantity(self, obj):
        return max(Decimal("0.000"), obj.quoted_quantity - self.get_awarded_quantity(obj))


class PurchaseOfferSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    lines = PurchaseOfferLineSerializer(many=True, read_only=True)
    total = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    received_by_name = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOffer
        fields = ["id", "request", "supplier", "supplier_name", "supplier_reference", "quote_date", "valid_until", "expected_date", "currency", "notes", "state", "received_by_name", "created_at", "lines", "total"]
        read_only_fields = fields

    def get_received_by_name(self, obj):
        return obj.received_by.get_full_name() or obj.received_by.get_username()


class PurchaseOfferLineInputSerializer(serializers.Serializer):
    sourcing_line = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"), required=False)
    unit_cost = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.00"))


class PurchaseOfferInputSerializer(serializers.Serializer):
    supplier = serializers.PrimaryKeyRelatedField(queryset=Supplier.objects.filter(is_active=True))
    supplier_reference = serializers.CharField(max_length=120, required=False, allow_blank=True)
    quote_date = serializers.DateField(required=False)
    valid_until = serializers.DateField(required=False, allow_null=True)
    expected_date = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)
    lines = PurchaseOfferLineInputSerializer(many=True, allow_empty=False)

    def validate(self, attrs):
        request = self.context["sourcing_request"]
        if request.state not in {PurchaseSourcingRequest.State.OPEN, PurchaseSourcingRequest.State.PARTIAL}:
            raise serializers.ValidationError("Solo se reciben ofertas para solicitudes abiertas o parcialmente adjudicadas.")
        line_ids = [line["sourcing_line"] for line in attrs["lines"]]
        expected = {str(pk) for pk in request.lines.values_list("id", flat=True)}
        if len(line_ids) != len(set(line_ids)) or not {str(pk) for pk in line_ids}.issubset(expected):
            raise serializers.ValidationError({"lines": "Cada renglón cotizado debe corresponder a un producto solicitado, sin duplicados."})
        if not line_ids:
            raise serializers.ValidationError({"lines": "Incluye al menos un producto cotizado."})
        request_lines = {str(line.id): line for line in request.lines.all()}
        for line in attrs["lines"]:
            if line.get("quantity", request_lines[str(line["sourcing_line"])].quantity) > request_lines[str(line["sourcing_line"])].quantity:
                raise serializers.ValidationError({"lines": "La cantidad cotizada no puede superar la cantidad solicitada."})
        quote_date = attrs.get("quote_date", timezone.localdate())
        if attrs.get("valid_until") and attrs["valid_until"] < quote_date:
            raise serializers.ValidationError({"valid_until": "La oferta ya está vencida en la fecha de emisión."})
        if attrs.get("expected_date") and attrs["expected_date"] < quote_date:
            raise serializers.ValidationError({"expected_date": "La fecha prometida no puede preceder a la cotización."})
        return attrs


class PurchaseAwardAllocationSerializer(serializers.Serializer):
    offer = serializers.UUIDField()
    sourcing_line = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"))
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True)

    def validate(self, attrs):
        key = (attrs["offer"], attrs["sourcing_line"])
        if key in self.context.setdefault("seen", set()):
            raise serializers.ValidationError("No repitas la combinación de oferta y producto.")
        self.context["seen"].add(key)
        return attrs


class PurchaseSourcingRequestSerializer(serializers.ModelSerializer):
    target_location_code = serializers.CharField(source="target_location.code", read_only=True)
    target_location_name = serializers.CharField(source="target_location.name", read_only=True)
    requested_by_name = serializers.SerializerMethodField()
    selected_offer = PurchaseOfferSerializer(read_only=True)
    purchase_order_number = serializers.CharField(source="purchase_order.number", read_only=True, default="")
    purchase_orders = PurchaseOrderSerializer(many=True, read_only=True)
    lines = PurchaseSourcingLineSerializer(many=True, read_only=True)
    offers = PurchaseOfferSerializer(many=True, read_only=True)
    events = PurchaseSourcingEventSerializer(many=True, read_only=True)

    class Meta:
        model = PurchaseSourcingRequest
        fields = ["id", "number", "requested_date", "desired_date", "target_location", "target_location_code", "target_location_name", "state", "notes", "created_by", "requested_by_name", "created_at", "lines", "offers", "selected_offer", "purchase_order", "purchase_order_number", "purchase_orders", "events"]
        read_only_fields = fields

    def get_requested_by_name(self, obj):
        return obj.created_by.get_full_name() or obj.created_by.get_username()


class PurchaseReceiptLineInputSerializer(serializers.Serializer):
    purchase_order_line = serializers.PrimaryKeyRelatedField(queryset=PurchaseOrderLine.objects.all())
    location = serializers.PrimaryKeyRelatedField(queryset=StockLocation.objects.filter(is_active=True))
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"))
    serial_numbers = serializers.ListField(child=serializers.CharField(max_length=120, allow_blank=False), required=False, allow_empty=True, max_length=100)

    def validate_serial_numbers(self, value):
        value = [item.strip() for item in value]
        if len(value) != len(set(value)):
            raise serializers.ValidationError("No repitas números de serie.")
        return value


class PurchaseReceiptInputSerializer(serializers.Serializer):
    idempotency_key = serializers.UUIDField()
    note = serializers.CharField(max_length=240, required=False, allow_blank=True)
    lines = PurchaseReceiptLineInputSerializer(many=True, allow_empty=False)

    def validate(self, attrs):
        line_ids = [line["purchase_order_line"].id for line in attrs["lines"]]
        if len(line_ids) != len(set(line_ids)):
            raise serializers.ValidationError({"lines": "Incluye una sola línea por concepto de la orden."})
        order = self.context["purchase_order"]
        allowed_line_ids = set(order.lines.values_list("id", flat=True))
        if any(line_id not in allowed_line_ids for line_id in line_ids):
            raise serializers.ValidationError({"lines": "Todas las líneas deben pertenecer a esta orden de compra."})
        for line in attrs["lines"]:
            expected_location_id = line["purchase_order_line"].expected_location_id
            if expected_location_id and expected_location_id != line["location"].id:
                raise serializers.ValidationError({"lines": "Cada recepción debe llegar a la ubicación prevista de su renglón."})
        return attrs


class PurchaseReceiptSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="purchase_order.number", read_only=True)
    supplier_name = serializers.CharField(source="purchase_order.supplier.name", read_only=True)
    lines = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseReceipt
        fields = ["id", "purchase_order", "order_number", "supplier_name", "receipt_date", "note", "received_by", "lines"]
        read_only_fields = fields

    def get_lines(self, obj):
        return [{
            "purchase_order_line": str(line.purchase_order_line_id),
            "line_number": line.purchase_order_line.line_number,
            "product_sku": line.purchase_order_line.product.sku,
            "product_name": line.purchase_order_line.product.name,
            "location": line.stock_movement.location_id,
            "location_name": line.stock_movement.location.name,
            "quantity": str(line.quantity),
            "movement_id": str(line.stock_movement_id),
              "serial_numbers": list(line.stock_movement.serial_events.select_related("unit").order_by("unit__serial_number").values_list("unit__serial_number", flat=True)),
        } for line in obj.lines.select_related("purchase_order_line__product", "stock_movement__location")]


class SupplierBillLineInputSerializer(serializers.Serializer):
    purchase_order_line = serializers.PrimaryKeyRelatedField(queryset=PurchaseOrderLine.objects.all())
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"))
    unit_cost = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.00"))
    tax_amount = serializers.DecimalField(max_digits=16, decimal_places=2, min_value=Decimal("0.00"))


class SupplierBillInputSerializer(serializers.Serializer):
    invoice_number = serializers.CharField(max_length=80, trim_whitespace=True)
    invoice_date = serializers.DateField()
    due_date = serializers.DateField(required=False, allow_null=True)
    lines = SupplierBillLineInputSerializer(many=True, allow_empty=False)

    def validate(self, attrs):
        order = self.context["purchase_order"]
        line_ids = [line["purchase_order_line"].pk for line in attrs["lines"]]
        if len(line_ids) != len(set(line_ids)):
            raise serializers.ValidationError({"lines": "Incluye una sola vez cada concepto de la orden."})
        if set(line_ids) - set(order.lines.values_list("id", flat=True)):
            raise serializers.ValidationError({"lines": "Todos los conceptos deben pertenecer a esta orden."})
        return attrs


class SupplierBillLineSerializer(serializers.ModelSerializer):
    product_sku = serializers.CharField(source="purchase_order_line.product.sku", read_only=True)
    product_name = serializers.CharField(source="purchase_order_line.product.name", read_only=True)
    purchase_order_line_number = serializers.IntegerField(source="purchase_order_line.line_number", read_only=True)
    ordered_unit_cost = serializers.DecimalField(source="purchase_order_line.unit_cost", max_digits=14, decimal_places=2, read_only=True)
    unit_cost_variance = serializers.SerializerMethodField()

    class Meta:
        model = SupplierBillLine
        fields = ["id", "purchase_order_line", "purchase_order_line_number", "product_sku", "product_name", "quantity", "ordered_unit_cost", "unit_cost", "unit_cost_variance", "subtotal", "tax_amount"]

    def get_unit_cost_variance(self, obj):
        return obj.unit_cost - obj.purchase_order_line.unit_cost


class SupplierBillSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    purchase_order_number = serializers.CharField(source="purchase_order.number", read_only=True, allow_null=True)
    registered_by_name = serializers.SerializerMethodField()
    lines = SupplierBillLineSerializer(many=True, read_only=True)
    paid_amount = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    balance_due = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    payment_status = serializers.CharField(read_only=True)
    is_opening_balance = serializers.BooleanField(read_only=True)
    cfdi_uuid = serializers.SerializerMethodField()
    cfdi_xml_attached = serializers.SerializerMethodField()
    cfdi_xsd_validated_at = serializers.SerializerMethodField()
    cfdi_issuer_seal_verified = serializers.SerializerMethodField()
    cfdi_issuer_seal_verified_at = serializers.SerializerMethodField()

    class Meta:
        model = SupplierBill
        fields = ["id", "supplier", "supplier_name", "purchase_order", "purchase_order_number", "invoice_number", "invoice_date", "due_date", "subtotal", "tax_total", "total", "paid_amount", "balance_due", "payment_status", "is_opening_balance", "opening_balance_batch_id", "opening_source_system", "opening_cutoff_date", "opening_original_total", "opening_paid_before_cutoff", "cfdi_uuid", "cfdi_xml_attached", "cfdi_xsd_validated_at", "cfdi_issuer_seal_verified", "cfdi_issuer_seal_verified_at", "registered_at", "registered_by", "registered_by_name", "lines"]
        read_only_fields = fields

    def get_registered_by_name(self, obj):
        return obj.registered_by.get_full_name() or obj.registered_by.get_username()

    @staticmethod
    def _cfdi_record(obj):
        return getattr(obj, "cfdi_record", None)

    def get_cfdi_uuid(self, obj):
        record = self._cfdi_record(obj)
        return str(record.cfdi_uuid) if record else ""

    def get_cfdi_xml_attached(self, obj):
        return self._cfdi_record(obj) is not None

    def get_cfdi_xsd_validated_at(self, obj):
        record = self._cfdi_record(obj)
        return record.xsd_validated_at if record else None

    def get_cfdi_issuer_seal_verified(self, obj):
        record = self._cfdi_record(obj)
        return bool(record and record.issuer_seal_verified)

    def get_cfdi_issuer_seal_verified_at(self, obj):
        record = self._cfdi_record(obj)
        return record.issuer_seal_verified_at if record else None


class SupplierBillCFDIUploadSerializer(serializers.Serializer):
    xml_file = serializers.FileField(allow_empty_file=False)

    def validate_xml_file(self, value):
        if not value.name.lower().endswith(".xml"):
            raise serializers.ValidationError("Adjunta el CFDI con extensión .xml.")
        if value.size < 1 or value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("El XML debe pesar entre 1 byte y 5 MB.")
        return value


class SupplierPaymentApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupplierPaymentApplication
        fields = ["id", "bill", "amount"]
        read_only_fields = ["id"]

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("El importe aplicado debe ser mayor que cero.")
        return value


class SupplierPaymentSerializer(serializers.ModelSerializer):
    applications = SupplierPaymentApplicationSerializer(many=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    created_by_name = serializers.SerializerMethodField()
    posted_by_name = serializers.SerializerMethodField()
    reversed_by_name = serializers.SerializerMethodField()
    reversal_entry_number = serializers.SerializerMethodField()

    class Meta:
        model = SupplierPayment
        fields = ["id", "number", "supplier", "supplier_name", "amount", "currency", "method", "paid_at", "reference", "memo", "state", "applications", "created_by", "created_by_name", "created_at", "posted_by", "posted_by_name", "posted_at", "reversal_reason", "reversed_by", "reversed_by_name", "reversed_at", "reversal_entry", "reversal_entry_number"]
        read_only_fields = ["id", "number", "state", "created_by", "created_by_name", "created_at", "posted_by", "posted_by_name", "posted_at", "reversal_reason", "reversed_by", "reversed_by_name", "reversed_at", "reversal_entry", "reversal_entry_number"]

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("El importe pagado debe ser mayor que cero.")
        return value

    def validate_currency(self, value):
        if value != "MXN":
            raise serializers.ValidationError("La primera versión opera únicamente en MXN.")
        return value

    def validate_applications(self, applications):
        if not applications:
            raise serializers.ValidationError("Agrega al menos una factura de proveedor al pago.")
        bill_ids = [item["bill"].id for item in applications]
        if len(bill_ids) != len(set(bill_ids)):
            raise serializers.ValidationError("No repitas una factura; combina sus importes en una aplicación.")
        return applications

    def validate(self, attrs):
        supplier = attrs.get("supplier", getattr(self.instance, "supplier", None))
        applications = attrs.get("applications")
        if applications is not None and any(item["bill"].supplier_id != supplier.id for item in applications):
            raise serializers.ValidationError({"applications": "El pago y las facturas deben pertenecer al mismo proveedor."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        applications = validated_data.pop("applications")
        payment = SupplierPayment.objects.create(**validated_data)
        for application in applications:
            SupplierPaymentApplication.objects.create(payment=payment, **application)
        return payment

    @transaction.atomic
    def update(self, instance, validated_data):
        instance = SupplierPayment.objects.select_for_update().get(pk=instance.pk)
        if instance.state != SupplierPayment.State.DRAFT:
            raise serializers.ValidationError("Solo se edita un pago en borrador.")
        applications = validated_data.pop("applications", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if applications is not None:
            instance.applications.all().delete()
            for application in applications:
                SupplierPaymentApplication.objects.create(payment=instance, **application)
        return instance

    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() or obj.created_by.get_username()

    def get_posted_by_name(self, obj):
        return (obj.posted_by.get_full_name() or obj.posted_by.get_username()) if obj.posted_by else ""

    def get_reversed_by_name(self, obj):
        return (obj.reversed_by.get_full_name() or obj.reversed_by.get_username()) if obj.reversed_by else ""

    def get_reversal_entry_number(self, obj):
        return obj.reversal_entry.number if obj.reversal_entry_id else ""


class SupplierPaymentReverseSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, min_length=10, trim_whitespace=True)
    confirm_irreversible = serializers.BooleanField()

    def validate_confirm_irreversible(self, value):
        if not value:
            raise serializers.ValidationError("Confirma expresamente la reversa del pago.")
        return value
