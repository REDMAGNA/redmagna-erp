from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Case, Count, DecimalField, F, Sum, Value, When
from django.utils import timezone

from sales.models import WorkOrder, WorkOrderMaterialRequirement

from .models import StockMovement, StockReservation, StockUnit
from purchasing.models import PurchaseOrderLine


ZERO = Decimal("0.000")
ACTIVE_WORK_STATUSES = [WorkOrder.Status.PLANNED, WorkOrder.Status.IN_PROGRESS, WorkOrder.Status.BLOCKED]


def _money(value):
    return str(value.quantize(Decimal("0.001")))


def build_replenishment_forecast(rule, horizon_days):
    """Build a dated, deliberately bounded stock forecast from recorded dates."""
    today = timezone.localdate()
    horizon_end = today + timedelta(days=horizon_days)
    product, location = rule.product, rule.location
    reserved_quantity = getattr(rule, "current_reserved", None)
    if reserved_quantity is None:
        reserved_quantity = StockReservation.objects.filter(
            product=product, location=location, state=StockReservation.State.ACTIVE,
        ).aggregate(total=Sum("remaining_quantity"))["total"] or ZERO
        reserved_quantity += Decimal(StockUnit.objects.filter(
            product=product, location=location, state=StockUnit.State.RESERVED,
        ).count())
    pairs = defaultdict(lambda: {"inbound": ZERO, "demand": ZERO, "events": []})
    unknown_incoming = ZERO
    undestined_incoming = ZERO
    unknown_demand = ZERO
    undated_orders = []
    undestined_orders = []
    undated_work_orders = []

    purchase_lines = PurchaseOrderLine.objects.filter(
        product=product,
        purchase_order__status__in=["ordered", "partial"],
    ).filter(received_quantity__lt=F("quantity")).select_related("purchase_order__supplier")
    for line in purchase_lines:
        amount = line.quantity - line.received_quantity
        order = line.purchase_order
        if line.expected_location_id is None:
            undestined_incoming += amount
            undestined_orders.append(order.number)
            continue
        if line.expected_location_id != location.pk:
            continue
        if not order.expected_date:
            unknown_incoming += amount
            undated_orders.append(order.number)
            continue
        due_date = order.expected_date
        forecast_date = max(due_date, today)
        if forecast_date <= horizon_end:
            pairs[forecast_date]["inbound"] += amount
            pairs[forecast_date]["events"].append({
                "kind": "incoming", "quantity": _money(amount), "reference": order.number,
                "party": order.supplier.name, "original_date": due_date.isoformat(),
                "overdue": due_date < today,
            })

    requirements = WorkOrderMaterialRequirement.objects.filter(
        product=product, supply_location=location, work_order__status__in=ACTIVE_WORK_STATUSES,
    ).values(
        "work_order_id", "work_order__scheduled_start", "work_order__sales_order__quote__number",
    ).annotate(required=Sum("required_quantity"))
    work = {item["work_order_id"]: item for item in requirements}
    work_ids = list(work)
    net_issued = dict(StockMovement.objects.filter(
        product=product, location=location, work_order_id__in=work_ids,
        kind__in=[StockMovement.Kind.ISSUE, StockMovement.Kind.RETURN],
    ).values("work_order_id").annotate(total=Sum(Case(
        When(kind=StockMovement.Kind.ISSUE, then=F("quantity")),
        When(kind=StockMovement.Kind.RETURN, then=-F("quantity")),
        default=Value(ZERO), output_field=DecimalField(max_digits=14, decimal_places=3),
    ))).values_list("work_order_id", "total")) if work_ids else {}
    reserved_qty = dict(StockReservation.objects.filter(
        product=product, location=location, state=StockReservation.State.ACTIVE, work_order_id__in=work_ids,
    ).values("work_order_id").annotate(total=Sum("remaining_quantity")).values_list("work_order_id", "total")) if work_ids else {}
    reserved_serial = dict(StockUnit.objects.filter(
        product=product, location=location, state=StockUnit.State.RESERVED, work_order_id__in=work_ids,
    ).values("work_order_id").annotate(total=Count("id")).values_list("work_order_id", "total")) if work_ids else {}

    for work_order_id, item in work.items():
        remaining = max(
            ZERO,
            item["required"] - net_issued.get(work_order_id, ZERO)
            - reserved_qty.get(work_order_id, ZERO)
            - Decimal(reserved_serial.get(work_order_id, 0)),
        )
        if remaining <= 0:
            continue
        number = item["work_order__sales_order__quote__number"]
        scheduled = item["work_order__scheduled_start"]
        if not scheduled:
            unknown_demand += remaining
            undated_work_orders.append(number)
            continue
        due_date = timezone.localtime(scheduled).date() if timezone.is_aware(scheduled) else scheduled.date()
        forecast_date = max(due_date, today)
        if forecast_date <= horizon_end:
            pairs[forecast_date]["demand"] += remaining
            pairs[forecast_date]["events"].append({
                "kind": "demand", "quantity": _money(remaining), "reference": number,
                "party": "Orden de trabajo", "original_date": due_date.isoformat(),
                "overdue": due_date < today,
            })

    on_hand_quantity = Decimal(str(rule.on_hand_quantity or ZERO))
    balance = on_hand_quantity - reserved_quantity
    opening_available = balance
    rows = []
    minimum_quantity = rule.minimum_quantity
    projected_values = [balance]
    for day_offset in range(horizon_days + 1):
        day = today + timedelta(days=day_offset)
        batch = pairs.get(day, {"inbound": ZERO, "demand": ZERO, "events": []})
        balance += batch["inbound"] - batch["demand"]
        projected_values.append(balance)
        rows.append({
            "date": day.isoformat(),
            "incoming": _money(batch["inbound"]),
            "demand": _money(batch["demand"]),
            "projected_quantity": _money(balance),
            "below_minimum": balance < minimum_quantity,
            "events": sorted(batch["events"], key=lambda event: (event["kind"], event["reference"])),
        })

    first_breach = today.isoformat() if opening_available < minimum_quantity else next(
        (row["date"] for row in rows if row["below_minimum"]), None,
    )
    minimum_projected = min(projected_values)
    return {
        "rule": str(rule.pk),
        "product_sku": product.sku,
        "product_name": product.name,
        "location_code": location.code,
        "as_of": today.isoformat(),
        "horizon_days": horizon_days,
        "horizon_end": horizon_end.isoformat(),
        "minimum_quantity": _money(rule.minimum_quantity),
        "target_quantity": _money(rule.target_quantity),
        "on_hand_quantity": _money(on_hand_quantity),
        "reserved_quantity": _money(reserved_quantity),
        "opening_available": _money(opening_available),
        "unknown_incoming": _money(unknown_incoming),
        "undestined_incoming": _money(undestined_incoming),
        "unknown_demand": _money(unknown_demand),
        "undated_purchase_orders": sorted(set(undated_orders)),
        "undestined_purchase_orders": sorted(set(undestined_orders)),
        "undated_work_orders": sorted(set(undated_work_orders)),
        "first_breach_date": first_breach,
        "minimum_projected_quantity": _money(minimum_projected),
        "suggested_quantity": _money(max(ZERO, rule.target_quantity - minimum_projected)),
        "rows": rows,
    }
