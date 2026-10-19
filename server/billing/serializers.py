from django.db import transaction
from django.db.models import Sum
from rest_framework import serializers
from inventory.models import Product
from sales.models import QuoteLine

from .fiscal.catalogs import is_sat_catalog_value
from .models import CustomerCreditNote, CustomerCreditNoteLine, CustomerInvoice, CustomerInvoiceReminder, InvoiceLine, Payment, PaymentAllocation, FiscalDocument, FiscalEvent


class InvoiceLineSerializer(serializers.ModelSerializer):
    catalog_product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True), allow_null=True, required=False)
    quote_line = serializers.PrimaryKeyRelatedField(queryset=QuoteLine.objects.all(), allow_null=True, required=False, default=None)
    catalog_product_sku = serializers.CharField(source="catalog_product.sku", read_only=True, default="")
    catalog_product_name = serializers.CharField(source="catalog_product.name", read_only=True, default="")
    catalog_product_sat_product_service_key = serializers.CharField(source="catalog_product.sat_product_service_key", read_only=True, default="")
    catalog_product_sat_unit_key = serializers.CharField(source="catalog_product.sat_unit_key", read_only=True, default="")
    catalog_product_sat_tax_object = serializers.CharField(source="catalog_product.sat_tax_object", read_only=True, default="02")
    catalog_product_sat_tax_factor = serializers.CharField(source="catalog_product.sat_tax_factor", read_only=True, default="Tasa")
    catalog_product_sat_border_8_eligible = serializers.BooleanField(source="catalog_product.sat_border_8_eligible", read_only=True, default=False)
    discount_amount = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    line_number = serializers.IntegerField(required=False, min_value=1)
    line_subtotal = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    tax_amount = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)

    class Meta:
        model = InvoiceLine
        fields = ["id", "line_number", "catalog_product", "quote_line", "catalog_product_sku", "catalog_product_name", "catalog_product_sat_product_service_key", "catalog_product_sat_unit_key", "catalog_product_sat_tax_object", "catalog_product_sat_tax_factor", "catalog_product_sat_border_8_eligible", "description", "quantity", "unit_price", "discount_percent", "discount_amount", "tax_rate", "line_subtotal", "tax_amount"]
        read_only_fields = ["id", "line_subtotal", "tax_amount"]

    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError("La cantidad debe ser mayor que cero.")
        return value

    def validate_unit_price(self, value):
        if value < 0:
            raise serializers.ValidationError("El precio no puede ser negativo.")
        return value

    def validate_tax_rate(self, value):
        if not 0 <= value <= 100:
            raise serializers.ValidationError("La tasa debe estar entre 0 y 100.")
        return value

    def validate_line_number(self, value):
        if value < 1:
            raise serializers.ValidationError("La línea debe empezar en 1.")
        return value


class CustomerInvoiceReminderSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerInvoiceReminder
        fields = ["kind", "status", "attempt_count", "last_attempt_at", "sent_at", "last_error"]
        read_only_fields = fields


class CustomerInvoiceSerializer(serializers.ModelSerializer):
    lines = InvoiceLineSerializer(many=True)
    reminders = CustomerInvoiceReminderSerializer(many=True, read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    customer_legal_name = serializers.CharField(source="customer.legal_name", read_only=True)
    customer_rfc = serializers.CharField(source="customer.rfc", read_only=True)
    customer_fiscal_regime = serializers.CharField(source="customer.fiscal_regime", read_only=True)
    customer_fiscal_postal_code = serializers.CharField(source="customer.fiscal_postal_code", read_only=True)
    sales_order_number = serializers.CharField(source="sales_order.number", read_only=True, allow_null=True)
    subtotal = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    tax_total = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    total = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    paid_amount = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    credited_amount = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    balance_due = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    is_opening_balance = serializers.BooleanField(read_only=True)

    class Meta:
        model = CustomerInvoice
        fields = ["id", "number", "customer", "customer_name", "customer_legal_name", "customer_rfc", "customer_fiscal_regime", "customer_fiscal_postal_code", "sales_order", "sales_order_number", "currency", "issue_date", "due_date", "memo", "state", "lines", "reminders", "subtotal", "tax_total", "total", "paid_amount", "credited_amount", "balance_due", "is_opening_balance", "opening_balance_batch_id", "opening_external_number", "opening_source_system", "opening_cutoff_date", "opening_original_total", "opening_paid_before_cutoff", "created_by", "created_at", "opened_by", "opened_at"]
        read_only_fields = ["id", "number", "sales_order", "state", "is_opening_balance", "opening_balance_batch_id", "opening_external_number", "opening_source_system", "opening_cutoff_date", "opening_original_total", "opening_paid_before_cutoff", "created_by", "created_at", "opened_by", "opened_at"]

    def validate_lines(self, lines):
        if not lines:
            raise serializers.ValidationError("Agrega al menos un concepto.")
        return lines

    def validate_currency(self, value):
        if value != "MXN":
            raise serializers.ValidationError("La primera versión opera únicamente en MXN.")
        return value

    def _validate_order_invoice_lines(self, sales_order, lines, exclude_invoice=None):
        previous_lines = InvoiceLine.objects.filter(invoice__sales_order=sales_order)
        if exclude_invoice is not None:
            previous_lines = previous_lines.exclude(invoice=exclude_invoice)
        if previous_lines.filter(quote_line__isnull=True).exists():
            raise serializers.ValidationError({"lines": "Hay facturas previas sin concepto de cotización relacionado; revisa esas facturas antes de continuar."})
        billed = dict(previous_lines.values("quote_line_id").annotate(quantity=Sum("quantity")).values_list("quote_line_id", "quantity"))
        requested = {}
        for line in lines:
            quote_line = line.get("quote_line")
            if quote_line is None or quote_line.quote_id != sales_order.quote_id:
                raise serializers.ValidationError({"lines": "Cada renglón de una factura ligada debe señalar un concepto de la cotización de esa orden."})
            if line.get("discount_percent", quote_line.discount_percent) != quote_line.discount_percent:
                raise serializers.ValidationError({"lines": f"El descuento de {quote_line.description} debe coincidir con la cotización aceptada."})
            requested[quote_line.pk] = requested.get(quote_line.pk, 0) + line["quantity"]
        for quote_line_id, quantity in requested.items():
            quote_line = next(item["quote_line"] for item in lines if item["quote_line"].pk == quote_line_id)
            if billed.get(quote_line_id, 0) + quantity > quote_line.billable_quantity:
                raise serializers.ValidationError({"lines": f"La cantidad facturada excedería lo cotizado para {quote_line.description}."})

    def validate(self, attrs):
        customer = attrs.get("customer", getattr(self.instance, "customer", None))
        sales_order = attrs.get("sales_order", getattr(self.instance, "sales_order", None))
        if sales_order and customer and sales_order.quote.customer_id != customer.id:
            raise serializers.ValidationError({"sales_order": "La orden de venta debe pertenecer al mismo cliente de la factura."})
        lines = attrs.get("lines")
        if lines is not None:
            if not sales_order and any(line.get("quote_line") for line in lines):
                raise serializers.ValidationError({"lines": "Solo las facturas ligadas a una orden de venta pueden vincular conceptos de cotización."})
            if sales_order:
                self._validate_order_invoice_lines(sales_order, lines, exclude_invoice=self.instance)
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        lines = validated_data.pop("lines")
        invoice = CustomerInvoice.objects.create(**validated_data)
        for i, line in enumerate(lines, start=1):
            InvoiceLine.objects.create(invoice=invoice, line_number=line.pop("line_number", i), **line)
        return invoice

    @transaction.atomic
    def update(self, instance, validated_data):
        current = CustomerInvoice.objects.get(pk=instance.pk)
        locked_order = None
        if current.sales_order_id:
            from sales.models import SalesOrder

            locked_order = SalesOrder.objects.select_for_update().get(pk=current.sales_order_id)
        instance = CustomerInvoice.objects.select_for_update().get(pk=instance.pk)
        if instance.state != CustomerInvoice.State.DRAFT:
            raise serializers.ValidationError("Solo se edita una factura en borrador.")
        lines = validated_data.pop("lines", None)
        if lines is not None and locked_order:
            self._validate_order_invoice_lines(locked_order, lines, exclude_invoice=instance)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.save()
        if lines is not None:
            instance.lines.all().delete()
            for i, line in enumerate(lines, start=1):
                InvoiceLine.objects.create(invoice=instance, line_number=line.pop("line_number", i), **line)
        return instance


class PaymentAllocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentAllocation
        fields = ["id", "invoice", "amount"]
        read_only_fields = ["id"]

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("El importe aplicado debe ser mayor que cero.")
        return value


class CustomerCreditNoteLineSerializer(serializers.ModelSerializer):
    invoice_line_description = serializers.CharField(source="invoice_line.description", read_only=True)
    unit_price = serializers.DecimalField(max_digits=14, decimal_places=2, source="invoice_line.unit_price", read_only=True)
    discount_percent = serializers.DecimalField(max_digits=5, decimal_places=2, source="invoice_line.discount_percent", read_only=True)
    tax_rate = serializers.DecimalField(max_digits=5, decimal_places=2, source="invoice_line.tax_rate", read_only=True)
    line_subtotal = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    tax_amount = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)

    class Meta:
        model = CustomerCreditNoteLine
        fields = ["id", "invoice_line", "invoice_line_description", "line_number", "quantity", "unit_price", "discount_percent", "tax_rate", "line_subtotal", "tax_amount"]
        read_only_fields = ["id", "invoice_line_description", "unit_price", "discount_percent", "tax_rate", "line_subtotal", "tax_amount"]


class CustomerCreditNoteSerializer(serializers.ModelSerializer):
    lines = CustomerCreditNoteLineSerializer(many=True)
    invoice_number = serializers.CharField(source="invoice.number", read_only=True)
    customer_name = serializers.CharField(source="invoice.customer.name", read_only=True)
    subtotal = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    tax_total = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    total = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)

    class Meta:
        model = CustomerCreditNote
        fields = ["id", "number", "invoice", "invoice_number", "customer_name", "issue_date", "reason", "state", "lines", "subtotal", "tax_total", "total", "created_by", "created_at", "posted_by", "posted_at", "reversed_by", "reversed_at", "reversal_reason"]
        read_only_fields = ["id", "number", "state", "created_by", "created_at", "posted_by", "posted_at", "reversed_by", "reversed_at", "reversal_reason"]

    def validate_lines(self, lines):
        if not lines:
            raise serializers.ValidationError("Agrega al menos un concepto de la factura.")
        invoice_line_ids = [row["invoice_line"].pk for row in lines]
        if len(invoice_line_ids) != len(set(invoice_line_ids)):
            raise serializers.ValidationError("No repitas un renglón de factura; suma las cantidades en un solo concepto.")
        return lines

    def validate(self, attrs):
        invoice = attrs.get("invoice", getattr(self.instance, "invoice", None))
        if invoice and invoice.state in [CustomerInvoice.State.DRAFT, CustomerInvoice.State.CANCELLED]:
            raise serializers.ValidationError({"invoice": "Selecciona una factura abierta y no cancelada."})
        lines = attrs.get("lines")
        if invoice and lines is not None:
            for row in lines:
                if row["invoice_line"].invoice_id != invoice.id:
                    raise serializers.ValidationError({"lines": "Cada concepto debe pertenecer a la factura seleccionada."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        lines = validated_data.pop("lines")
        note = CustomerCreditNote.objects.create(**validated_data)
        for i, row in enumerate(lines, start=1):
            CustomerCreditNoteLine.objects.create(credit_note=note, line_number=row.get("line_number", i), **row)
        return note

    @transaction.atomic
    def update(self, instance, validated_data):
        note = CustomerCreditNote.objects.select_for_update().get(pk=instance.pk)
        if note.state != CustomerCreditNote.State.DRAFT:
            raise serializers.ValidationError("Solo se edita una nota de crédito en borrador.")
        lines = validated_data.pop("lines", None)
        for key, value in validated_data.items():
            setattr(note, key, value)
        note.save()
        if lines is not None:
            note.lines.all().delete()
            for i, row in enumerate(lines, start=1):
                CustomerCreditNoteLine.objects.create(credit_note=note, line_number=row.get("line_number", i), **row)
        return note

class PaymentSerializer(serializers.ModelSerializer):
    allocations = PaymentAllocationSerializer(many=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)

    class Meta:
        model = Payment
        fields = ["id", "number", "customer", "customer_name", "amount", "currency", "method", "received_at", "reference", "memo", "state", "allocations", "created_by", "created_at", "posted_by", "posted_at", "reversed_by", "reversed_at", "reversal_reason"]
        read_only_fields = ["id", "number", "state", "created_by", "created_at", "posted_by", "posted_at", "reversed_by", "reversed_at", "reversal_reason"]

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("El importe recibido debe ser mayor que cero.")
        return value

    def validate_currency(self, value):
        if value != "MXN":
            raise serializers.ValidationError("La primera versión opera únicamente en MXN.")
        return value

    def validate_allocations(self, allocations):
        if not allocations:
            raise serializers.ValidationError("Agrega al menos una factura al cobro.")
        invoice_ids = [item["invoice"].id for item in allocations]
        if len(invoice_ids) != len(set(invoice_ids)):
            raise serializers.ValidationError("No repitas una factura; combina los importes en una sola aplicación.")
        return allocations

    def validate(self, attrs):
        customer = attrs.get("customer", getattr(self.instance, "customer", None))
        currency = attrs.get("currency", getattr(self.instance, "currency", "MXN"))
        allocations = attrs.get("allocations")
        if allocations is not None:
            for allocation in allocations:
                invoice = allocation["invoice"]
                if customer and invoice.customer_id != customer.id:
                    raise serializers.ValidationError({"allocations": "El cobro y la factura deben pertenecer al mismo cliente."})
                if invoice.currency != currency:
                    raise serializers.ValidationError({"allocations": "El cobro y la factura deben usar la misma moneda."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        allocations = validated_data.pop("allocations")
        payment = Payment.objects.create(**validated_data)
        for allocation in allocations:
            PaymentAllocation.objects.create(payment=payment, **allocation)
        return payment

    @transaction.atomic
    def update(self, instance, validated_data):
        instance = Payment.objects.select_for_update().get(pk=instance.pk)
        if instance.state != Payment.State.DRAFT:
            raise serializers.ValidationError("Solo se edita un cobro en borrador.")
        allocations = validated_data.pop("allocations", None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.save()
        if allocations is not None:
            instance.allocations.all().delete()
            for allocation in allocations:
                PaymentAllocation.objects.create(payment=instance, **allocation)
        return instance


class FiscalEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = FiscalEvent
        fields = ["action", "state_before", "state_after", "provider_request_id", "response_code", "response_payload", "occurred_at"]


class FiscalDocumentSerializer(serializers.ModelSerializer):
    events = FiscalEventSerializer(many=True, read_only=True)
    pdf_available = serializers.SerializerMethodField()

    def get_pdf_available(self, obj):
        return bool(obj.pdf_storage_key)

    class Meta:
        model = FiscalDocument
        fields = ["id", "invoice", "credit_note", "payment", "replaces", "document_type", "cfdi_version", "provider_code", "idempotency_key", "provider_request_id", "cfdi_uuid", "state", "issuer_rfc", "recipient_rfc", "recipient_name", "recipient_fiscal_regime", "recipient_postal_code", "cfdi_use", "payment_method", "payment_form", "currency", "request_payload", "request_xml", "xml_content", "pdf_available", "stamped_at", "cancellation_reason", "replacement_uuid", "created_at", "events"]
        read_only_fields = fields


class CancelFiscalDocumentSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(choices=FiscalDocument.CancellationReason.choices)
    replacement_uuid = serializers.UUIDField(required=False, allow_null=True)
    confirm_irreversible = serializers.BooleanField(required=True)


class ReversePaymentSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, trim_whitespace=True)
    confirm_irreversible = serializers.BooleanField(required=True)

    def validate_reason(self, value):
        if len(value.strip()) < 10:
            raise serializers.ValidationError("Escribe un motivo de al menos 10 caracteres.")
        return value.strip()


class ReverseCustomerCreditNoteSerializer(ReversePaymentSerializer):
    pass


class FiscalConceptMappingSerializer(serializers.Serializer):
    invoice_line_id = serializers.UUIDField()
    product_service_key = serializers.RegexField(r"^\d{8}$", max_length=8)
    unit_key = serializers.RegexField(r"^[A-Z0-9]{2,3}$", max_length=3)
    tax_object = serializers.ChoiceField(choices=[("01", "No objeto de impuesto"), ("02", "Sí objeto de impuesto")])
    tax_factor = serializers.ChoiceField(choices=[("Tasa", "Tasa"), ("Exento", "Exento")], required=False, default="Tasa")

    def validate_unit_key(self, value):
        return value.upper()


class PrepareInvoiceCFDISerializer(serializers.Serializer):
    cfdi_use = serializers.RegexField(r"^[A-Z0-9]{3}$", max_length=3)
    exportation = serializers.ChoiceField(choices=[("01", "No aplica"), ("02", "Definitiva con clave A1"), ("03", "Temporal"), ("04", "Definitiva con clave distinta a A1 o sin enajenación")])
    payment_method = serializers.ChoiceField(choices=[("PUE", "Pago en una sola exhibición"), ("PPD", "Pago en parcialidades o diferido")])
    payment_form = serializers.RegexField(r"^\d{2}$", max_length=2)
    idempotency_key = serializers.UUIDField()
    concepts = FiscalConceptMappingSerializer(many=True)

    def validate(self, attrs):
        invoice = self.context["invoice"]
        if not is_sat_catalog_value("c_UsoCFDI", attrs["cfdi_use"]):
            raise serializers.ValidationError({"cfdi_use": "La clave no está en el catálogo CFDI 4.0 incluido."})
        if not is_sat_catalog_value("c_Exportacion", attrs["exportation"]):
            raise serializers.ValidationError({"exportation": "La clave no está en el catálogo CFDI 4.0 incluido."})
        if not is_sat_catalog_value("c_FormaPago", attrs["payment_form"]):
            raise serializers.ValidationError({"payment_form": "La clave no está en el catálogo CFDI 4.0 incluido."})
        lines = list(invoice.lines.order_by("line_number"))
        mappings = attrs["concepts"]
        mapped_ids = [item["invoice_line_id"] for item in mappings]
        expected_ids = [line.id for line in lines]
        if len(mapped_ids) != len(set(mapped_ids)) or set(mapped_ids) != set(expected_ids):
            raise serializers.ValidationError({"concepts": "Incluye exactamente una clasificación para cada concepto de la factura."})
        mapping_by_id = {item["invoice_line_id"]: item for item in mappings}
        for line in lines:
            mapping = mapping_by_id[line.id]
            if not is_sat_catalog_value("c_ClaveProdServ", mapping["product_service_key"]):
                raise serializers.ValidationError({"concepts": f"La clave SAT de producto o servicio del concepto {line.line_number} no está en el catálogo CFDI 4.0 incluido."})
            if not is_sat_catalog_value("c_ClaveUnidad", mapping["unit_key"]):
                raise serializers.ValidationError({"concepts": f"La unidad SAT del concepto {line.line_number} no está en el catálogo CFDI 4.0 incluido."})
            if mapping["tax_object"] == "01" and line.tax_rate != 0:
                raise serializers.ValidationError({"concepts": f"El concepto {line.line_number} marcado como no objeto debe tener tasa estimada cero."})
            if mapping["tax_object"] == "02" and line.tax_rate not in {0, 8, 16}:
                raise serializers.ValidationError({"concepts": f"El concepto {line.line_number} tiene una tasa fuera de esta preparación inicial (0, 8 o 16)."})
            if mapping["tax_object"] == "02" and mapping["tax_factor"] == "Exento" and line.tax_rate != 0:
                raise serializers.ValidationError({"concepts": f"El concepto {line.line_number} solo puede marcarse Exento con tasa cero."})
        if attrs["payment_method"] == "PPD" and attrs["payment_form"] != "99":
            raise serializers.ValidationError({"payment_form": "Para PPD se requiere la forma 99 en esta preparación inicial."})
        if attrs["payment_method"] == "PUE" and attrs["payment_form"] == "99":
            raise serializers.ValidationError({"payment_form": "La forma 99 no se admite para PUE."})
        if attrs["payment_method"] == "PUE" and invoice.state != CustomerInvoice.State.PAID:
            raise serializers.ValidationError({"payment_method": "PUE requiere que la factura esté completamente pagada en el ERP."})
        return attrs


class PreparePaymentCFDISerializer(serializers.Serializer):
    payment_form = serializers.RegexField(r"^\d{2}$", max_length=2)
    idempotency_key = serializers.UUIDField()

    def validate_payment_form(self, value):
        if value == "99":
            raise serializers.ValidationError("El complemento debe registrar la forma de pago efectivamente recibida, no la clave 99.")
        if not is_sat_catalog_value("c_FormaPago", value):
            raise serializers.ValidationError("La clave no está en el catálogo CFDI 4.0 incluido.")
        return value


class PrepareCreditNoteCFDISerializer(serializers.Serializer):
    cfdi_use = serializers.RegexField(r"^[A-Z0-9]{3}$", max_length=3)
    payment_form = serializers.RegexField(r"^\d{2}$", max_length=2)
    idempotency_key = serializers.UUIDField()

    def validate(self, attrs):
        if not is_sat_catalog_value("c_UsoCFDI", attrs["cfdi_use"]):
            raise serializers.ValidationError({"cfdi_use": "La clave no está en el catálogo CFDI 4.0 incluido."})
        if attrs["payment_form"] == "99" or not is_sat_catalog_value("c_FormaPago", attrs["payment_form"]):
            raise serializers.ValidationError({"payment_form": "Selecciona la forma de pago elegida por Contabilidad en el catálogo SAT; no se admite 99 con PUE."})
        return attrs
