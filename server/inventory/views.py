import csv
import io
import re
import unicodedata

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, DecimalField, F, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from decimal import Decimal
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from purchasing.models import PurchaseOrderLine
from .models import InventoryCount, InventoryCountLine, Product, ReorderRule, StockBalance, StockLocation, StockMovement, StockReservation, StockTransfer, StockUnit
from .permissions import InventoryPermissions
from .serializers import InventoryCountCreateSerializer, InventoryCountQuantitySerializer, InventoryCountSerializer, ProductSerializer, ReorderRuleSerializer, StockBalanceSerializer, StockLocationSerializer, StockMovementInputSerializer, StockMovementSerializer, StockReservationInputSerializer, StockReservationSerializer, StockTransferInputSerializer, StockTransferSerializer, StockUnitInstallSerializer, StockUnitReservationInputSerializer, StockUnitSerializer
from .forecast import build_replenishment_forecast
from .services import apply_inventory_count, create_inventory_count, mark_stock_unit_installed, post_stock_movement, post_stock_transfer, record_inventory_count, release_stock_reservation, release_stock_unit_reservation, reserve_stock, reserve_stock_unit, submit_inventory_count


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    permission_classes = [InventoryPermissions]
    search_fields = ["sku", "barcode", "name", "description"]
    ordering_fields = ["sku", "barcode", "name", "kind", "is_active"]
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

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
            "sku": {"sku", "codigo", "code", "default_code", "internal_reference", "product_code"},
            "barcode": {"barcode", "codigo_de_barras", "ean", "gtin", "upc"},
            "name": {"name", "nombre", "product", "producto"},
            "description": {"description", "descripcion", "sales_description"},
            "kind": {"kind", "type", "tipo", "product_type"},
            "unit": {"unit", "unidad", "unit_of_measure", "uom"},
            "tracking_policy": {"tracking_policy", "tracking", "seguimiento"},
            "sat_product_service_key": {"sat_product_service_key", "clave_prodserv", "clave_sat_prodserv", "clave_producto_servicio"},
            "sat_unit_key": {"sat_unit_key", "clave_unidad_sat", "clave_unidad"},
            "sat_tax_object": {"sat_tax_object", "objeto_impuesto", "objeto_imp"},
            "sat_tax_factor": {"sat_tax_factor", "factor_iva", "tipo_factor"},
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
            if "sku" not in header_map.values() or "name" not in header_map.values():
                raise ValidationError({"file": "Incluye las columnas SKU o Código, y Nombre."})
            raw_rows = list(reader)
        except csv.Error:
            raise ValidationError({"file": "No se pudo leer el contenido CSV."}) from None
        if len(raw_rows) > 1000:
            raise ValidationError({"file": "Importa como máximo 1,000 productos por archivo."})

        existing_skus = {value.strip().upper() for value in Product.objects.values_list("sku", flat=True)}
        seen_skus, results, to_create = set(), [], []
        for row_number, raw in enumerate(raw_rows, start=2):
            payload = {"is_active": True}
            for header, value in raw.items():
                field = header_map.get(header)
                if field:
                    payload[field] = (value or "").strip()
            sku = payload.get("sku", "").strip().upper()
            if sku and (sku in existing_skus or sku in seen_skus):
                results.append({"row": row_number, "sku": sku, "name": payload.get("name", ""), "status": "duplicate", "detail": "El SKU ya existe; no se modificará el producto."})
                seen_skus.add(sku)
                continue
            payload["sku"] = sku
            if payload.get("kind"):
                kind = normalize_header(payload["kind"])
                payload["kind"] = "service" if kind in {"service", "servicio"} else "stockable" if kind in {"stockable", "product", "producto", "inventariable", "goods", "consu", "stockable_product", "storable", "storable_product", "producto_con_existencias"} else payload["kind"]
            if payload.get("tracking_policy"):
                tracking = normalize_header(payload["tracking_policy"])
                payload["tracking_policy"] = "serial" if tracking in {"serial", "serie", "numero_de_serie", "by_unique_serial_number", "serial_number"} else "quantity" if tracking in {"quantity", "cantidad", "por_cantidad", "by_lots", "lot", "none"} else payload["tracking_policy"]
            for key in ("sat_product_service_key", "sat_unit_key"):
                if key in payload:
                    payload[key] = payload[key].upper()
            if payload.get("sat_tax_object"):
                tax_object = normalize_header(payload["sat_tax_object"])
                payload["sat_tax_object"] = "01" if tax_object in {"01", "no_objeto"} else "02" if tax_object in {"02", "si_objeto"} else payload["sat_tax_object"]
            if payload.get("sat_tax_factor"):
                tax_factor = normalize_header(payload["sat_tax_factor"])
                payload["sat_tax_factor"] = "Exento" if tax_factor in {"exento", "exempt"} else "Tasa" if tax_factor in {"tasa", "rate"} else payload["sat_tax_factor"]
            serializer = ProductSerializer(data=payload)
            if not serializer.is_valid():
                errors = "; ".join(f"{field}: {', '.join(str(item) for item in messages)}" for field, messages in serializer.errors.items())
                results.append({"row": row_number, "sku": sku, "name": payload.get("name", ""), "status": "error", "detail": errors})
                continue
            results.append({"row": row_number, "sku": sku, "name": serializer.validated_data["name"], "status": "create", "detail": "Listo para importar."})
            to_create.append(serializer)
            seen_skus.add(sku)

        commit = str(request.data.get("commit", "false")).casefold() in {"1", "true", "yes", "si", "sí"}
        created_count = 0
        if commit and to_create:
            try:
                with transaction.atomic():
                    for serializer in to_create:
                        serializer.save()
            except IntegrityError:
                raise ValidationError({"file": "El catálogo cambió durante la carga. Vuelve a seleccionar el archivo y revisa los SKU antes de confirmar."}) from None
            created_count = len(to_create)
        return Response({
            "committed": commit,
            "created": created_count,
            "skipped": sum(item["status"] == "duplicate" for item in results),
            "errors": sum(item["status"] == "error" for item in results),
            "rows": results,
        })


class StockLocationViewSet(viewsets.ModelViewSet):
    queryset = StockLocation.objects.filter(is_active=True)
    serializer_class = StockLocationSerializer
    permission_classes = [InventoryPermissions]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        queryset = StockLocation.objects.all() if self.request.user.has_perm("inventory.change_stocklocation") else StockLocation.objects.filter(is_active=True)
        return queryset.select_for_update() if self.request.method == "PATCH" else queryset

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    def handle_exception(self, exc):
        if isinstance(exc, DjangoValidationError):
            detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            exc = ValidationError(detail)
        return super().handle_exception(exc)


class StockBalanceViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StockBalance.objects.select_related("product", "location").filter(product__is_active=True)
    serializer_class = StockBalanceSerializer
    permission_classes = [InventoryPermissions]
    search_fields = ["product__sku", "product__name", "location__code", "location__name"]
    ordering_fields = ["quantity", "product__sku", "updated_at"]

    def get_queryset(self):
        reserved = StockReservation.objects.filter(product_id=OuterRef("product_id"), location_id=OuterRef("location_id"), state=StockReservation.State.ACTIVE).order_by().values("product_id").annotate(total=Sum("remaining_quantity")).values("total")[:1]
        reserved_serials = StockUnit.objects.filter(product_id=OuterRef("product_id"), location_id=OuterRef("location_id"), state=StockUnit.State.RESERVED).order_by().values("product_id").annotate(total=Count("id")).values("total")[:1]
        decimal_field = DecimalField(max_digits=14, decimal_places=3)
        reserved_quantity = Coalesce(Subquery(reserved, output_field=decimal_field), Value(Decimal("0.000")), output_field=decimal_field)
        reserved_serial_quantity = Coalesce(Subquery(reserved_serials, output_field=decimal_field), Value(Decimal("0.000")), output_field=decimal_field)
        return self.queryset.annotate(current_reserved=reserved_quantity + reserved_serial_quantity)


class ReorderRuleViewSet(viewsets.ModelViewSet):
    serializer_class = ReorderRuleSerializer
    permission_classes = [InventoryPermissions]
    http_method_names = ["get", "post", "put", "patch", "head", "options"]
    search_fields = ["product__sku", "product__name", "location__code", "location__name"]
    ordering_fields = ["product__sku", "location__code", "minimum_quantity", "target_quantity", "is_active"]

    def get_queryset(self):
        balance = StockBalance.objects.filter(product_id=OuterRef("product_id"), location_id=OuterRef("location_id")).values("quantity")[:1]
        reserved = StockReservation.objects.filter(product_id=OuterRef("product_id"), location_id=OuterRef("location_id"), state=StockReservation.State.ACTIVE).order_by().values("product_id").annotate(total=Sum("remaining_quantity")).values("total")[:1]
        reserved_serials = StockUnit.objects.filter(product_id=OuterRef("product_id"), location_id=OuterRef("location_id"), state=StockUnit.State.RESERVED).order_by().values("product_id").annotate(total=Count("id")).values("total")[:1]
        incoming = PurchaseOrderLine.objects.filter(
            product_id=OuterRef("product_id"),
            expected_location_id=OuterRef("location_id"),
            purchase_order__status__in=["ordered", "partial"],
            received_quantity__lt=F("quantity"),
        ).order_by().values("product_id").annotate(
            remaining=Sum(F("quantity") - F("received_quantity"))
        ).values("remaining")[:1]
        decimal_field = DecimalField(max_digits=14, decimal_places=3)
        reserved_quantity = Coalesce(Subquery(reserved, output_field=decimal_field), Value(Decimal("0.000")), output_field=decimal_field)
        reserved_serial_quantity = Coalesce(Subquery(reserved_serials, output_field=decimal_field), Value(Decimal("0.000")), output_field=decimal_field)
        return ReorderRule.objects.select_related("product", "location").annotate(
            current_on_hand=Coalesce(Subquery(balance, output_field=decimal_field), Value(Decimal("0.000")), output_field=decimal_field),
            current_incoming=Coalesce(Subquery(incoming, output_field=decimal_field), Value(Decimal("0.000")), output_field=decimal_field),
            current_reserved=reserved_quantity + reserved_serial_quantity,
        )

    @action(detail=True, methods=["get"])
    def forecast(self, request, pk=None):
        try:
            horizon_days = int(request.query_params.get("horizon_days", "30"))
        except (TypeError, ValueError) as error:
            raise ValidationError({"horizon_days": "Indica un número de días entre 1 y 180."}) from error
        if not 1 <= horizon_days <= 180:
            raise ValidationError({"horizon_days": "El horizonte permitido va de 1 a 180 días."})
        rule = self.get_object()
        return Response(build_replenishment_forecast(rule, horizon_days))

    def handle_exception(self, exc):
        if isinstance(exc, DjangoValidationError):
            detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            exc = ValidationError(detail)
        return super().handle_exception(exc)


class StockUnitViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StockUnit.objects.select_related("product", "location", "work_order__sales_order__quote", "customer").prefetch_related(
        "events__created_by", "events__movement",
        "events__movement__purchase_receipt_line__receipt__purchase_order__supplier",
        "events__movement__purchase_receipt_line__purchase_order_line__purchase_order__supplier",
        "events__work_order__sales_order__quote", "events__customer", "events__from_location", "events__to_location",
    )
    serializer_class = StockUnitSerializer
    permission_classes = [InventoryPermissions]
    search_fields = ["serial_number", "product__sku", "product__name", "work_order__sales_order__quote__number"]
    ordering_fields = ["serial_number", "state", "updated_at"]

    @action(detail=True, methods=["post"])
    def install(self, request, pk=None):
        serializer = StockUnitInstallSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            unit = mark_stock_unit_installed(pk, request.user, **serializer.validated_data)
        except DjangoValidationError as error:
            raise ValidationError(error.messages) from error
        return Response(self.get_serializer(unit).data)

    @action(detail=True, methods=["post"])
    def reserve(self, request, pk=None):
        serializer = StockUnitReservationInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            unit = reserve_stock_unit(pk, actor=request.user, **serializer.validated_data)
        except DjangoValidationError as error:
            detail = error.message_dict if hasattr(error, "message_dict") else error.messages
            raise ValidationError(detail) from error
        return Response(self.get_serializer(unit).data)

    @action(detail=True, methods=["post"])
    def release(self, request, pk=None):
        try:
            unit = release_stock_unit_reservation(pk, request.user)
        except DjangoValidationError as error:
            detail = error.message_dict if hasattr(error, "message_dict") else error.messages
            raise ValidationError(detail) from error
        return Response(self.get_serializer(unit).data)


class StockMovementViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StockMovement.objects.select_related("product", "location", "counterpart_location", "work_order__sales_order__quote", "created_by")
    serializer_class = StockMovementSerializer
    permission_classes = [InventoryPermissions]
    search_fields = ["product__sku", "product__name", "reference", "note", "work_order__sales_order__quote__number", "serial_events__unit__serial_number"]
    ordering_fields = ["kind", "quantity", "created_at"]

    def _post(self, request, kind):
        serializer = StockMovementInputSerializer(data=request.data, context={"movement_kind": kind})
        serializer.is_valid(raise_exception=True)
        try:
            result = post_stock_movement(
                kind=kind,
                actor=request.user,
                **serializer.validated_data,
            )
        except DjangoValidationError as error:
            raise ValidationError(error.messages) from error
        if isinstance(result, tuple):
            movement, created = result
        else:
            movement, created = result, True
        return Response(StockMovementSerializer(movement).data, status=201 if created else 200)

    @action(detail=False, methods=["post"])
    def receive(self, request):
        return self._post(request, StockMovement.Kind.RECEIPT)

    @action(detail=False, methods=["post"])
    def issue(self, request):
        return self._post(request, StockMovement.Kind.ISSUE)

    @action(detail=False, methods=["post"], url_path="return")
    def return_stock(self, request):
        return self._post(request, StockMovement.Kind.RETURN)

    @action(detail=False, methods=["post"])
    def adjust(self, request):
        direction = request.data.get("direction")
        if direction not in {"in", "out"}:
            raise ValidationError({"direction": "Indica 'in' o 'out' para el ajuste."})
        kind = StockMovement.Kind.ADJUSTMENT_IN if direction == "in" else StockMovement.Kind.ADJUSTMENT_OUT
        return self._post(request, kind)


class StockTransferViewSet(viewsets.ModelViewSet):
    queryset = StockTransfer.objects.select_related("source_location", "destination_location", "created_by").prefetch_related("lines__product")
    serializer_class = StockTransferSerializer
    permission_classes = [InventoryPermissions]
    http_method_names = ["get", "post", "head", "options"]

    def create(self, request, *args, **kwargs):
        serializer = StockTransferInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            transfer = post_stock_transfer(actor=request.user, **serializer.validated_data)
        except DjangoValidationError as error:
            detail = error.message_dict if hasattr(error, "message_dict") else error.messages
            raise ValidationError(detail) from error
        transfer = self.get_queryset().get(pk=transfer.pk)
        response_serializer = self.get_serializer(transfer)
        return Response(response_serializer.data, status=201)


class StockReservationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StockReservation.objects.select_related("work_order__sales_order__quote", "product", "location", "created_by").prefetch_related("events__created_by")
    serializer_class = StockReservationSerializer
    permission_classes = [InventoryPermissions]
    ordering_fields = ["created_at", "state", "product__sku", "location__code"]
    search_fields = ["product__sku", "product__name", "location__code", "work_order__sales_order__quote__number"]

    def create(self, request, *args, **kwargs):
        serializer = StockReservationInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            reservation = reserve_stock(actor=request.user, **serializer.validated_data)
        except DjangoValidationError as error:
            detail = error.message_dict if hasattr(error, "message_dict") else error.messages
            raise ValidationError(detail) from error
        reservation = self.get_queryset().get(pk=reservation.pk)
        return Response(self.get_serializer(reservation).data, status=201)

    @action(detail=True, methods=["post"])
    def release(self, request, pk=None):
        try:
            reservation = release_stock_reservation(pk, request.user)
        except DjangoValidationError as error:
            detail = error.message_dict if hasattr(error, "message_dict") else error.messages
            raise ValidationError(detail) from error
        reservation = self.get_queryset().get(pk=reservation.pk)
        return Response(self.get_serializer(reservation).data)


class InventoryCountViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = InventoryCount.objects.select_related("location", "created_by", "reviewed_by").prefetch_related("lines__product")
    serializer_class = InventoryCountSerializer
    permission_classes = [InventoryPermissions]
    ordering_fields = ["created_at", "state", "location__code"]
    search_fields = ["location__code", "reason", "lines__product__sku", "lines__product__name"]

    def create(self, request, *args, **kwargs):
        serializer = InventoryCountCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            count = create_inventory_count(actor=request.user, **serializer.validated_data)
        except (DjangoValidationError, StockLocation.DoesNotExist) as error:
            detail = error.message_dict if hasattr(error, "message_dict") else error.messages if hasattr(error, "messages") else str(error)
            raise ValidationError(detail) from error
        count = self.get_queryset().get(pk=count.pk)
        return Response(self.get_serializer(count).data, status=201)

    @action(detail=True, methods=["post"], url_path=r"lines/(?P<line_id>[^/.]+)/record")
    def record_line(self, request, pk=None, line_id=None):
        if not self.get_queryset().filter(pk=pk, lines__pk=line_id).exists():
            raise ValidationError({"line": "La línea no pertenece a este conteo."})
        serializer = InventoryCountQuantitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            record_inventory_count(
                line_id, serializer.validated_data.get("counted_quantity"), request.user,
                serial_numbers=serializer.validated_data.get("counted_serial_numbers"),
            )
        except DjangoValidationError as error:
            raise ValidationError(error.message_dict if hasattr(error, "message_dict") else error.messages) from error
        count = self.get_queryset().get(pk=pk)
        return Response(self.get_serializer(count).data)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        try:
            submit_inventory_count(pk, request.user)
        except DjangoValidationError as error:
            raise ValidationError(error.message_dict if hasattr(error, "message_dict") else error.messages) from error
        count = self.get_queryset().get(pk=pk)
        return Response(self.get_serializer(count).data)

    @action(detail=True, methods=["post"])
    def apply(self, request, pk=None):
        try:
            apply_inventory_count(pk, request.user)
        except DjangoValidationError as error:
            raise ValidationError(error.message_dict if hasattr(error, "message_dict") else error.messages) from error
        count = self.get_queryset().get(pk=pk)
        return Response(self.get_serializer(count).data)
