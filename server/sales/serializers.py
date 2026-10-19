from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from django.db import transaction
from django.db.models import Sum
from django.contrib.auth import get_user_model
from inventory.models import Product, StockLocation

from .models import Customer, CustomerContact, CustomerSite, Opportunity, OpportunityActivity, Quote, QuoteCostItem, QuoteCostSheet, QuoteLine, QuoteTemplate, WorkLog, WorkOrder, WorkOrderChecklistItem, WorkOrderChecklistTemplate, WorkOrderCustomerAcceptance, WorkOrderEvidence, WorkOrderMaterialRequirement, inspect_work_order_evidence


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ["id", "name", "legal_name", "rfc", "email", "phone", "fiscal_regime", "fiscal_postal_code", "payment_term_days", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class CustomerContactSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)

    class Meta:
        model = CustomerContact
        fields = ["id", "customer", "customer_name", "name", "role", "email", "phone", "is_primary", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "customer_name", "created_at", "updated_at"]

    def validate_customer(self, customer):
        if not customer.is_active:
            raise serializers.ValidationError("No se pueden agregar contactos a un cliente inactivo.")
        if self.instance and customer.pk != self.instance.customer_id:
            raise serializers.ValidationError("Un contacto existente no se puede cambiar de cliente.")
        return customer

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Indica el nombre del contacto.")
        return value


class CustomerSiteSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)

    class Meta:
        model = CustomerSite
        fields = ["id", "customer", "customer_name", "name", "address", "contact_name", "phone", "email", "notes", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "customer_name", "created_at", "updated_at"]

    def validate_customer(self, customer):
        if not customer.is_active:
            raise serializers.ValidationError("No se pueden agregar sitios a un cliente inactivo.")
        if self.instance and customer.pk != self.instance.customer_id:
            raise serializers.ValidationError("Un sitio existente no se puede cambiar de cliente.")
        return customer

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Indica un nombre para el sitio del cliente.")
        return value

    def validate_address(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Indica el domicilio del sitio.")
        return value


class OpportunitySerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True, default="")
    assigned_to_name = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Opportunity
        fields = ["id", "name", "customer", "customer_name", "company_name", "contact_name", "email", "phone", "stage", "expected_revenue", "probability", "expected_close_date", "source", "utm_source", "utm_medium", "utm_campaign", "description", "assigned_to", "assigned_to_name", "lost_reason", "closing_note", "is_active", "created_by", "created_by_name", "created_at", "updated_at"]
        read_only_fields = ["id", "stage", "is_active", "created_by", "created_at", "updated_at"]

    assigned_to = serializers.PrimaryKeyRelatedField(queryset=get_user_model().objects.filter(is_active=True), required=False, allow_null=True)

    def get_assigned_to_name(self, obj):
        if not obj.assigned_to_id:
            return ""
        return obj.assigned_to.get_full_name() or obj.assigned_to.get_username()

    def get_created_by_name(self, obj):
        if not obj.created_by_id:
            return "Solicitud pública"
        return obj.created_by.get_full_name() or obj.created_by.get_username()

    def validate(self, attrs):
        customer = attrs.get("customer", getattr(self.instance, "customer", None))
        company_name = attrs.get("company_name", getattr(self.instance, "company_name", ""))
        expected_revenue = attrs.get("expected_revenue", getattr(self.instance, "expected_revenue", Decimal("0.00")))
        probability = attrs.get("probability", getattr(self.instance, "probability", 10))
        if not customer and not company_name.strip() and not attrs.get("contact_name", getattr(self.instance, "contact_name", "")).strip():
            raise serializers.ValidationError("Agrega una empresa, un contacto o relaciona un cliente existente.")
        if customer and company_name.strip() and company_name.strip().casefold() != customer.name.strip().casefold():
            raise serializers.ValidationError({"company_name": "El nombre de empresa debe coincidir con el cliente relacionado."})
        if expected_revenue < 0:
            raise serializers.ValidationError({"expected_revenue": "El ingreso estimado no puede ser negativo."})
        if not 0 <= probability <= 100:
            raise serializers.ValidationError({"probability": "La probabilidad debe estar entre 0 y 100."})
        return attrs


class OpportunityNewCustomerSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200, trim_whitespace=True)
    legal_name = serializers.CharField(max_length=250, required=False, allow_blank=True, trim_whitespace=True)
    rfc = serializers.CharField(max_length=13, required=False, allow_blank=True, trim_whitespace=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True, trim_whitespace=True)
    fiscal_regime = serializers.CharField(max_length=3, required=False, allow_blank=True, trim_whitespace=True)
    fiscal_postal_code = serializers.CharField(max_length=5, required=False, allow_blank=True, trim_whitespace=True)


class OpportunityConvertSerializer(serializers.Serializer):
    customer_id = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.filter(is_active=True), required=False)
    new_customer = OpportunityNewCustomerSerializer(required=False)

    def validate(self, attrs):
        if attrs.get("customer_id") and attrs.get("new_customer"):
            raise serializers.ValidationError("Selecciona un cliente existente o captura los datos para crear uno, no ambos.")
        return attrs


class OpportunityActivitySerializer(serializers.ModelSerializer):
    opportunity_name = serializers.CharField(source="opportunity.name", read_only=True)
    assigned_to_name = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    completed_by_name = serializers.SerializerMethodField()

    opportunity = serializers.PrimaryKeyRelatedField(queryset=Opportunity.objects.all())
    assigned_to = serializers.PrimaryKeyRelatedField(queryset=get_user_model().objects.filter(is_active=True), required=False, allow_null=True)

    class Meta:
        model = OpportunityActivity
        fields = ["id", "opportunity", "opportunity_name", "activity_type", "title", "due_at", "status", "note", "assigned_to", "assigned_to_name", "created_by", "created_by_name", "completed_by", "completed_by_name", "completed_at", "created_at"]
        read_only_fields = ["id", "status", "created_by", "created_by_name", "completed_by", "completed_by_name", "completed_at", "created_at"]

    def get_assigned_to_name(self, obj):
        if not obj.assigned_to_id:
            return ""
        return obj.assigned_to.get_full_name() or obj.assigned_to.get_username()

    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() or obj.created_by.get_username()

    def get_completed_by_name(self, obj):
        if not obj.completed_by_id:
            return ""
        return obj.completed_by.get_full_name() or obj.completed_by.get_username()

    def validate(self, attrs):
        opportunity = attrs.get("opportunity", getattr(self.instance, "opportunity", None))
        if self.instance and self.instance.status != OpportunityActivity.Status.PLANNED:
            raise serializers.ValidationError("Solo se pueden editar actividades pendientes.")
        if opportunity and opportunity.stage in {Opportunity.Stage.WON, Opportunity.Stage.LOST}:
            raise serializers.ValidationError({"opportunity": "No se pueden programar actividades en una oportunidad cerrada."})
        return attrs


class QuoteLineSerializer(serializers.ModelSerializer):
    catalog_product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True), allow_null=True, required=False)
    catalog_product_sku = serializers.CharField(source="catalog_product.sku", read_only=True, default="")
    catalog_product_name = serializers.CharField(source="catalog_product.name", read_only=True, default="")
    discount_amount = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    line_subtotal = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    tax_amount = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    approved_quantity = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True, allow_null=True)

    class Meta:
        model = QuoteLine
        fields = ["id", "kind", "catalog_product", "catalog_product_sku", "catalog_product_name", "description", "quantity", "unit_price", "discount_percent", "discount_amount", "tax_rate", "is_optional", "approved_quantity", "line_subtotal", "tax_amount"]
        read_only_fields = ["id", "approved_quantity", "discount_amount", "line_subtotal", "tax_amount"]

    def validate(self, attrs):
        quantity = attrs.get("quantity", getattr(self.instance, "quantity", None))
        unit_price = attrs.get("unit_price", getattr(self.instance, "unit_price", None))
        tax_rate = attrs.get("tax_rate", getattr(self.instance, "tax_rate", None))
        discount_percent = attrs.get("discount_percent", getattr(self.instance, "discount_percent", Decimal("0.00")))
        kind = attrs.get("kind", getattr(self.instance, "kind", None))
        product = attrs.get("catalog_product", getattr(self.instance, "catalog_product", None))
        if quantity is not None and quantity <= 0:
            raise serializers.ValidationError({"quantity": "La cantidad debe ser mayor que cero."})
        if unit_price is not None and unit_price < 0:
            raise serializers.ValidationError({"unit_price": "El precio no puede ser negativo."})
        if not Decimal("0") <= discount_percent <= Decimal("100"):
            raise serializers.ValidationError({"discount_percent": "El descuento debe estar entre 0 y 100 por ciento."})
        if tax_rate is not None and not 0 <= tax_rate <= 100:
            raise serializers.ValidationError({"tax_rate": "La tasa debe estar entre 0 y 100."})
        if product is not None:
            expected_kind = Product.Kind.STOCKABLE if kind in {QuoteLine.Kind.EQUIPMENT, QuoteLine.Kind.MATERIAL} else Product.Kind.SERVICE
            if product.kind != expected_kind:
                raise serializers.ValidationError({"catalog_product": "Elige un producto de inventario para equipo/material o un servicio para instalación/soporte."})
        return attrs


class QuoteCostItemSerializer(serializers.ModelSerializer):
    line_total = serializers.DecimalField(max_digits=30, decimal_places=2, read_only=True)

    class Meta:
        model = QuoteCostItem
        fields = ["id", "category", "description", "quantity", "unit_cost", "is_optional", "sort_order", "line_total"]
        read_only_fields = ["id", "line_total"]

    def validate_description(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Describe el costo interno.")
        return value


class QuoteCostSheetSerializer(serializers.ModelSerializer):
    items = QuoteCostItemSerializer(many=True, required=False)
    quote_number = serializers.CharField(source="quote.number", read_only=True)
    quote_status = serializers.CharField(source="quote.status", read_only=True)
    quote_subtotal = serializers.SerializerMethodField()
    quote_optional_subtotal = serializers.SerializerMethodField()
    base_cost_total = serializers.SerializerMethodField()
    optional_cost_total = serializers.SerializerMethodField()
    total_cost = serializers.SerializerMethodField()
    estimated_gross_profit = serializers.SerializerMethodField()
    estimated_margin_percent = serializers.SerializerMethodField()
    estimated_optional_gross_profit = serializers.SerializerMethodField()
    estimated_optional_margin_percent = serializers.SerializerMethodField()
    target_selling_subtotal = serializers.SerializerMethodField()
    optional_target_selling_subtotal = serializers.SerializerMethodField()

    class Meta:
        model = QuoteCostSheet
        fields = ["id", "quote_number", "quote_status", "target_margin_percent", "items", "quote_subtotal", "quote_optional_subtotal", "base_cost_total", "optional_cost_total", "total_cost", "estimated_gross_profit", "estimated_margin_percent", "estimated_optional_gross_profit", "estimated_optional_margin_percent", "target_selling_subtotal", "optional_target_selling_subtotal", "created_at", "updated_at"]
        read_only_fields = ["id", "quote_number", "quote_status", "created_at", "updated_at"]

    def validate_items(self, value):
        if len(value) > 500:
            raise serializers.ValidationError("Una hoja puede contener hasta 500 renglones de costo.")
        return value

    def _totals(self, obj):
        items = list(obj.items.all())
        base_cost = sum((item.line_total for item in items if not item.is_optional), Decimal("0.00"))
        optional_cost = sum((item.line_total for item in items if item.is_optional), Decimal("0.00"))
        quote = obj.quote
        return quote, base_cost, optional_cost

    def get_quote_subtotal(self, obj):
        return obj.quote.subtotal

    def get_quote_optional_subtotal(self, obj):
        return obj.quote.optional_subtotal

    def get_base_cost_total(self, obj):
        return self._totals(obj)[1]

    def get_optional_cost_total(self, obj):
        return self._totals(obj)[2]

    def get_total_cost(self, obj):
        _, base_cost, optional_cost = self._totals(obj)
        return base_cost + optional_cost

    def get_estimated_gross_profit(self, obj):
        quote, base_cost, _ = self._totals(obj)
        return quote.subtotal - base_cost

    def get_estimated_margin_percent(self, obj):
        quote, base_cost, _ = self._totals(obj)
        if quote.subtotal <= 0:
            return None
        return ((quote.subtotal - base_cost) * Decimal("100") / quote.subtotal).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def get_estimated_optional_gross_profit(self, obj):
        quote, _, optional_cost = self._totals(obj)
        return quote.optional_subtotal - optional_cost

    def get_estimated_optional_margin_percent(self, obj):
        quote, _, optional_cost = self._totals(obj)
        if quote.optional_subtotal <= 0:
            return None
        return ((quote.optional_subtotal - optional_cost) * Decimal("100") / quote.optional_subtotal).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def _target_price(self, obj, optional=False):
        margin = obj.target_margin_percent
        if margin is None:
            return None
        _, base_cost, optional_cost = self._totals(obj)
        amount = optional_cost if optional else base_cost
        divisor = Decimal("1") - margin / Decimal("100")
        return (amount / divisor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def get_target_selling_subtotal(self, obj):
        return self._target_price(obj)

    def get_optional_target_selling_subtotal(self, obj):
        return self._target_price(obj, optional=True)

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items", [])
        sheet = QuoteCostSheet.objects.create(**validated_data)
        QuoteCostItem.objects.bulk_create([QuoteCostItem(cost_sheet=sheet, **item) for item in items])
        return sheet

    @transaction.atomic
    def update(self, instance, validated_data):
        items = validated_data.pop("items", None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.save()
        if items is not None:
            instance.items.all().delete()
            QuoteCostItem.objects.bulk_create([QuoteCostItem(cost_sheet=instance, **item) for item in items])
        return instance


class QuoteTemplateLineInputSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=QuoteLine.Kind.choices)
    catalog_product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True), required=False, allow_null=True)
    description = serializers.CharField(max_length=300, trim_whitespace=True)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0.001"))
    unit_price = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.00"))
    discount_percent = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal("0.00"), max_value=Decimal("100.00"), required=False, default=Decimal("0.00"))
    tax_rate = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal("0.00"), max_value=Decimal("100.00"), required=False)
    is_optional = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        product = attrs.get("catalog_product")
        if product:
            stock_line = attrs["kind"] in {QuoteLine.Kind.EQUIPMENT, QuoteLine.Kind.MATERIAL}
            expected_kind = Product.Kind.STOCKABLE if stock_line else Product.Kind.SERVICE
            if product.kind != expected_kind:
                raise serializers.ValidationError({"catalog_product": "El tipo de producto no corresponde al concepto de la plantilla."})
        return attrs


class QuoteTemplateSerializer(serializers.ModelSerializer):
    lines = serializers.JSONField()
    created_by = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = QuoteTemplate
        fields = ["id", "name", "title", "validity_days", "notes", "tax_rate", "lines", "is_active", "created_by", "created_at", "updated_at"]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Indica el nombre de la plantilla.")
        return value

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Indica el título comercial que recibirá la cotización.")
        return value

    def validate_validity_days(self, value):
        if value > 3650:
            raise serializers.ValidationError("La vigencia no puede exceder diez años; usa 0 para no asignar fecha límite automática.")
        return value

    def validate_tax_rate(self, value):
        if not Decimal("0") <= value <= Decimal("100"):
            raise serializers.ValidationError("La tasa debe estar entre 0 y 100.")
        return value

    def validate_lines(self, value):
        if not isinstance(value, list) or not 1 <= len(value) <= 50:
            raise serializers.ValidationError("La plantilla debe contener entre 1 y 50 conceptos.")
        validator = QuoteTemplateLineInputSerializer(data=value, many=True)
        validator.is_valid(raise_exception=True)
        normalized = []
        for line in validator.validated_data:
            product = line.pop("catalog_product", None)
            normalized.append({
                "kind": line["kind"],
                "catalog_product": str(product.pk) if product else None,
                "description": line["description"],
                "quantity": str(line["quantity"]),
                "unit_price": str(line["unit_price"]),
                "discount_percent": str(line.get("discount_percent", Decimal("0.00"))),
                "is_optional": line["is_optional"],
                **({"tax_rate": str(line["tax_rate"])} if "tax_rate" in line else {}),
            })
        return normalized

    def to_representation(self, instance):
        data = super().to_representation(instance)
        product_ids = [line.get("catalog_product") for line in data["lines"] if line.get("catalog_product")]
        products = {str(product.pk): product for product in Product.objects.filter(pk__in=product_ids)}
        for line in data["lines"]:
            product = products.get(line.get("catalog_product"))
            line["catalog_product_sku"] = product.sku if product else ""
            line["catalog_product_name"] = product.name if product else ""
        return data


class QuoteSerializer(serializers.ModelSerializer):
    lines = QuoteLineSerializer(many=True, required=False)
    template = serializers.PrimaryKeyRelatedField(queryset=QuoteTemplate.objects.filter(is_active=True), write_only=True, required=False)
    customer_contact = serializers.PrimaryKeyRelatedField(queryset=CustomerContact.objects.all(), required=False, allow_null=True)
    title = serializers.CharField(max_length=240, required=False)
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    customer_contact_name = serializers.CharField(source="customer_contact.name", read_only=True, default="")
    opportunity_name = serializers.CharField(source="opportunity.name", read_only=True, default="")
    revision_of_number = serializers.SerializerMethodField()
    subtotal = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    tax_total = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    total = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    optional_subtotal = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    optional_tax_total = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    optional_total = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    created_by = serializers.StringRelatedField(read_only=True)
    discount_approval_required = serializers.SerializerMethodField()
    discount_approved = serializers.SerializerMethodField()
    discount_maximum_percent = serializers.SerializerMethodField()
    discount_limit_percent = serializers.SerializerMethodField()

    class Meta:
        model = Quote
        fields = ["id", "number", "customer", "customer_name", "customer_contact", "customer_contact_name", "recipient_name_snapshot", "recipient_email_snapshot", "opportunity", "opportunity_name", "customer_site", "service_site_name", "service_address", "service_contact_name", "service_contact_phone", "service_contact_email", "title", "status", "issue_date", "valid_until", "payment_term_days", "notes", "revision_of", "revision_of_number", "revision_number", "template", "lines", "subtotal", "tax_total", "total", "optional_subtotal", "optional_tax_total", "optional_total", "discount_approval_required", "discount_approved", "discount_maximum_percent", "discount_limit_percent", "created_by", "created_at", "updated_at"]
        read_only_fields = ["id", "number", "recipient_name_snapshot", "recipient_email_snapshot", "status", "revision_of", "revision_number", "created_by", "created_at", "updated_at"]

    def get_revision_of_number(self, obj):
        return obj.revision_of.number if obj.revision_of_id else ""

    def _get_discount_review(self, obj):
        cache = getattr(self, "_discount_review_cache", None)
        if cache is None:
            cache = self._discount_review_cache = {}
        if obj.pk not in cache:
            from .services import quote_discount_review
            cache[obj.pk] = quote_discount_review(obj)
        return cache[obj.pk]

    def get_discount_approval_required(self, obj):
        return self._get_discount_review(obj)["required"]

    def get_discount_approved(self, obj):
        review = self._get_discount_review(obj)
        return review["approved"] if review["required"] else False

    def get_discount_maximum_percent(self, obj):
        return str(self._get_discount_review(obj)["maximum_discount_percent"])

    def get_discount_limit_percent(self, obj):
        return str(self._get_discount_review(obj)["threshold_percent"])

    @transaction.atomic
    def create(self, validated_data):
        template = validated_data.pop("template", None)
        lines = validated_data.pop("lines", None)
        if template:
            if not lines:
                lines = []
                for item in template.lines:
                    product_id = item.get("catalog_product")
                    product = Product.objects.filter(pk=product_id, is_active=True).first() if product_id else None
                    if product_id and product is None:
                        raise serializers.ValidationError({"template": "Un producto de la plantilla ya no está activo; actualízala antes de usarla."})
                    lines.append({
                        "kind": item["kind"], "catalog_product": product,
                        "description": item["description"], "quantity": Decimal(item["quantity"]),
                        "unit_price": Decimal(item["unit_price"]), "tax_rate": Decimal(item.get("tax_rate", template.tax_rate)),
                        "discount_percent": Decimal(item.get("discount_percent", "0.00")),
                        "is_optional": item.get("is_optional", False),
                    })
            if not validated_data.get("title"):
                validated_data["title"] = template.title
            issue_date = validated_data.get("issue_date")
            if not validated_data.get("valid_until") and template.validity_days and issue_date:
                validated_data["valid_until"] = issue_date + timedelta(days=template.validity_days)
            if not validated_data.get("notes") and template.notes:
                validated_data["notes"] = template.notes
        if not validated_data.get("title"):
            raise serializers.ValidationError({"title": "Indica el proyecto o servicio de la cotización."})
        if "payment_term_days" not in validated_data:
            validated_data["payment_term_days"] = validated_data["customer"].payment_term_days
        if not lines:
            raise serializers.ValidationError({"lines": "Agrega conceptos directamente o elige una plantilla con conceptos."})
        opportunity = validated_data.get("opportunity")
        if opportunity and (not opportunity.customer_id or opportunity.customer_id != validated_data["customer"].id):
            raise serializers.ValidationError({"opportunity": "Relaciona un cliente igual al de la oportunidad antes de crear la cotización."})
        if opportunity and opportunity.stage in {Opportunity.Stage.WON, Opportunity.Stage.LOST}:
            raise serializers.ValidationError({"opportunity": "No se pueden agregar cotizaciones a una oportunidad cerrada."})
        quote = Quote.objects.create(**validated_data)
        for line in lines:
            QuoteLine.objects.create(quote=quote, **line)
        return quote

    def validate(self, attrs):
        customer = attrs.get("customer", getattr(self.instance, "customer", None))
        customer_changed = bool(self.instance and customer and customer.pk != self.instance.customer_id)
        contact = attrs.get("customer_contact", getattr(self.instance, "customer_contact", None))
        contact_changed = "customer_contact" in attrs
        if contact and contact.customer_id != customer.pk:
            raise serializers.ValidationError({"customer_contact": "El contacto debe pertenecer al cliente de la cotización."})
        if contact and (not self.instance or contact_changed) and not contact.is_active:
            raise serializers.ValidationError({"customer_contact": "Elige un contacto activo para una cotización nueva o editada."})
        if contact and not contact.email.strip():
            raise serializers.ValidationError({"customer_contact": "El contacto necesita un correo para ser destinatario de la cotización."})
        if not self.instance or contact_changed or customer_changed:
            if customer_changed and not contact_changed:
                attrs["customer_contact"] = None
                contact = None
            attrs["recipient_name_snapshot"] = contact.name if contact else customer.name
            attrs["recipient_email_snapshot"] = contact.email if contact else customer.email
        site = attrs.get("customer_site", getattr(self.instance, "customer_site", None))
        if self.instance and customer and customer.pk != self.instance.customer_id and "payment_term_days" not in attrs:
            attrs["payment_term_days"] = customer.payment_term_days
        if site and site.customer_id != customer.pk:
            raise serializers.ValidationError({"customer_site": "El sitio debe pertenecer al cliente de la cotización."})
        if site and not site.is_active and site.pk != getattr(self.instance, "customer_site_id", None):
            raise serializers.ValidationError({"customer_site": "El sitio está inactivo y no se puede asignar a otra cotización."})
        if site and "customer_site" in attrs:
            attrs.update(
                service_site_name=site.name,
                service_address=site.address,
                service_contact_name=site.contact_name,
                service_contact_phone=site.phone,
                service_contact_email=site.email,
            )
        elif "customer_site" in attrs and site is None:
            attrs.update(service_site_name="", service_address="", service_contact_name="", service_contact_phone="", service_contact_email="")
        return attrs

    @transaction.atomic
    def update(self, instance, validated_data):
        instance = Quote.objects.select_for_update().get(pk=instance.pk)
        if instance.status != Quote.Status.DRAFT:
            raise serializers.ValidationError("Solo se pueden editar cotizaciones en borrador.")
        if validated_data.pop("template", None):
            raise serializers.ValidationError({"template": "Selecciona la plantilla al crear la cotización; las existentes conservan sus conceptos como snapshot."})
        lines = validated_data.pop("lines", None)
        opportunity = validated_data.get("opportunity", instance.opportunity)
        customer = validated_data.get("customer", instance.customer)
        if opportunity and (not opportunity.customer_id or opportunity.customer_id != customer.id):
            raise serializers.ValidationError({"opportunity": "Relaciona un cliente igual al de la oportunidad antes de editar la cotización."})
        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.save()
        if lines is not None:
            instance.lines.all().delete()
            for line in lines:
                QuoteLine.objects.create(quote=instance, **line)
        return instance


class WorkOrderMaterialRequirementSerializer(serializers.ModelSerializer):
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_unit = serializers.CharField(source="product.unit", read_only=True)
    source_description = serializers.CharField(source="source_quote_line.description", read_only=True)
    supply_location_code = serializers.CharField(source="supply_location.code", read_only=True)
    supply_location_name = serializers.CharField(source="supply_location.name", read_only=True)

    class Meta:
        model = WorkOrderMaterialRequirement
        fields = ["id", "source_quote_line", "source_description", "product", "product_sku", "product_name", "product_unit", "required_quantity", "supply_location", "supply_location_code", "supply_location_name", "created_at"]
        read_only_fields = fields


class WorkOrderMaterialLocationSerializer(serializers.Serializer):
    supply_location = serializers.PrimaryKeyRelatedField(queryset=StockLocation.objects.filter(is_active=True))


class WorkOrderSerializer(serializers.ModelSerializer):
    sales_order_number = serializers.CharField(source="sales_order.quote.number", read_only=True)
    customer_id = serializers.UUIDField(source="sales_order.quote.customer_id", read_only=True)
    customer_name = serializers.CharField(source="sales_order.quote.customer.name", read_only=True)
    customer_site_name = serializers.CharField(source="service_site_name", read_only=True)
    assigned_to_name = serializers.SerializerMethodField()
    time_logs = serializers.SerializerMethodField()
    total_logged_hours = serializers.SerializerMethodField()
    checklist_items = serializers.SerializerMethodField()
    customer_acceptance = serializers.SerializerMethodField()
    invoiceable_lines = serializers.SerializerMethodField()
    approved_total = serializers.SerializerMethodField()
    material_requirements = WorkOrderMaterialRequirementSerializer(many=True, read_only=True)

    class Meta:
        model = WorkOrder
        fields = ["id", "sales_order", "sales_order_number", "customer_id", "customer_name", "customer_site", "customer_site_name", "title", "status", "scheduled_start", "scheduled_end", "service_site_name", "service_address", "service_contact_name", "service_contact_phone", "service_contact_email", "assigned_to", "assigned_to_name", "completion_notes", "time_logs", "total_logged_hours", "checklist_items", "customer_acceptance", "invoiceable_lines", "approved_total", "material_requirements", "created_at"]
        read_only_fields = ["id", "sales_order", "created_at"]

    def get_assigned_to_name(self, obj):
        if not obj.assigned_to_id:
            return ""
        return obj.assigned_to.get_full_name() or obj.assigned_to.get_username()

    def get_time_logs(self, obj):
        logs = list(obj.time_logs.all())[:20]
        return WorkLogSerializer(logs, many=True).data

    def get_total_logged_hours(self, obj):
        return sum((log.hours for log in obj.time_logs.all()), Decimal("0.00"))

    def get_checklist_items(self, obj):
        return WorkOrderChecklistItemSerializer(obj.checklist_items.all(), many=True).data

    def get_customer_acceptance(self, obj):
        try:
            acceptance = obj.customer_acceptance
        except WorkOrderCustomerAcceptance.DoesNotExist:
            return None
        return WorkOrderCustomerAcceptanceSerializer(acceptance).data

    def get_approved_total(self, obj):
        total = Decimal("0.00")
        for line in obj.sales_order.quote.lines.all():
            quantity = line.billable_quantity
            if quantity <= 0:
                continue
            gross = (quantity * line.unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            discount = (gross * line.discount_percent / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            subtotal = gross - discount
            tax = (subtotal * line.tax_rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            total += subtotal + tax
        return str(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    def get_invoiceable_lines(self, obj):
        from billing.models import InvoiceLine

        billed = dict(InvoiceLine.objects.filter(invoice__sales_order_id=obj.sales_order_id, quote_line__isnull=False)
            .values("quote_line_id").annotate(quantity=Sum("quantity")).values_list("quote_line_id", "quantity"))
        result = []
        for line in obj.sales_order.quote.lines.all().order_by("id"):
            accepted_quantity = line.billable_quantity
            if accepted_quantity <= 0:
                continue
            invoiced = billed.get(line.id, Decimal("0.000"))
            remaining = accepted_quantity - invoiced
            if remaining <= 0:
                continue
            result.append({
                "quote_line": str(line.id),
                "kind": line.kind,
                "description": line.description,
                "quoted_quantity": str(accepted_quantity),
                "proposed_quantity": str(line.quantity),
                "invoiced_quantity": str(invoiced),
                "remaining_quantity": str(remaining),
                "unit_price": str(line.unit_price),
                "discount_percent": str(line.discount_percent),
                "tax_rate": str(line.tax_rate),
            })
        return result


class WorkOrderCustomerAcceptanceSerializer(serializers.ModelSerializer):
    captured_by_name = serializers.SerializerMethodField()

    class Meta:
        model = WorkOrderCustomerAcceptance
        fields = ["customer_contact_name", "customer_contact_email", "notes", "accepted_at", "captured_by_name"]
        read_only_fields = fields

    def get_captured_by_name(self, obj):
        return obj.captured_by.get_full_name() or obj.captured_by.get_username()


class WorkOrderCustomerAcceptanceInputSerializer(serializers.Serializer):
    customer_contact_name = serializers.CharField(max_length=160, trim_whitespace=True)
    customer_contact_email = serializers.EmailField(required=False, allow_blank=True)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True, trim_whitespace=True)
    customer_confirmed = serializers.BooleanField(write_only=True)

    def validate(self, attrs):
        if not attrs["customer_contact_name"].strip():
            raise serializers.ValidationError({"customer_contact_name": "Escribe el nombre de quien confirmó."})
        if not attrs["customer_confirmed"]:
            raise serializers.ValidationError({"customer_confirmed": "Confirma que el cliente manifestó su conformidad."})
        return attrs


class WorkOrderInvoiceLineInputSerializer(serializers.Serializer):
    quote_line = serializers.PrimaryKeyRelatedField(queryset=QuoteLine.objects.all())
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0.001"))


class WorkOrderInvoiceCreateSerializer(serializers.Serializer):
    lines = WorkOrderInvoiceLineInputSerializer(many=True, required=False, default=list, max_length=200)

    def validate_lines(self, lines):
        quote_line_ids = [line["quote_line"].pk for line in lines]
        if len(quote_line_ids) != len(set(quote_line_ids)):
            raise serializers.ValidationError("Cada concepto de cotización debe aparecer una sola vez.")
        return lines


class WorkOrderChecklistItemSerializer(serializers.ModelSerializer):
    completed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = WorkOrderChecklistItem
        fields = ["id", "label", "is_completed", "completed_at", "completed_by_name", "created_at"]
        read_only_fields = fields

    def get_completed_by_name(self, obj):
        if not obj.completed_by_id:
            return ""
        return obj.completed_by.get_full_name() or obj.completed_by.get_username()


class WorkOrderChecklistItemCreateSerializer(serializers.Serializer):
    label = serializers.CharField(max_length=240, allow_blank=False, trim_whitespace=True)


class WorkOrderChecklistItemUpdateSerializer(serializers.Serializer):
    is_completed = serializers.BooleanField()


class WorkOrderChecklistTemplateSerializer(serializers.ModelSerializer):
    items = serializers.ListField(
        child=serializers.CharField(max_length=240, allow_blank=False, trim_whitespace=True),
        required=False, allow_empty=False, max_length=50,
    )
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = WorkOrderChecklistTemplate
        fields = ["id", "name", "items", "is_active", "created_by", "created_by_name", "created_at", "updated_at"]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Indica un nombre para la plantilla.")
        return value

    def validate_items(self, items):
        items = [item.strip() for item in items]
        if len({item.casefold() for item in items}) != len(items):
            raise serializers.ValidationError("La plantilla no puede repetir puntos.")
        return items

    def validate(self, attrs):
        if not self.instance and not attrs.get("items"):
            raise serializers.ValidationError({"items": "Agrega al menos un punto a la plantilla."})
        return attrs

    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() or obj.created_by.get_username()


class WorkOrderChecklistTemplateApplySerializer(serializers.Serializer):
    template = serializers.PrimaryKeyRelatedField(queryset=WorkOrderChecklistTemplate.objects.filter(is_active=True))


class WorkLogSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = WorkLog
        fields = ["id", "work_date", "hours", "description", "created_by", "created_by_name", "created_at"]
        read_only_fields = fields

    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() or obj.created_by.get_username()


class WorkLogInputSerializer(serializers.Serializer):
    work_date = serializers.DateField(required=False)
    hours = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal("0.01"), max_value=24)
    description = serializers.CharField(max_length=500, allow_blank=False, trim_whitespace=True)


class WorkOrderScheduleSerializer(serializers.ModelSerializer):
    customer_site = serializers.PrimaryKeyRelatedField(
        queryset=CustomerSite.objects.filter(customer__is_active=True), required=False, allow_null=True
    )
    assigned_to = serializers.PrimaryKeyRelatedField(
        queryset=get_user_model().objects.filter(is_active=True), required=False, allow_null=True
    )

    class Meta:
        model = WorkOrder
        fields = ["scheduled_start", "scheduled_end", "customer_site", "service_site_name", "service_address", "service_contact_name", "service_contact_phone", "service_contact_email", "assigned_to", "completion_notes"]

    def validate(self, attrs):
        start = attrs.get("scheduled_start", getattr(self.instance, "scheduled_start", None))
        end = attrs.get("scheduled_end", getattr(self.instance, "scheduled_end", None))
        if start and end and end <= start:
            raise serializers.ValidationError({"scheduled_end": "La hora de fin debe ser posterior a la hora de inicio."})
        site = attrs.get("customer_site")
        if site and site.customer_id != self.instance.sales_order.quote.customer_id:
            raise serializers.ValidationError({"customer_site": "El sitio debe pertenecer al cliente de esta orden."})
        if site and not site.is_active and site.pk != self.instance.customer_site_id:
            raise serializers.ValidationError({"customer_site": "El sitio está inactivo y no se puede asignar a otra orden."})
        if site:
            attrs.update(service_site_name=site.name, service_address=site.address, service_contact_name=site.contact_name, service_contact_phone=site.phone, service_contact_email=site.email)
        return attrs


class WorkOrderEvidenceUploadSerializer(serializers.Serializer):
    file = serializers.FileField(allow_empty_file=False)
    description = serializers.CharField(max_length=500, required=False, allow_blank=True, trim_whitespace=True)

    def create(self, validated_data):
        from django.utils.text import get_valid_filename

        uploaded_file = validated_data.pop("file")
        work_order = validated_data.pop("work_order")
        uploaded_by = validated_data.pop("uploaded_by")
        original_name = get_valid_filename(uploaded_file.name.replace("\\", "/").split("/")[-1])[:255]
        if not original_name:
            raise serializers.ValidationError({"file": "El archivo debe tener un nombre válido."})
        try:
            content_type = inspect_work_order_evidence(original_name, uploaded_file)
        except DjangoValidationError as error:
            detail = error.message_dict if hasattr(error, "message_dict") else error.messages
            raise serializers.ValidationError(detail) from error
        evidence = WorkOrderEvidence(
            file=uploaded_file,
            original_name=original_name,
            content_type=content_type,
            file_size=uploaded_file.size,
            description=validated_data.get("description", ""),
            work_order=work_order,
            uploaded_by=uploaded_by,
        )
        evidence.save()
        return evidence


class WorkOrderEvidenceSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.SerializerMethodField()
    download_path = serializers.SerializerMethodField()

    class Meta:
        model = WorkOrderEvidence
        fields = ["id", "work_order", "original_name", "content_type", "file_size", "description", "uploaded_by_name", "created_at", "download_path"]
        read_only_fields = fields

    def get_uploaded_by_name(self, obj):
        return obj.uploaded_by.get_full_name() or obj.uploaded_by.get_username()

    def get_download_path(self, obj):
        return f"work-orders/{obj.work_order_id}/evidence/{obj.id}/download/"
