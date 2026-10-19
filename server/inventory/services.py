import hashlib
import json
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models import Case, Count, DecimalField, F, Q, Sum, Value, When
from django.utils import timezone

from sales.models import WorkOrder, WorkOrderMaterialRequirement

from .models import InventoryCount, InventoryCountLine, Product, StockBalance, StockLocation, StockMovement, StockReservation, StockReservationEvent, StockTransfer, StockTransferLine, StockUnit, StockUnitEvent


INBOUND_KINDS = {StockMovement.Kind.RECEIPT, StockMovement.Kind.RETURN, StockMovement.Kind.ADJUSTMENT_IN}
OUTBOUND_KINDS = {StockMovement.Kind.ISSUE, StockMovement.Kind.ADJUSTMENT_OUT}


@transaction.atomic
def create_inventory_count(location, product_ids, reason, actor):
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "Describe el motivo del conteo físico."})
    products = list(Product.objects.select_for_update().filter(pk__in=set(product_ids), is_active=True, kind=Product.Kind.STOCKABLE).order_by("pk"))
    if not products or len(products) != len(set(product_ids)):
        raise ValidationError({"products": "Selecciona productos activos con existencias, controlados por cantidad o serie, sin repetirlos."})
    location = StockLocation.objects.select_for_update().get(pk=location.pk, is_active=True)
    count = InventoryCount.objects.create(location=location, reason=reason, created_by=actor)
    serial_products = [product for product in products if product.tracking_policy == Product.TrackingPolicy.SERIAL]
    serials_by_product = {product.pk: [] for product in serial_products}
    for unit in StockUnit.objects.select_for_update().filter(
        product__in=serial_products, location=location,
        state__in=[StockUnit.State.IN_STOCK, StockUnit.State.RESERVED],
    ).order_by("product_id", "serial_number"):
        serials_by_product[unit.product_id].append({
            "id": str(unit.pk), "serial_number": unit.serial_number, "state": unit.state,
            "work_order_id": str(unit.work_order_id) if unit.work_order_id else "",
            "updated_at": unit.updated_at.isoformat(),
        })
    balances = {balance.product_id: balance for balance in StockBalance.objects.select_for_update().filter(location=location, product__in=products)}
    for product in serial_products:
        quantity = balances[product.pk].quantity if product.pk in balances else Decimal("0.000")
        if quantity != Decimal(len(serials_by_product[product.pk])):
            raise ValidationError({"serial_balance": f"El saldo y las series físicas registradas de {product.sku} no coinciden; corrige la trazabilidad antes de contar."})
    InventoryCountLine.objects.bulk_create([
        InventoryCountLine(count=count, product=product,
            expected_quantity=balances[product.pk].quantity if product.pk in balances else Decimal("0.000"),
            balance_updated_at=balances[product.pk].updated_at if product.pk in balances else None,
            expected_serials=serials_by_product.get(product.pk, []))
        for product in products
    ])
    return count


@transaction.atomic
def record_inventory_count(line_id, quantity, actor, serial_numbers=None):
    count_id = InventoryCountLine.objects.only("count_id").get(pk=line_id).count_id
    count = InventoryCount.objects.select_for_update().get(pk=count_id)
    line = InventoryCountLine.objects.select_for_update().get(pk=line_id)
    if count.state != InventoryCount.State.DRAFT:
        raise ValidationError("Solo se pueden capturar cantidades mientras el conteo está en captura.")
    if line.product.tracking_policy == Product.TrackingPolicy.SERIAL:
        if quantity is not None:
            raise ValidationError({"counted_quantity": "Este producto se controla por serie; captura la lista de series observadas."})
        serial_numbers = [str(serial).strip() for serial in (serial_numbers or [])]
        if any(not serial for serial in serial_numbers) or len(serial_numbers) != len(set(serial_numbers)):
            raise ValidationError({"counted_serial_numbers": "Las series deben estar completas y no repetirse."})
        line.counted_serials = serial_numbers
        line.counted_quantity = Decimal(len(serial_numbers))
    elif serial_numbers is not None:
        raise ValidationError({"counted_serial_numbers": "Este producto se controla por cantidad; captura un número."})
    elif quantity is not None and quantity < 0:
        raise ValidationError({"counted_quantity": "El conteo físico no puede ser negativo."})
    else:
        line.counted_quantity = quantity
    line.counted_by = actor
    line.counted_at = timezone.now()
    line.save(update_fields=["counted_quantity", "counted_serials", "counted_by", "counted_at"])
    return line


@transaction.atomic
def submit_inventory_count(count_id, actor):
    count = InventoryCount.objects.select_for_update().get(pk=count_id)
    if count.state != InventoryCount.State.DRAFT:
        raise ValidationError("El conteo ya no está en captura.")
    if not count.lines.exists() or count.lines.filter(counted_quantity__isnull=True).exists():
        raise ValidationError("Captura la cantidad de todas las líneas antes de enviar a revisión.")
    count.state = InventoryCount.State.SUBMITTED
    count.submitted_at = timezone.now()
    count.save(update_fields=["state", "submitted_at"])
    return count


@transaction.atomic
def apply_inventory_count(count_id, actor):
    count = InventoryCount.objects.select_for_update().select_related("location", "created_by").get(pk=count_id)
    if count.state != InventoryCount.State.SUBMITTED:
        raise ValidationError("Solo se puede aplicar un conteo pendiente de revisión.")
    if count.created_by_id == actor.pk:
        raise ValidationError("Una persona distinta de quien capturó el conteo debe revisarlo y aplicarlo.")
    lines = list(count.lines.select_for_update().select_related("product").order_by("product_id"))
    products = list(Product.objects.select_for_update().filter(pk__in=[line.product_id for line in lines]).order_by("pk"))
    if len(products) != len(lines):
        raise ValidationError("El conteo contiene productos que ya no están disponibles.")
    if any(not product.is_active or product.kind != Product.Kind.STOCKABLE or product.tracking_policy not in Product.TrackingPolicy.values for product in products):
        raise ValidationError("El conteo contiene un producto inactivo o con seguimiento no reconocido.")
    location = StockLocation.objects.select_for_update().get(pk=count.location_id, is_active=True)
    serial_product_ids = [product.pk for product in products if product.tracking_policy == Product.TrackingPolicy.SERIAL]
    current_serials_by_product = {product_id: [] for product_id in serial_product_ids}
    for unit in StockUnit.objects.select_for_update().filter(
        product_id__in=serial_product_ids, location=location,
        state__in=[StockUnit.State.IN_STOCK, StockUnit.State.RESERVED],
    ).order_by("product_id", "serial_number").values("id", "product_id", "serial_number", "state", "work_order_id", "updated_at"):
        current_serials_by_product[unit["product_id"]].append({
            "id": str(unit["id"]), "serial_number": unit["serial_number"], "state": unit["state"],
            "work_order_id": str(unit["work_order_id"]) if unit["work_order_id"] else "",
            "updated_at": unit["updated_at"].isoformat(),
        })
    balance_map = {balance.product_id: balance for balance in StockBalance.objects.select_for_update().filter(location=count.location, product_id__in=[line.product_id for line in lines]).order_by("product_id")}
    for line in lines:
        balance = balance_map.get(line.product_id)
        current_quantity = balance.quantity if balance else Decimal("0.000")
        current_updated_at = balance.updated_at if balance else None
        if line.counted_quantity is None:
            raise ValidationError("El conteo contiene líneas sin cantidad capturada.")
        if current_quantity != line.expected_quantity or current_updated_at != line.balance_updated_at:
            raise ValidationError({"stale_count": f"El saldo de {line.product.sku} cambió desde que inició el conteo. Inicia un conteo nuevo."})
        if line.product.tracking_policy == Product.TrackingPolicy.SERIAL:
            current_snapshot = current_serials_by_product[line.product_id]
            if current_snapshot != line.expected_serials:
                raise ValidationError({"stale_count": f"Las series de {line.product.sku} cambiaron desde el inicio. Inicia un conteo nuevo."})
            if line.counted_serials is None:
                raise ValidationError({"counted_serial_numbers": f"Captura todas las series de {line.product.sku}."})
        elif line.counted_quantity is None:
            raise ValidationError({"counted_quantity": f"Captura la cantidad de {line.product.sku}."})
    for line in lines:
        note = f"Conteo físico {count.pk}: {count.reason}"[:240]
        reference = f"Conteo {count.pk}"
        if line.product.tracking_policy == Product.TrackingPolicy.SERIAL:
            expected = {item["serial_number"] for item in line.expected_serials}
            counted = set(line.counted_serials)
            missing = sorted(expected - counted)
            added = sorted(counted - expected)
            missing_reserved = {item["serial_number"] for item in line.expected_serials if item["state"] == StockUnit.State.RESERVED} & set(missing)
            if missing_reserved:
                raise ValidationError({"reserved_serials": f"Libera o revisa las series reservadas antes de ajustar: {', '.join(missing_reserved)}."})
            if missing:
                result = post_stock_movement(
                    kind=StockMovement.Kind.ADJUSTMENT_OUT, product=line.product, location=count.location,
                    quantity=Decimal(len(missing)), actor=actor, serial_numbers=missing, note=note,
                    reference=reference, idempotency_key=line.adjustment_out_key,
                )
                line.adjustment_out_movement = result[0] if isinstance(result, tuple) else result
            if added:
                result = post_stock_movement(
                    kind=StockMovement.Kind.ADJUSTMENT_IN, product=line.product, location=count.location,
                    quantity=Decimal(len(added)), actor=actor, serial_numbers=added, note=note,
                    reference=reference, idempotency_key=line.adjustment_in_key,
                )
                line.adjustment_in_movement = result[0] if isinstance(result, tuple) else result
            line.save(update_fields=["adjustment_out_movement", "adjustment_in_movement"])
            continue
        difference = line.counted_quantity - line.expected_quantity
        if difference != 0:
            result = post_stock_movement(
                kind=StockMovement.Kind.ADJUSTMENT_IN if difference > 0 else StockMovement.Kind.ADJUSTMENT_OUT,
                product=line.product, location=count.location, quantity=abs(difference), actor=actor,
                note=note, reference=reference, idempotency_key=line.idempotency_key,
            )
            line.movement = result[0] if isinstance(result, tuple) else result
            line.save(update_fields=["movement"])
    count.state = InventoryCount.State.APPLIED
    count.reviewed_by = actor
    count.applied_at = timezone.now()
    count.save(update_fields=["state", "reviewed_by", "applied_at"])
    return count


def _remaining_work_order_demand(work_order, product, location):
    required = WorkOrderMaterialRequirement.objects.filter(
        work_order=work_order, product=product, supply_location=location,
    ).aggregate(total=Sum("required_quantity"))["total"] or Decimal("0.000")
    if required <= 0:
        return Decimal("0.000")
    net_issued = StockMovement.objects.filter(
        work_order=work_order, product=product, location=location,
        kind__in=[StockMovement.Kind.ISSUE, StockMovement.Kind.RETURN],
    ).aggregate(total=Sum(Case(
        When(kind=StockMovement.Kind.ISSUE, then=F("quantity")),
        When(kind=StockMovement.Kind.RETURN, then=-F("quantity")),
        default=Value(Decimal("0.000")), output_field=DecimalField(max_digits=14, decimal_places=3),
    )))["total"] or Decimal("0.000")
    return max(Decimal("0.000"), required - net_issued)


def _reserved_quantity(product, location, exclude_work_order=None):
    reservations = StockReservation.objects.filter(state=StockReservation.State.ACTIVE, product=product, location=location)
    if exclude_work_order:
        reservations = reservations.exclude(work_order=exclude_work_order)
    return reservations.aggregate(total=Sum("remaining_quantity"))["total"] or Decimal("0.000")


def unreserved_work_order_demand(product_id, location_id):
    """Open material demand assigned to one location, net of issues and reservations there."""
    active_statuses = [WorkOrder.Status.PLANNED, WorkOrder.Status.IN_PROGRESS, WorkOrder.Status.BLOCKED]
    demand = dict(WorkOrderMaterialRequirement.objects.filter(
        product_id=product_id, supply_location_id=location_id, work_order__status__in=active_statuses,
    ).values("work_order_id").annotate(total=Sum("required_quantity")).values_list("work_order_id", "total"))
    net_issued = dict(StockMovement.objects.filter(
        product_id=product_id, location_id=location_id, work_order__status__in=active_statuses,
        kind__in=[StockMovement.Kind.ISSUE, StockMovement.Kind.RETURN],
    ).values("work_order_id").annotate(total=Sum(Case(
        When(kind=StockMovement.Kind.ISSUE, then=F("quantity")),
        When(kind=StockMovement.Kind.RETURN, then=-F("quantity")),
        default=Value(Decimal("0.000")), output_field=DecimalField(max_digits=14, decimal_places=3),
    ))).values_list("work_order_id", "total"))
    reserved = dict(StockReservation.objects.filter(
        product_id=product_id, location_id=location_id, state=StockReservation.State.ACTIVE,
        work_order__status__in=active_statuses,
    ).values("work_order_id").annotate(total=Sum("remaining_quantity")).values_list("work_order_id", "total"))
    reserved_serials = dict(StockUnit.objects.filter(
        product_id=product_id, location_id=location_id, state=StockUnit.State.RESERVED,
        work_order__status__in=active_statuses,
    ).values("work_order_id").annotate(total=Count("id")).values_list("work_order_id", "total"))
    return sum(
        (max(Decimal("0.000"), required - net_issued.get(work_order_id, Decimal("0.000"))
             - reserved.get(work_order_id, Decimal("0.000")) - Decimal(reserved_serials.get(work_order_id, 0)))
         for work_order_id, required in demand.items()),
        Decimal("0.000"),
    )


@transaction.atomic
def reserve_stock(work_order, product, location, quantity, idempotency_key, actor):
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [idempotency_key.int & ((1 << 63) - 1)])
    existing = StockReservation.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        if (existing.work_order_id != work_order.pk or existing.product_id != product.pk or existing.location_id != location.pk or existing.quantity != quantity):
            raise ValidationError("La clave de esta reserva ya se usó con otros datos.")
        return existing

    product = Product.objects.select_for_update().get(pk=product.pk)
    work_order = WorkOrder.objects.select_for_update().get(pk=work_order.pk)
    location = StockLocation.objects.select_for_update().get(pk=location.pk)
    if work_order.status not in {WorkOrder.Status.PLANNED, WorkOrder.Status.IN_PROGRESS}:
        raise ValidationError("Solo se pueden reservar materiales para una orden programada o en curso.")
    if not product.is_active or product.kind != Product.Kind.STOCKABLE or product.tracking_policy != Product.TrackingPolicy.QUANTITY:
        raise ValidationError("Selecciona un producto activo con existencias y seguimiento por cantidad.")
    if not location.is_active:
        raise ValidationError("La ubicación debe estar activa.")
    if quantity <= 0:
        raise ValidationError("La cantidad a reservar debe ser mayor que cero.")
    if StockReservation.objects.filter(work_order=work_order, product=product, location=location, state=StockReservation.State.ACTIVE).exists():
        raise ValidationError("Esta orden ya tiene una reserva activa para el producto en esa ubicación; libera la reserva previa antes de crear otra.")

    demand = _remaining_work_order_demand(work_order, product, location)
    reserved_for_order = StockReservation.objects.filter(
        work_order=work_order, product=product, location=location, state=StockReservation.State.ACTIVE,
    ).aggregate(total=Sum("remaining_quantity"))["total"] or Decimal("0.000")
    if demand <= reserved_for_order or quantity > demand - reserved_for_order:
        raise ValidationError(
            f"La orden tiene {demand} unidades aprobadas pendientes para {product.sku} en {location.code}, "
            f"de las que ya tiene {reserved_for_order} reservadas; no se pueden reservar {quantity}."
        )

    StockBalance.objects.get_or_create(product=product, location=location, defaults={"quantity": Decimal("0.000")})
    balance = StockBalance.objects.select_for_update().get(product=product, location=location)
    available = balance.quantity - _reserved_quantity(product, location)
    if quantity > available:
        raise ValidationError(f"Existencia disponible para reservar de {product.sku} en {location.code}: {available}; solicitada: {quantity}.")
    reservation = StockReservation.objects.create(
        work_order=work_order, product=product, location=location, quantity=quantity,
        remaining_quantity=quantity, idempotency_key=idempotency_key, created_by=actor,
    )
    StockReservationEvent.objects.create(
        reservation=reservation, action=StockReservationEvent.Action.RESERVED,
        quantity=quantity, remaining_after=quantity, created_by=actor,
    )
    return reservation


@transaction.atomic
def release_stock_reservation(reservation_id, actor):
    product_id = StockReservation.objects.only("product_id").get(pk=reservation_id).product_id
    Product.objects.select_for_update().get(pk=product_id)
    reservation = StockReservation.objects.select_for_update().select_related("work_order", "product", "location").get(pk=reservation_id)
    if reservation.state != StockReservation.State.ACTIVE:
        raise ValidationError("Solo se puede liberar una reserva activa.")
    released = reservation.remaining_quantity
    reservation.remaining_quantity = Decimal("0.000")
    reservation.state = StockReservation.State.RELEASED
    reservation.save(update_fields=["remaining_quantity", "state", "updated_at"])
    StockReservationEvent.objects.create(
        reservation=reservation, action=StockReservationEvent.Action.RELEASED,
        quantity=released, remaining_after=Decimal("0.000"), created_by=actor,
    )
    return reservation


def _normalized_serials(serial_numbers):
    serials = [value.strip() for value in (serial_numbers or [])]
    if any(not value for value in serials) or len(serials) != len(set(serials)):
        raise ValidationError("Los números de serie deben estar completos y no repetirse.")
    return serials


def _validate_serial_count(product, quantity, serial_numbers):
    serials = _normalized_serials(serial_numbers)
    if product.tracking_policy == Product.TrackingPolicy.QUANTITY:
        if serials:
            raise ValidationError("Este producto se controla por cantidad y no debe incluir números de serie.")
        return serials
    if quantity != quantity.to_integral_value() or len(serials) != int(quantity):
        raise ValidationError("Captura un número de serie distinto por cada unidad; la cantidad debe ser entera.")
    return serials


def _record_unit_event(unit, movement, actor, state_before, from_location, to_location, work_order=None):
    StockUnitEvent.objects.create(
        unit=unit, movement=movement, state_before=state_before, state_after=unit.state,
        from_location=from_location, to_location=to_location, work_order=work_order, created_by=actor,
    )


@transaction.atomic
def post_stock_movement(kind, product, quantity, actor, location=None, work_order=None, reference="", note="", serial_numbers=None, idempotency_key=None):
    if kind not in INBOUND_KINDS | OUTBOUND_KINDS:
        raise ValidationError("Tipo de movimiento de inventario no reconocido.")
    if quantity <= 0:
        raise ValidationError("La cantidad debe ser mayor que cero.")
    reference = (reference or "").strip()
    note = (note or "").strip()
    if kind == StockMovement.Kind.RECEIPT and not reference.strip():
        raise ValidationError("Indica la orden, remisión o referencia que origina la entrada al almacén.")
    if kind in {StockMovement.Kind.RETURN, StockMovement.Kind.ADJUSTMENT_IN, StockMovement.Kind.ADJUSTMENT_OUT} and not note.strip():
        raise ValidationError("Indica el motivo de la devolución o del ajuste para conservar la bitácora.")

    serials = _normalized_serials(serial_numbers)
    effective_location_id = location.pk if location else StockLocation.objects.only("pk").get(code="MAIN", is_active=True).pk
    fingerprint = ""
    if idempotency_key:
        request_data = {
            "kind": kind,
            "product": str(product.pk),
            "location": str(effective_location_id),
            "work_order": str(work_order.pk) if work_order else "",
            "quantity": str(Decimal(quantity).quantize(Decimal("0.001"))),
            "serial_numbers": sorted(serials),
            "reference": reference,
            "note": note,
            "actor": str(actor.pk),
        }
        fingerprint = hashlib.sha256(json.dumps(request_data, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [idempotency_key.int & ((1 << 63) - 1)])
        existing = StockMovement.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            if existing.request_fingerprint != fingerprint:
                raise ValidationError("La clave del movimiento ya se usó con otros datos.")
            return existing, False

    product = Product.objects.select_for_update().get(pk=product.pk)
    if not product.is_active:
        raise ValidationError("No se pueden mover existencias de un producto inactivo.")
    if product.kind != Product.Kind.STOCKABLE:
        raise ValidationError("Los servicios no tienen movimientos de inventario.")
    serials = _validate_serial_count(product, quantity, serials)

    if kind in {StockMovement.Kind.ISSUE, StockMovement.Kind.RETURN}:
        if work_order is None:
            raise ValidationError("Este movimiento debe ligarse a una orden de trabajo.")
        work_order = WorkOrder.objects.select_for_update().get(pk=work_order.pk)
        if kind == StockMovement.Kind.ISSUE and work_order.status not in {WorkOrder.Status.PLANNED, WorkOrder.Status.IN_PROGRESS}:
            raise ValidationError("Solo se puede entregar material a una orden programada o en curso.")
        if kind == StockMovement.Kind.RETURN:
            issued = StockMovement.objects.filter(work_order=work_order, product=product, kind=StockMovement.Kind.ISSUE).aggregate(total=Sum("quantity"))["total"] or Decimal("0.000")
            returned = StockMovement.objects.filter(work_order=work_order, product=product, kind=StockMovement.Kind.RETURN).aggregate(total=Sum("quantity"))["total"] or Decimal("0.000")
            if quantity > issued - returned:
                raise ValidationError("La devolución no puede superar la cantidad entregada a esta orden.")
            if work_order.status == WorkOrder.Status.CANCELLED:
                raise ValidationError("No se pueden devolver materiales a una orden cancelada; solicita un ajuste administrativo.")
    elif work_order is not None:
        raise ValidationError("Entradas y ajustes no se ligan directamente a una orden de trabajo.")

    if location is None:
        location = StockLocation.objects.select_for_update().get(code="MAIN", is_active=True)
    else:
        location = StockLocation.objects.select_for_update().get(pk=location.pk)
    if not location.is_active:
        raise ValidationError("La ubicación de inventario está inactiva.")

    units = []
    inbound_new_units = kind in {StockMovement.Kind.RECEIPT, StockMovement.Kind.ADJUSTMENT_IN}
    if product.tracking_policy == Product.TrackingPolicy.SERIAL:
        if inbound_new_units:
            if StockUnit.objects.filter(product=product, serial_number__in=serials).exists():
                raise ValidationError("Uno o más números de serie ya están registrados para este producto.")
        elif kind == StockMovement.Kind.RETURN:
            units = list(StockUnit.objects.select_for_update().filter(
                product=product, serial_number__in=serials, state=StockUnit.State.ASSIGNED, work_order=work_order,
            ).order_by("serial_number"))
            if len(units) != len(serials):
                raise ValidationError("Todos los números deben estar asignados a la orden seleccionada para devolverlos.")
        else:
            units = list(StockUnit.objects.select_for_update().filter(product=product, serial_number__in=serials, location=location)
                .filter(Q(state=StockUnit.State.IN_STOCK) | Q(state=StockUnit.State.RESERVED, work_order=work_order))
                .order_by("serial_number"))
            if len(units) != len(serials):
                raise ValidationError("Las series deben estar libres o reservadas para esta misma orden en la ubicación seleccionada.")

    if not reference:
        reference = work_order.sales_order.quote.number if work_order else ""
    if kind in {StockMovement.Kind.ISSUE, StockMovement.Kind.RETURN} and work_order:
        reference = f"{reference} · {work_order.sales_order.quote.number}".strip(" ·") if reference != work_order.sales_order.quote.number else reference

    if kind == StockMovement.Kind.ISSUE:
        demand = _remaining_work_order_demand(work_order, product, location)
        if demand <= 0:
            raise ValidationError("Esta orden no tiene requerimiento aprobado pendiente para ese producto y ubicación.")
        if product.tracking_policy == Product.TrackingPolicy.SERIAL and demand != demand.to_integral_value():
            raise ValidationError("La cantidad aprobada pendiente del equipo serializado debe ser entera.")
        if quantity > demand:
            raise ValidationError(f"La orden tiene {demand} unidades aprobadas pendientes de surtir; solicitadas: {quantity}.")

    StockBalance.objects.get_or_create(product=product, location=location, defaults={"quantity": Decimal("0.000")})
    balance = StockBalance.objects.select_for_update().get(product=product, location=location)
    reservation = None
    reservation_issue_quantity = Decimal("0.000")
    if kind == StockMovement.Kind.ISSUE:
        reservation = StockReservation.objects.select_for_update().filter(
            work_order=work_order, product=product, location=location, state=StockReservation.State.ACTIVE,
        ).first()
        own_remaining = reservation.remaining_quantity if reservation else Decimal("0.000")
        available = balance.quantity - _reserved_quantity(product, location) + own_remaining
        if quantity > available:
            raise ValidationError(f"Existencia disponible para la orden {work_order.sales_order.quote.number} de {product.sku}: {available}; solicitada: {quantity}. Las demás reservas se conservan.")
        reservation_issue_quantity = min(quantity, own_remaining)
    elif kind == StockMovement.Kind.ADJUSTMENT_OUT:
        available = balance.quantity - _reserved_quantity(product, location)
        if quantity > available:
            raise ValidationError(f"No se puede ajustar: {available} unidades están libres; las reservas activas deben conservarse.")
    new_quantity = balance.quantity + quantity if kind in INBOUND_KINDS else balance.quantity - quantity
    if new_quantity < 0:
        raise ValidationError(f"Existencia insuficiente de {product.sku}: disponible {balance.quantity}, solicitado {quantity}.")

    movement = StockMovement.objects.create(
        kind=kind,
        product=product,
        location=location,
        work_order=work_order,
        reservation=reservation if reservation_issue_quantity else None,
        quantity=quantity,
        reference=reference[:120],
        note=note[:240],
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
        created_by=actor,
    )
    balance.quantity = new_quantity
    balance.save(update_fields=["quantity", "updated_at"])
    if reservation_issue_quantity and reservation:
        reservation.remaining_quantity -= reservation_issue_quantity
        if reservation.remaining_quantity == 0:
            reservation.state = StockReservation.State.FULFILLED
        reservation.save(update_fields=["remaining_quantity", "state", "updated_at"])
        StockReservationEvent.objects.create(
            reservation=reservation, movement=movement, action=StockReservationEvent.Action.ISSUED,
            quantity=reservation_issue_quantity, remaining_after=reservation.remaining_quantity, created_by=actor,
        )
    if product.tracking_policy == Product.TrackingPolicy.SERIAL:
        if inbound_new_units:
            units = [StockUnit.objects.create(product=product, serial_number=serial, location=location) for serial in serials]
            for unit in units:
                _record_unit_event(unit, movement, actor, "", None, location)
        else:
            for unit in units:
                state_before, location_before = unit.state, unit.location
                if kind == StockMovement.Kind.ISSUE:
                    unit.state, unit.location, unit.work_order = StockUnit.State.ASSIGNED, None, work_order
                elif kind == StockMovement.Kind.RETURN:
                    unit.state, unit.location, unit.work_order = StockUnit.State.IN_STOCK, location, None
                elif kind == StockMovement.Kind.ADJUSTMENT_OUT:
                    unit.state, unit.location, unit.work_order = StockUnit.State.RETIRED, None, None
                unit.save(update_fields=["state", "location", "work_order", "updated_at"])
                _record_unit_event(unit, movement, actor, state_before, location_before, unit.location, work_order)
    return (movement, True) if idempotency_key else movement


@transaction.atomic
def reserve_stock_unit(unit_id, work_order, actor):
    unit_ref = StockUnit.objects.only("product_id").get(pk=unit_id)
    product = Product.objects.select_for_update().get(pk=unit_ref.product_id)
    work_order = WorkOrder.objects.select_for_update().get(pk=work_order.pk)
    unit = StockUnit.objects.select_for_update().select_related("product", "location").get(pk=unit_id)
    if not product.is_active or product.kind != Product.Kind.STOCKABLE or product.tracking_policy != Product.TrackingPolicy.SERIAL:
        raise ValidationError("Solo se pueden reservar equipos activos con seguimiento por número de serie.")
    if work_order.status not in {WorkOrder.Status.PLANNED, WorkOrder.Status.IN_PROGRESS}:
        raise ValidationError("Solo se puede reservar un equipo para una orden programada o en curso.")
    if unit.state == StockUnit.State.RESERVED and unit.work_order_id == work_order.pk:
        return unit
    if unit.state != StockUnit.State.IN_STOCK or not unit.location_id:
        raise ValidationError("El equipo debe estar disponible en un almacén para reservarlo.")
    demand = _remaining_work_order_demand(work_order, product, unit.location)
    reserved_for_order = StockUnit.objects.filter(
        product=product, location=unit.location, state=StockUnit.State.RESERVED, work_order=work_order,
    ).count()
    if demand != demand.to_integral_value() or demand <= reserved_for_order:
        raise ValidationError("La orden no tiene requerimiento aprobado pendiente para reservar otra unidad de este equipo en esa ubicación.")
    previous_state, location = unit.state, unit.location
    unit.state = StockUnit.State.RESERVED
    unit.work_order = work_order
    unit.save(update_fields=["state", "work_order", "updated_at"])
    StockUnitEvent.objects.create(
        unit=unit, movement=None, action=StockUnitEvent.Action.RESERVED,
        state_before=previous_state, state_after=unit.state, from_location=location,
        to_location=location, work_order=work_order, created_by=actor,
    )
    return unit


@transaction.atomic
def release_stock_unit_reservation(unit_id, actor):
    unit = StockUnit.objects.select_for_update().select_related("location", "work_order").get(pk=unit_id)
    if unit.state == StockUnit.State.IN_STOCK:
        last_event = unit.events.order_by("-created_at", "-id").first()
        if last_event and last_event.action == StockUnitEvent.Action.RELEASED:
            return unit
    if unit.state != StockUnit.State.RESERVED or not unit.work_order_id:
        raise ValidationError("El equipo no tiene una reserva activa para liberar.")
    previous_state, location, work_order = unit.state, unit.location, unit.work_order
    unit.state = StockUnit.State.IN_STOCK
    unit.work_order = None
    unit.save(update_fields=["state", "work_order", "updated_at"])
    StockUnitEvent.objects.create(
        unit=unit, movement=None, action=StockUnitEvent.Action.RELEASED,
        state_before=previous_state, state_after=unit.state, from_location=location,
        to_location=location, work_order=work_order, created_by=actor,
    )
    return unit


@transaction.atomic
def post_stock_transfer(source_location, destination_location, idempotency_key, lines, actor, reference="", note=""):
    reference = (reference or "").strip()
    note = (note or "").strip()
    if not note:
        raise ValidationError("Describe el motivo del traspaso para conservar la bitácora.")
    # PostgreSQL advisory lock serializes retries even when they contain different products.
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [idempotency_key.int & ((1 << 63) - 1)])

    def get_existing_transfer():
        existing = StockTransfer.objects.filter(idempotency_key=idempotency_key).prefetch_related("lines").first()
        if not existing:
            return None
        submitted = {
            str(line["product"].pk): (line["quantity"], tuple(sorted(line.get("serial_numbers", []))))
            for line in lines
        }
        recorded = {}
        for transfer_line in existing.lines.all():
            serials = StockUnitEvent.objects.filter(
                movement__transfer_line=transfer_line, movement__kind=StockMovement.Kind.TRANSFER_OUT,
            ).values_list("unit__serial_number", flat=True)
            recorded[str(transfer_line.product_id)] = (transfer_line.quantity, tuple(sorted(serials)))
        if (existing.source_location_id != source_location.pk or existing.destination_location_id != destination_location.pk
                or existing.reference != reference or existing.note != note or submitted != recorded):
            raise ValidationError("La clave de este traspaso ya se usó con otros datos.")
        return existing

    existing = get_existing_transfer()
    if existing:
        return existing

    product_ids = sorted({line["product"].pk for line in lines}, key=str)
    locked_products = {item.pk: item for item in Product.objects.select_for_update().filter(pk__in=product_ids)}
    if len(locked_products) != len(product_ids):
        raise ValidationError("Uno o más productos ya no están disponibles.")
    for product in locked_products.values():
        if not product.is_active or product.kind != Product.Kind.STOCKABLE:
            raise ValidationError(f"El producto {product.sku} no está activo para control de existencias.")

    # A repeated request waits on the product lock, then sees the committed transfer.
    existing = get_existing_transfer()
    if existing:
        return existing

    location_ids = sorted({source_location.pk, destination_location.pk}, key=str)
    locked_locations = {item.pk: item for item in StockLocation.objects.select_for_update().filter(pk__in=location_ids)}
    source = locked_locations.get(source_location.pk)
    destination = locked_locations.get(destination_location.pk)
    if not source or not destination:
        raise ValidationError("Selecciona ubicaciones de inventario vigentes.")
    if source.pk == destination.pk:
        raise ValidationError("El origen y destino deben ser distintos.")
    if not source.is_active or not destination.is_active:
        raise ValidationError("No se pueden hacer traspasos desde o hacia una ubicación inactiva.")

    balances = {}
    for product_id in product_ids:
        for location in (source, destination):
            StockBalance.objects.get_or_create(product_id=product_id, location=location, defaults={"quantity": Decimal("0.000")})
    for balance in StockBalance.objects.select_for_update().filter(product_id__in=product_ids, location_id__in=location_ids):
        balances[(balance.product_id, balance.location_id)] = balance
    for line in lines:
        product = locked_products[line["product"].pk]
        quantity = line["quantity"]
        line["serial_numbers"] = _validate_serial_count(product, quantity, line.get("serial_numbers"))
        if quantity <= 0:
            raise ValidationError("La cantidad debe ser mayor que cero.")
        available = balances[(product.pk, source.pk)].quantity
        if product.tracking_policy == Product.TrackingPolicy.QUANTITY:
            available -= _reserved_quantity(product, source)
        if quantity > available:
            raise ValidationError(f"Existencia libre insuficiente de {product.sku} en {source.code}: disponible {available} después de reservas, solicitado {quantity}.")

    transfer = StockTransfer.objects.create(
        source_location=source, destination_location=destination, idempotency_key=idempotency_key,
        reference=reference[:120], note=note[:240], created_by=actor,
    )
    for line in lines:
        product = locked_products[line["product"].pk]
        quantity = line["quantity"]
        serials = line["serial_numbers"]
        units = []
        if product.tracking_policy == Product.TrackingPolicy.SERIAL:
            units = list(StockUnit.objects.select_for_update().filter(
                product=product, serial_number__in=serials, state=StockUnit.State.IN_STOCK, location=source,
            ).order_by("serial_number"))
            if len(units) != len(serials):
                raise ValidationError(f"Todos los números de serie de {product.sku} deben estar disponibles en {source.code}.")
        transfer_line = StockTransferLine.objects.create(transfer=transfer, product=product, quantity=quantity)
        movement_out = StockMovement.objects.create(
            kind=StockMovement.Kind.TRANSFER_OUT, product=product, location=source,
            transfer_line=transfer_line, counterpart_location=destination, quantity=quantity,
            reference=transfer.reference, note=transfer.note, created_by=actor,
        )
        movement_in = StockMovement.objects.create(
            kind=StockMovement.Kind.TRANSFER_IN, product=product, location=destination,
            transfer_line=transfer_line, counterpart_location=source, quantity=quantity,
            reference=transfer.reference, note=transfer.note, created_by=actor,
        )
        source_balance = balances[(product.pk, source.pk)]
        destination_balance = balances[(product.pk, destination.pk)]
        source_balance.quantity -= quantity
        destination_balance.quantity += quantity
        source_balance.save(update_fields=["quantity", "updated_at"])
        destination_balance.save(update_fields=["quantity", "updated_at"])
        for unit in units:
            unit.location = destination
            unit.save(update_fields=["location", "updated_at"])
            _record_unit_event(unit, movement_out, actor, StockUnit.State.IN_STOCK, source, destination)
            _record_unit_event(unit, movement_in, actor, StockUnit.State.IN_STOCK, source, destination)
    return transfer


@transaction.atomic
def mark_stock_unit_installed(unit_id, actor, installed_at, warranty_until=None):
    unit = StockUnit.objects.select_for_update().select_related("product", "work_order__sales_order__quote").get(pk=unit_id)
    if unit.state == StockUnit.State.INSTALLED:
        if unit.installed_at == installed_at and unit.warranty_until == warranty_until:
            return unit
        raise ValidationError("El equipo ya tiene una instalación registrada; solicita una corrección autorizada.")
    if unit.state != StockUnit.State.ASSIGNED or not unit.work_order_id:
        raise ValidationError("Solo se puede instalar un equipo serializado entregado a una orden de trabajo.")
    work_order = WorkOrder.objects.select_for_update().select_related("sales_order__quote__customer").get(pk=unit.work_order_id)
    if work_order.status != WorkOrder.Status.DONE:
        raise ValidationError("La orden de trabajo debe estar terminada antes de registrar la instalación.")
    if installed_at > timezone.localdate():
        raise ValidationError({"installed_at": "La fecha de instalación no puede estar en el futuro."})
    if warranty_until and warranty_until < installed_at:
        raise ValidationError({"warranty_until": "La garantía no puede vencer antes de la instalación."})
    previous_state = unit.state
    unit.state = StockUnit.State.INSTALLED
    unit.customer = work_order.sales_order.quote.customer
    unit.installed_at = installed_at
    unit.warranty_until = warranty_until
    unit.save(update_fields=["state", "customer", "installed_at", "warranty_until", "updated_at"])
    StockUnitEvent.objects.create(
        unit=unit, movement=None, action=StockUnitEvent.Action.INSTALLED,
        state_before=previous_state, state_after=unit.state, work_order=work_order,
        customer=unit.customer, created_by=actor,
    )
    return unit
