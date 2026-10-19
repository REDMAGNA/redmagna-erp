import csv
import io
import re
import unicodedata

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import FileResponse
from django.db import transaction
from django.db.models import Prefetch, Sum
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from django.utils.dateparse import parse_date
from django.utils import timezone

from .models import PurchaseFrameworkAgreement, PurchaseFrameworkAgreementLine, PurchaseOffer, PurchaseOfferLine, PurchaseOrder, PurchaseOrderLine, PurchaseReceipt, PurchaseSourcingEvent, PurchaseSourcingLine, PurchaseSourcingRequest, Supplier, SupplierProduct, SupplierBill, SupplierPayment
from .permissions import PurchaseFrameworkAgreementPermissions, PurchaseOrderPermissions, PurchaseReceiptPermissions, PurchaseSourcingPermissions, SupplierBillPermissions, SupplierPaymentPermissions, SupplierPermissions, SupplierProductPermissions
from .reports import payables_aging, supplier_cfdi_register, supplier_statement
from .serializers import PurchaseAwardAllocationSerializer, PurchaseFrameworkAgreementSerializer, PurchaseFrameworkOrderInputSerializer, PurchaseOfferInputSerializer, PurchaseOfferSerializer, PurchaseOrderSerializer, PurchaseReceiptInputSerializer, PurchaseReceiptSerializer, PurchaseSourcingRFQSerializer, PurchaseSourcingRequestInputSerializer, PurchaseSourcingRequestSerializer, SupplierBillCFDIUploadSerializer, SupplierBillInputSerializer, SupplierBillSerializer, SupplierPaymentReverseSerializer, SupplierPaymentSerializer, SupplierProductSerializer, SupplierSerializer
from .services import award_purchase_allocations, award_purchase_offer, cancel_purchase_order, confirm_purchase_order, post_supplier_payment, receive_purchase_order, register_supplier_bill, reverse_supplier_payment, send_purchase_rfq
from .cfdi import SupplierCFDIValidationError, attach_supplier_bill_cfdi


class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.filter(is_active=True)
    serializer_class = SupplierSerializer
    permission_classes = [SupplierPermissions]
    search_fields = ["name", "legal_name", "rfc", "email"]
    ordering_fields = ["name", "created_at"]

    @action(detail=False, methods=["post"], url_path="import-csv", parser_classes=[MultiPartParser, FormParser])
    def import_csv(self, request):
        uploaded = request.FILES.get("file")
        if uploaded is None:
            raise ValidationError({"file": "Selecciona un archivo CSV."})
        if uploaded.size > 5 * 1024 * 1024:
            raise ValidationError({"file": "El archivo no puede superar 5 MB."})
        try:
            source = uploaded.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ValidationError({"file": "Guarda el CSV como UTF-8 y vuelve a seleccionarlo."}) from None
        if not source.strip():
            raise ValidationError({"file": "El archivo no contiene datos."})

        def normalize_header(value):
            ascii_value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii").casefold()
            return re.sub(r"[^a-z0-9]+", "_", ascii_value).strip("_")

        aliases = {
            "name": {"name", "nombre", "supplier", "proveedor", "vendor"},
            "legal_name": {"legal_name", "razon_social", "company_name", "nombre_fiscal"},
            "rfc": {"rfc", "tax_id", "vat"},
            "email": {"email", "correo", "e_mail"},
            "phone": {"phone", "telefono", "telephone", "mobile"},
            "lead_time_days": {"lead_time_days", "plazo_entrega", "dias_entrega", "lead_time"},
        }
        try:
            try:
                dialect = csv.Sniffer().sniff(source[:4096], delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            reader = csv.DictReader(io.StringIO(source), dialect=dialect)
            header_map = {}
            for header in reader.fieldnames or []:
                normalized = normalize_header(header)
                matching = [field for field, names in aliases.items() if normalized in names]
                if matching:
                    if matching[0] in header_map.values():
                        raise ValidationError({"file": f"Hay más de una columna para {matching[0]}. Deja solo una."})
                    header_map[header] = matching[0]
            if "name" not in header_map.values():
                raise ValidationError({"file": "Incluye una columna Nombre o Proveedor."})
            raw_rows = list(reader)
        except csv.Error:
            raise ValidationError({"file": "No se pudo leer el contenido CSV."}) from None
        if len(raw_rows) > 1000:
            raise ValidationError({"file": "Importa como máximo 1,000 proveedores por archivo."})

        existing_rfcs, existing_emails = set(), set()
        for supplier in Supplier.objects.all().only("rfc", "email"):
            if supplier.rfc.strip():
                existing_rfcs.add(supplier.rfc.strip().upper())
            if supplier.email.strip():
                existing_emails.add(supplier.email.strip().casefold())

        seen_rfcs, seen_emails, results, to_create = set(), set(), [], []
        for row_number, raw in enumerate(raw_rows, start=2):
            payload = {"is_active": True}
            for header, value in raw.items():
                field = header_map.get(header)
                if field:
                    payload[field] = (value or "").strip()
            payload["rfc"] = payload.get("rfc", "").upper()
            if payload.get("lead_time_days") == "":
                payload["lead_time_days"] = None
            serializer = SupplierSerializer(data=payload)
            if not serializer.is_valid():
                errors = "; ".join(f"{field}: {', '.join(str(item) for item in messages)}" for field, messages in serializer.errors.items())
                results.append({"row": row_number, "name": payload.get("name", ""), "status": "error", "detail": errors})
                continue
            clean = serializer.validated_data
            rfc = clean.get("rfc", "").strip().upper()
            email = clean.get("email", "").strip().casefold()
            duplicate = bool(rfc and (rfc in existing_rfcs or rfc in seen_rfcs)) or bool(email and (email in existing_emails or email in seen_emails))
            if duplicate:
                results.append({"row": row_number, "name": clean["name"], "status": "duplicate", "detail": "Coincide por RFC o correo; no se modificará ningún registro."})
                if rfc:
                    seen_rfcs.add(rfc)
                if email:
                    seen_emails.add(email)
                continue
            results.append({"row": row_number, "name": clean["name"], "status": "create", "detail": "Listo para importar."})
            to_create.append(clean)
            if rfc:
                seen_rfcs.add(rfc)
            if email:
                seen_emails.add(email)

        commit = str(request.data.get("commit", "false")).casefold() in {"1", "true", "yes", "si", "sí"}
        if commit and to_create:
            with transaction.atomic():
                for data in to_create:
                    Supplier.objects.create(**data)
        return Response({
            "committed": commit,
            "created": len(to_create) if commit else 0,
            "skipped": sum(item["status"] == "duplicate" for item in results),
            "errors": sum(item["status"] == "error" for item in results),
            "rows": results,
        })

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=["is_active", "updated_at"])


class SupplierProductViewSet(viewsets.ModelViewSet):
    queryset = SupplierProduct.objects.select_related("supplier", "product").prefetch_related("history__changed_by")
    serializer_class = SupplierProductSerializer
    permission_classes = [SupplierProductPermissions]
    search_fields = ["supplier__name", "product__sku", "product__name", "supplier_reference"]
    ordering_fields = ["supplier__name", "product__sku", "unit_cost", "updated_at"]

    def get_queryset(self):
        queryset = super().get_queryset()
        supplier_id = self.request.query_params.get("supplier")
        if supplier_id:
            queryset = queryset.filter(supplier_id=supplier_id)
        return queryset

    def perform_destroy(self, instance):
        serializer = self.get_serializer(
            instance,
            data={"is_active": False, "history_reason": self.request.data.get("history_reason", "")},
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()


class PurchaseSourcingRequestViewSet(viewsets.ModelViewSet):
    queryset = PurchaseSourcingRequest.objects.select_related("target_location", "created_by", "selected_offer__supplier", "purchase_order").prefetch_related(
        "lines__product", "offers__supplier", "offers__lines__sourcing_line__product", "offers__purchase_orders", "events__actor", "events__supplier", "purchase_orders__supplier", "purchase_orders__lines__product",
    )
    serializer_class = PurchaseSourcingRequestSerializer
    permission_classes = [PurchaseSourcingPermissions]
    http_method_names = ["get", "post", "head", "options"]

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = PurchaseSourcingRequestInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        lines = data.pop("lines")
        sourcing = PurchaseSourcingRequest.objects.create(created_by=request.user, **data)
        for index, line in enumerate(lines, start=1):
            PurchaseSourcingLine.objects.create(request=sourcing, line_number=index, **line)
        PurchaseSourcingEvent.objects.create(request=sourcing, action="request_created", detail=f"{len(lines)} productos", actor=request.user)
        return Response(self.get_serializer(sourcing).data, status=201)

    @action(detail=True, methods=["get", "post"])
    @transaction.atomic
    def offers(self, request, pk=None):
        sourcing = PurchaseSourcingRequest.objects.select_for_update().get(pk=self.get_object().pk)
        if request.method == "GET":
            offers = sourcing.offers.select_related("supplier", "received_by").prefetch_related("lines__sourcing_line__product")
            return Response(PurchaseOfferSerializer(offers, many=True).data)
        serializer = PurchaseOfferInputSerializer(data=request.data, context={"sourcing_request": sourcing})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        lines = data.pop("lines")
        supplier = data.pop("supplier")
        if sourcing.offers.filter(supplier=supplier).exists():
            raise ValidationError("Ya existe una oferta de este proveedor para la solicitud.")
        offer = PurchaseOffer.objects.create(request=sourcing, supplier=supplier, received_by=request.user, **data)
        sourcing_lines = {str(line.id): line for line in sourcing.lines.all()}
        for line in lines:
            sourcing_line = sourcing_lines[str(line["sourcing_line"])]
            PurchaseOfferLine.objects.create(offer=offer, sourcing_line=sourcing_line, quoted_quantity=line.get("quantity", sourcing_line.quantity), unit_cost=line["unit_cost"])
        PurchaseSourcingEvent.objects.create(request=sourcing, offer=offer, action="offer_received", detail=f"{supplier.name} · {offer.total:.2f} MXN", actor=request.user)
        return Response(PurchaseOfferSerializer(offer).data, status=201)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def award(self, request, pk=None):
        offer_id = serializers.UUIDField().run_validation(request.data.get("offer"))
        reason = serializers.CharField(max_length=300, required=False, allow_blank=True).run_validation(request.data.get("reason", ""))
        try:
            sourcing = award_purchase_offer(pk, offer_id, request.user, reason)
        except (DjangoValidationError, PurchaseSourcingRequest.DoesNotExist, PurchaseOffer.DoesNotExist) as error:
            raise ValidationError(getattr(error, "messages", [str(error)])) from error
        return Response(self.get_serializer(sourcing).data)

    @action(detail=True, methods=["post"], url_path="award-lines")
    @transaction.atomic
    def award_lines(self, request, pk=None):
        serializer = PurchaseAwardAllocationSerializer(data=request.data.get("allocations"), many=True)
        serializer.is_valid(raise_exception=True)
        try:
            sourcing = award_purchase_allocations(pk, serializer.validated_data, request.user)
        except (DjangoValidationError, PurchaseSourcingRequest.DoesNotExist) as error:
            raise ValidationError(getattr(error, "messages", [str(error)])) from error
        return Response(self.get_serializer(sourcing).data)

    @action(detail=True, methods=["post"], url_path="send-rfq")
    def send_rfq(self, request, pk=None):
        sourcing = self.get_object()
        serializer = PurchaseSourcingRFQSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = send_purchase_rfq(sourcing.pk, serializer.validated_data["supplier"].pk, request.user, serializer.validated_data["confirm_send"])
        except DjangoValidationError as error:
            raise ValidationError(error.message_dict if hasattr(error, "message_dict") else error.messages) from error
        return Response(result)


class PurchaseOrderViewSet(viewsets.ModelViewSet):
    queryset = PurchaseOrder.objects.select_related("supplier", "created_by", "confirmed_by").prefetch_related(
        Prefetch("lines", queryset=PurchaseOrderLine.objects.select_related("product"))
    )
    serializer_class = PurchaseOrderSerializer
    permission_classes = [PurchaseOrderPermissions]
    search_fields = ["number", "supplier__name", "notes", "lines__product__sku", "lines__product__name"]
    ordering_fields = ["number", "order_date", "expected_date", "created_at", "status"]
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        try:
            order = confirm_purchase_order(pk, request.user)
        except DjangoValidationError as error:
            raise ValidationError(error.messages) from error
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        try:
            order = cancel_purchase_order(pk, request.user)
        except DjangoValidationError as error:
            raise ValidationError(error.messages) from error
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        order = self.get_object()
        serializer = PurchaseReceiptInputSerializer(data=request.data, context={"purchase_order": order})
        serializer.is_valid(raise_exception=True)
        try:
            receipt, created = receive_purchase_order(order.pk, request.user, **serializer.validated_data)
        except DjangoValidationError as error:
            raise ValidationError(error.messages) from error
        return Response(PurchaseReceiptSerializer(receipt).data, status=201 if created else 200)

    @action(detail=True, methods=["post"], url_path="register-bill")
    def register_bill(self, request, pk=None):
        order = self.get_object()
        serializer = SupplierBillInputSerializer(data=request.data, context={"purchase_order": order})
        serializer.is_valid(raise_exception=True)
        try:
            bill = register_supplier_bill(order.pk, request.user, **serializer.validated_data)
        except DjangoValidationError as error:
            raise ValidationError(error.message_dict if hasattr(error, "message_dict") else error.messages) from error
        return Response(SupplierBillSerializer(bill).data, status=201)


class PurchaseFrameworkAgreementViewSet(viewsets.ModelViewSet):
    queryset = PurchaseFrameworkAgreement.objects.select_related("supplier", "created_by", "activated_by", "closed_by").prefetch_related("lines__product")
    serializer_class = PurchaseFrameworkAgreementSerializer
    permission_classes = [PurchaseFrameworkAgreementPermissions]
    http_method_names = ["get", "post", "put", "patch", "head", "options"]
    search_fields = ["reference", "supplier__name", "notes", "lines__product__sku", "lines__product__name"]
    ordering_fields = ["reference", "valid_from", "valid_until", "created_at", "status"]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        agreement = self.get_object()
        with transaction.atomic():
            agreement = PurchaseFrameworkAgreement.objects.select_for_update().get(pk=agreement.pk)
            if agreement.status != PurchaseFrameworkAgreement.Status.DRAFT:
                raise ValidationError("Solo puedes activar un acuerdo en borrador.")
            if not agreement.lines.exists():
                raise ValidationError({"lines": "Agrega al menos un producto antes de activar el acuerdo."})
            agreement.status = PurchaseFrameworkAgreement.Status.ACTIVE
            agreement.activated_by = request.user
            agreement.activated_at = timezone.now()
            agreement.save()
        return Response(self.get_serializer(agreement).data)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        agreement = self.get_object()
        with transaction.atomic():
            agreement = PurchaseFrameworkAgreement.objects.select_for_update().get(pk=agreement.pk)
            if agreement.status != PurchaseFrameworkAgreement.Status.ACTIVE:
                raise ValidationError("Solo puedes cerrar un acuerdo vigente.")
            agreement.status = PurchaseFrameworkAgreement.Status.CLOSED
            agreement.closed_by = request.user
            agreement.closed_at = timezone.now()
            agreement.save()
        return Response(self.get_serializer(agreement).data)

    @action(detail=True, methods=["post"], url_path="create-order")
    def create_order(self, request, pk=None):
        serializer = PurchaseFrameworkOrderInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            agreement = PurchaseFrameworkAgreement.objects.select_for_update().get(pk=self.get_object().pk)
            today = timezone.localdate()
            if agreement.status != PurchaseFrameworkAgreement.Status.ACTIVE or not agreement.valid_from <= today <= agreement.valid_until:
                raise ValidationError("El acuerdo debe estar vigente y dentro de sus fechas para generar una orden.")
            rows = serializer.validated_data["lines"]
            if any(row["framework_line"].agreement_id != agreement.pk for row in rows):
                raise ValidationError({"lines": "Todos los renglones deben pertenecer al acuerdo seleccionado."})
            order = PurchaseOrder.objects.create(
                supplier=agreement.supplier,
                order_date=today,
                expected_date=serializer.validated_data.get("expected_date"),
                notes=serializer.validated_data.get("notes", ""),
                framework_agreement=agreement,
                created_by=request.user,
            )
            for index, row in enumerate(rows, start=1):
                source = row["framework_line"]
                if source.quantity_limit is not None:
                    committed = source.purchase_order_lines.exclude(purchase_order__status=PurchaseOrder.Status.CANCELLED).aggregate(total=Sum("quantity"))["total"] or 0
                    if committed + row["quantity"] > source.quantity_limit:
                        raise ValidationError({"lines": f"La cantidad excede el saldo disponible para {source.product.sku}."})
                PurchaseOrderLine.objects.create(
                    purchase_order=order,
                    line_number=index,
                    product=source.product,
                    framework_line=source,
                    expected_location=row["expected_location"],
                    description=source.description,
                    quantity=row["quantity"],
                    unit_cost=source.unit_cost,
                )
        refreshed = PurchaseOrder.objects.select_related("supplier", "created_by").prefetch_related("lines__product").get(pk=order.pk)
        return Response(PurchaseOrderSerializer(refreshed).data, status=201)


class PurchaseReceiptViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PurchaseReceipt.objects.select_related("purchase_order__supplier", "received_by").prefetch_related(
        "lines__purchase_order_line__product", "lines__stock_movement__location"
    )
    serializer_class = PurchaseReceiptSerializer
    permission_classes = [PurchaseReceiptPermissions]
    search_fields = ["purchase_order__number", "purchase_order__supplier__name", "note"]
    ordering_fields = ["receipt_date"]


class SupplierBillViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SupplierBill.objects.select_related("supplier", "purchase_order", "registered_by", "cfdi_record").prefetch_related(
        "lines__purchase_order_line__product"
    )
    serializer_class = SupplierBillSerializer
    permission_classes = [SupplierBillPermissions]
    search_fields = ["invoice_number", "supplier__name", "purchase_order__number"]
    ordering_fields = ["invoice_date", "registered_at", "invoice_number"]

    @action(detail=False, methods=["get"], url_path="cfdi-register")
    def cfdi_register(self, request):
        raw_from = request.query_params.get("date_from")
        raw_to = request.query_params.get("date_to")
        date_from = parse_date(raw_from) if raw_from else None
        date_to = parse_date(raw_to) if raw_to else None
        if raw_from and date_from is None:
            raise ValidationError({"date_from": "Usa una fecha válida con formato AAAA-MM-DD."})
        if raw_to and date_to is None:
            raise ValidationError({"date_to": "Usa una fecha válida con formato AAAA-MM-DD."})
        if date_from and date_to and date_from > date_to:
            raise ValidationError({"date_to": "La fecha final no puede ser anterior a la inicial."})
        try:
            return Response(supplier_cfdi_register(date_from, date_to))
        except DjangoValidationError as error:
            detail = error.message_dict if hasattr(error, "message_dict") else error.messages
            raise ValidationError(detail) from error

    @action(detail=True, methods=["post"], url_path="attach-cfdi", parser_classes=[MultiPartParser, FormParser])
    def attach_cfdi(self, request, pk=None):
        bill = self.get_object()
        serializer = SupplierBillCFDIUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            attach_supplier_bill_cfdi(bill.pk, request.user, serializer.validated_data["xml_file"])
        except SupplierCFDIValidationError as error:
            raise ValidationError(str(error)) from error
        except DjangoValidationError as error:
            raise ValidationError(error.message_dict if hasattr(error, "message_dict") else error.messages) from error
        refreshed = self.get_queryset().get(pk=bill.pk)
        return Response(self.get_serializer(refreshed).data, status=201)

    @action(detail=True, methods=["get"], url_path="cfdi-xml")
    def download_cfdi_xml(self, request, pk=None):
        bill = self.get_object()
        record = getattr(bill, "cfdi_record", None)
        if not record:
            raise ValidationError("Esta factura no tiene un XML CFDI adjunto.")
        filename = re.sub(r"[^A-Za-z0-9._-]", "_", bill.invoice_number)[:70] or "factura-proveedor"
        response = FileResponse(record.xml_file.open("rb"), as_attachment=True, filename=f"{filename}.xml", content_type="application/xml")
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    @action(detail=False, methods=["get"], url_path="payables-aging")
    def payables_aging(self, request):
        raw_date = request.query_params.get("as_of")
        as_of = parse_date(raw_date) if raw_date else None
        if raw_date and as_of is None:
            raise ValidationError({"as_of": "Usa una fecha válida con formato AAAA-MM-DD."})
        return Response(payables_aging(as_of))

    @action(detail=False, methods=["get"], url_path="supplier-statement")
    def supplier_statement(self, request):
        supplier_id = request.query_params.get("supplier_id")
        if not supplier_id:
            raise ValidationError({"supplier_id": "Selecciona un proveedor para consultar su estado de cuenta."})
        raw_date = request.query_params.get("as_of")
        as_of = parse_date(raw_date) if raw_date else None
        if raw_date and as_of is None:
            raise ValidationError({"as_of": "Usa una fecha válida con formato AAAA-MM-DD."})
        try:
            supplier = Supplier.objects.get(pk=supplier_id)
        except (Supplier.DoesNotExist, ValueError, DjangoValidationError):
            raise ValidationError({"supplier_id": "No se encontró el proveedor seleccionado."})
        return Response(supplier_statement(supplier, as_of))


class SupplierPaymentViewSet(viewsets.ModelViewSet):
    queryset = SupplierPayment.objects.select_related("supplier", "created_by", "posted_by", "reversed_by", "reversal_entry").prefetch_related("applications__bill")
    serializer_class = SupplierPaymentSerializer
    permission_classes = [SupplierPaymentPermissions]
    http_method_names = ["get", "post", "put", "patch", "head", "options"]
    search_fields = ["number", "reference", "supplier__name"]
    ordering_fields = ["number", "paid_at", "state"]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"])
    def post(self, request, pk=None):
        try:
            payment = post_supplier_payment(self.get_object().pk, request.user)
        except DjangoValidationError as error:
            raise ValidationError(error.message_dict if hasattr(error, "message_dict") else error.messages) from error
        return Response(self.get_serializer(payment).data)

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        serializer = SupplierPaymentReverseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payment = reverse_supplier_payment(self.get_object().pk, request.user, serializer.validated_data["reason"])
        except DjangoValidationError as error:
            raise ValidationError(error.message_dict if hasattr(error, "message_dict") else error.messages) from error
        return Response(self.get_serializer(payment).data)
