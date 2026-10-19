from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone
from django.utils.html import escape

from inventory.services import post_stock_movement

from .models import PurchaseOffer, PurchaseOfferLine, PurchaseOrder, PurchaseOrderEvent, PurchaseOrderLine, PurchaseReceipt, PurchaseReceiptLine, PurchaseSourcingEvent, PurchaseSourcingLine, PurchaseSourcingRequest, Supplier, SupplierBill, SupplierBillLine, SupplierPayment, SupplierPaymentApplication


@transaction.atomic
def confirm_purchase_order(order_id, actor):
    order = PurchaseOrder.objects.select_for_update().select_related("supplier").get(pk=order_id)
    if order.status != PurchaseOrder.Status.DRAFT:
        raise ValidationError("Solo una orden en borrador puede confirmarse.")
    lines = list(order.lines.select_related("product"))
    if not lines:
        raise ValidationError("Agrega al menos un producto antes de solicitar la compra.")
    if not order.supplier.is_active or any(not line.product.is_active for line in lines):
        raise ValidationError("La orden contiene un proveedor o producto inactivo.")
    before = order.status
    order.status = PurchaseOrder.Status.ORDERED
    order.confirmed_by = actor
    order.confirmed_at = timezone.now()
    order.save(update_fields=["status", "confirmed_by", "confirmed_at", "updated_at"])
    PurchaseOrderEvent.objects.create(purchase_order=order, action="confirmed", state_before=before, state_after=order.status, actor=actor)
    return order


@transaction.atomic
def cancel_purchase_order(order_id, actor):
    order = PurchaseOrder.objects.select_for_update().get(pk=order_id)
    if order.status not in {PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.ORDERED}:
        raise ValidationError("Solo una orden en borrador o solicitada sin recepción puede cancelarse.")
    if order.lines.filter(received_quantity__gt=0).exists():
        raise ValidationError("Una orden con recepciones registradas no puede cancelarse; revisa la devolución con el proveedor.")
    before = order.status
    order.status = PurchaseOrder.Status.CANCELLED
    order.save(update_fields=["status", "updated_at"])
    PurchaseOrderEvent.objects.create(purchase_order=order, action="cancelled", state_before=before, state_after=order.status, actor=actor)
    if order.sourcing_request_id:
        refresh_sourcing_request(order.sourcing_request_id)
    return order


@transaction.atomic
def receive_purchase_order(order_id, actor, idempotency_key, lines, note=""):
    order = PurchaseOrder.objects.select_for_update().get(pk=order_id)
    canonical = {
        "note": note.strip(),
        "lines": sorted([
            {"purchase_order_line": str(item["purchase_order_line"].pk), "location": str(item["location"].pk), "quantity": str(Decimal(item["quantity"]).quantize(Decimal("0.001"))), "serial_numbers": sorted(item.get("serial_numbers", []))}
            for item in lines
        ], key=lambda item: item["purchase_order_line"]),
    }
    previous = PurchaseReceipt.objects.select_for_update().filter(idempotency_key=idempotency_key).first()
    if previous:
        if previous.purchase_order_id != order.id or previous.request_payload != canonical:
            raise ValidationError("La clave de reintento ya se usó para otra recepción.")
        return previous, False
    if order.status not in {PurchaseOrder.Status.ORDERED, PurchaseOrder.Status.PARTIAL}:
        raise ValidationError("Solo una orden solicitada y pendiente puede recibir mercancía.")
    receipt = PurchaseReceipt.objects.create(
        purchase_order=order, idempotency_key=idempotency_key, note=note.strip(),
        request_payload=canonical, received_by=actor,
    )
    for item in lines:
        order_line = PurchaseOrderLine.objects.select_for_update().select_related("product").get(pk=item["purchase_order_line"].pk, purchase_order=order)
        quantity = Decimal(item["quantity"]).quantize(Decimal("0.001"))
        if quantity <= 0 or order_line.received_quantity + quantity > order_line.quantity:
            remaining = order_line.quantity - order_line.received_quantity
            raise ValidationError(f"La recepción de {order_line.product.sku} excede lo pendiente ({remaining}).")
        expected_location_id = order_line.expected_location_id
        if expected_location_id and expected_location_id != item["location"].pk:
            raise ValidationError(f"La línea {order_line.line_number} de {order_line.product.sku} debe recibirse en la ubicación prevista.")
        if not expected_location_id:
            PurchaseOrderLine.objects.filter(pk=order_line.pk, expected_location__isnull=True).update(expected_location_id=item["location"].pk)
            order_line.expected_location_id = item["location"].pk
        movement = post_stock_movement(
            kind="receipt", product=order_line.product, quantity=quantity, actor=actor,
            location=item["location"], reference=order.number, serial_numbers=item.get("serial_numbers"),
            note=f"Recepción de compra · {order.number}"[:240],
        )
        PurchaseReceiptLine.objects.create(receipt=receipt, purchase_order_line=order_line, stock_movement=movement, quantity=quantity)
        PurchaseOrderLine.objects.filter(pk=order_line.pk).update(received_quantity=order_line.received_quantity + quantity)
    before = order.status
    remaining_exists = order.lines.filter(received_quantity__lt=F("quantity")).exists()
    order.status = PurchaseOrder.Status.PARTIAL if remaining_exists else PurchaseOrder.Status.RECEIVED
    order.save(update_fields=["status", "updated_at"])
    PurchaseOrderEvent.objects.create(purchase_order=order, action="received", state_before=before, state_after=order.status, actor=actor)
    return receipt, True


@transaction.atomic
def register_supplier_bill(order_id, actor, invoice_number, invoice_date, lines, due_date=None):
    order = PurchaseOrder.objects.select_for_update().select_related("supplier").get(pk=order_id)
    Supplier.objects.select_for_update().get(pk=order.supplier_id)
    if order.status not in {PurchaseOrder.Status.PARTIAL, PurchaseOrder.Status.RECEIVED}:
        raise ValidationError("Registra la factura después de recibir al menos parte de la mercancía.")
    normalized_number = invoice_number.strip().upper()
    if not normalized_number:
        raise ValidationError({"invoice_number": "Indica el folio de la factura del proveedor."})
    if SupplierBill.objects.filter(supplier=order.supplier, invoice_number__iexact=normalized_number).exists():
        raise ValidationError({"invoice_number": "Ese folio ya está registrado para este proveedor."})

    line_rows = []
    subtotal = tax_total = Decimal("0.00")
    for item in lines:
        order_line = PurchaseOrderLine.objects.select_for_update().get(pk=item["purchase_order_line"].pk, purchase_order=order)
        quantity = Decimal(item["quantity"]).quantize(Decimal("0.001"))
        unit_cost = Decimal(item["unit_cost"]).quantize(Decimal("0.01"))
        tax_amount = Decimal(item["tax_amount"]).quantize(Decimal("0.01"))
        invoiced = SupplierBillLine.objects.filter(purchase_order_line=order_line).aggregate(total=Sum("quantity"))["total"] or Decimal("0.000")
        if quantity <= 0 or invoiced + quantity > order_line.received_quantity:
            pending_received = order_line.received_quantity - invoiced
            raise ValidationError({"lines": f"La cantidad facturada de {order_line.product.sku} excede lo recibido pendiente ({pending_received})."})
        line_subtotal = (quantity * unit_cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        subtotal += line_subtotal
        tax_total += tax_amount
        line_rows.append((order_line, quantity, unit_cost, line_subtotal, tax_amount))
    if not line_rows:
        raise ValidationError({"lines": "Agrega al menos un concepto facturado."})
    if subtotal + tax_total <= 0:
        raise ValidationError({"lines": "El total de la factura debe ser mayor que cero."})

    bill = SupplierBill.objects.create(
        supplier=order.supplier, purchase_order=order, invoice_number=normalized_number,
        invoice_date=invoice_date, due_date=due_date, subtotal=subtotal, tax_total=tax_total,
        total=subtotal + tax_total, registered_by=actor,
    )
    for order_line, quantity, unit_cost, line_subtotal, tax_amount in line_rows:
        SupplierBillLine.objects.create(
            bill=bill, purchase_order_line=order_line, quantity=quantity,
            unit_cost=unit_cost, subtotal=line_subtotal, tax_amount=tax_amount,
        )
    from accounting.models import PostingConfiguration
    from accounting.posting import create_source_draft
    create_source_draft(
        PostingConfiguration.EventType.SUPPLIER_BILL,
        bill.id,
        actor,
        bill.invoice_date,
        f"Factura proveedor {bill.invoice_number} · {bill.supplier.name}",
        bill.total,
        base_amount=bill.subtotal,
        tax_amount=bill.tax_total,
    )
    return bill


@transaction.atomic
def post_supplier_payment(payment_id, actor):
    payment = SupplierPayment.objects.select_for_update().get(pk=payment_id)
    if payment.state == SupplierPayment.State.POSTED:
        return payment
    if payment.state != SupplierPayment.State.DRAFT:
        raise ValidationError("Solo un pago en borrador puede aplicarse.")
    applications = list(payment.applications.select_for_update().order_by("bill_id"))
    if not applications:
        raise ValidationError("Agrega al menos una factura de proveedor al pago.")
    allocated = sum((item.amount for item in applications), Decimal("0.00"))
    if allocated != payment.amount:
        raise ValidationError("El importe del pago debe quedar aplicado exactamente a facturas de proveedor.")

    bill_ids = sorted({item.bill_id for item in applications}, key=str)
    bills = {
        bill.id: bill
        for bill in SupplierBill.objects.select_for_update().filter(id__in=bill_ids).order_by("id")
    }
    by_bill = {}
    for application in applications:
        bill = bills.get(application.bill_id)
        if bill is None:
            raise ValidationError("No se encontró una factura de proveedor asociada al pago.")
        if bill.supplier_id != payment.supplier_id:
            raise ValidationError("El proveedor del pago debe coincidir con cada factura aplicada.")
        by_bill[bill.id] = by_bill.get(bill.id, Decimal("0.00")) + application.amount

    for bill_id, amount in by_bill.items():
        bill = bills[bill_id]
        if amount > bill.balance_due:
            raise ValidationError(f"El pago excede el saldo de la factura de proveedor {bill.invoice_number}.")

    payment.state = SupplierPayment.State.POSTED
    payment.posted_by = actor
    payment.posted_at = timezone.now()
    payment.save(update_fields=["state", "posted_by", "posted_at"])
    from accounting.models import PostingConfiguration
    from accounting.posting import create_source_draft
    create_source_draft(
        PostingConfiguration.EventType.SUPPLIER_PAYMENT,
        payment.id,
        actor,
        payment.paid_at.date(),
        f"Pago {payment.number} · {payment.supplier.name}",
        payment.amount,
    )
    return payment


@transaction.atomic
def reverse_supplier_payment(payment_id, actor, reason):
    payment = SupplierPayment.objects.select_for_update().get(pk=payment_id)
    if payment.state == SupplierPayment.State.REVERSED:
        return payment
    if payment.state != SupplierPayment.State.POSTED:
        raise ValidationError("Solo se puede revertir un pago ya aplicado.")
    reason = (reason or "").strip()
    if len(reason) < 10:
        raise ValidationError({"reason": "Explica el motivo de la reversa en al menos 10 caracteres."})

    from accounting.models import JournalEntry
    from accounting.services import reverse_entry

    source_entry = JournalEntry.objects.select_for_update().filter(
        origin_type="purchasing_supplier_payment", origin_id=payment.id,
    ).first()
    reversal_entry = None
    if source_entry:
        reversal_entry = JournalEntry.objects.select_for_update().filter(reversal_of=source_entry).first()
        if reversal_entry and reversal_entry.state != JournalEntry.State.POSTED:
            raise ValidationError("La reversa contable vinculada no está contabilizada; resuélvela con Contabilidad antes de revertir el pago.")
        if not reversal_entry:
            if source_entry.state != JournalEntry.State.POSTED:
                raise ValidationError("La póliza del pago sigue en borrador; contabilízala o resuélvela antes de revertir el pago.")
            reversal_entry = reverse_entry(source_entry.pk, actor)

    payment.state = SupplierPayment.State.REVERSED
    payment.reversal_reason = reason[:500]
    payment.reversed_by = actor
    payment.reversed_at = timezone.now()
    payment.reversal_entry = reversal_entry
    payment.save(update_fields=["state", "reversal_reason", "reversed_by", "reversed_at", "reversal_entry"])
    return payment


@transaction.atomic
def award_purchase_offer(request_id, offer_id, actor, reason=""):
    sourcing = PurchaseSourcingRequest.objects.select_for_update().get(pk=request_id)
    if sourcing.state == PurchaseSourcingRequest.State.AWARDED and sourcing.selected_offer_id == offer_id:
        return sourcing
    offer = PurchaseOffer.objects.get(pk=offer_id, request=sourcing)
    remaining = {
        line.pk: line.quantity - (PurchaseOrderLine.objects.filter(
            sourcing_line=line, purchase_order__status__in=[PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.ORDERED, PurchaseOrder.Status.PARTIAL, PurchaseOrder.Status.RECEIVED],
        ).aggregate(total=Sum("quantity"))["total"] or Decimal("0.000"))
        for line in sourcing.lines.all()
    }
    offer_lines = {line.sourcing_line_id: line for line in offer.lines.all()}
    if not remaining or set(offer_lines) != set(remaining) or any(qty <= 0 or offer_lines[line_id].quoted_quantity < qty for line_id, qty in remaining.items()):
        raise ValidationError("Esta oferta no cubre por completo lo que falta; usa adjudicación por renglón.")
    allocations = [{"offer": offer.pk, "sourcing_line": line_id, "quantity": qty, "reason": reason} for line_id, qty in remaining.items()]
    return award_purchase_allocations(request_id, allocations, actor)


@transaction.atomic
def award_purchase_allocations(request_id, allocations, actor):
    sourcing = PurchaseSourcingRequest.objects.select_for_update().select_related("target_location").get(pk=request_id)
    if sourcing.state not in {PurchaseSourcingRequest.State.OPEN, PurchaseSourcingRequest.State.PARTIAL}:
        raise ValidationError("Solo se puede adjudicar una solicitud abierta o parcialmente adjudicada.")
    if not allocations:
        raise ValidationError("Selecciona al menos un renglón para adjudicar.")

    request_lines = {line.pk: line for line in sourcing.lines.select_related("product")}
    offers = {offer.pk: offer for offer in PurchaseOffer.objects.select_for_update().filter(request=sourcing).select_related("supplier")}
    offer_lines = {(line.offer_id, line.sourcing_line_id): line for line in PurchaseOfferLine.objects.filter(offer__request=sourcing)}
    active_order_statuses = [PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.ORDERED, PurchaseOrder.Status.PARTIAL, PurchaseOrder.Status.RECEIVED]
    used_request_quantities = {
        row["sourcing_line_id"]: row["total"] or Decimal("0.000")
        for row in PurchaseOrderLine.objects.filter(
            sourcing_line_id__in=request_lines,
            purchase_order__status__in=active_order_statuses,
        ).values("sourcing_line_id").annotate(total=Sum("quantity"))
    }
    used_offer_quantities = {
        (row["purchase_order__sourcing_offer_id"], row["sourcing_line_id"]): row["total"] or Decimal("0.000")
        for row in PurchaseOrderLine.objects.filter(
            purchase_order__sourcing_request=sourcing,
            purchase_order__status__in=active_order_statuses,
            purchase_order__sourcing_offer__isnull=False,
        ).values("purchase_order__sourcing_offer_id", "sourcing_line_id").annotate(total=Sum("quantity"))
    }
    request_remaining = {line_id: line.quantity - used_request_quantities.get(line_id, Decimal("0.000")) for line_id, line in request_lines.items()}
    lowest_available_price = {}
    today = timezone.localdate()
    for key, quoted in offer_lines.items():
        candidate = offers.get(key[0])
        if not candidate or candidate.state not in {PurchaseOffer.State.RECEIVED, PurchaseOffer.State.PARTIAL}:
            continue
        if candidate.valid_until and candidate.valid_until < today:
            continue
        available = quoted.quoted_quantity - used_offer_quantities.get(key, Decimal("0.000"))
        if available > 0:
            current = lowest_available_price.get(key[1])
            if current is None or quoted.unit_cost < current:
                lowest_available_price[key[1]] = quoted.unit_cost

    offer_remaining = {}
    planned = {}
    seen = set()
    for item in allocations:
        offer_id, line_id = item["offer"], item["sourcing_line"]
        quantity = Decimal(item["quantity"]).quantize(Decimal("0.001"))
        key = (offer_id, line_id)
        if key in seen:
            raise ValidationError("No repitas la combinación de oferta y producto; suma las cantidades.")
        seen.add(key)
        offer, line = offers.get(offer_id), request_lines.get(line_id)
        if not offer or not line:
            raise ValidationError("La oferta y el renglón deben pertenecer a esta solicitud.")
        if offer.state not in {PurchaseOffer.State.RECEIVED, PurchaseOffer.State.PARTIAL}:
            raise ValidationError(f"La oferta de {offer.supplier.name} ya no tiene cantidades disponibles.")
        if offer.valid_until and offer.valid_until < today:
            raise ValidationError(f"La oferta de {offer.supplier.name} venció; solicita una actualización.")
        quoted = offer_lines.get(key)
        if not quoted:
            raise ValidationError(f"La oferta de {offer.supplier.name} no cotizó {line.product.sku}.")
        if key not in offer_remaining:
            offer_remaining[key] = quoted.quoted_quantity - used_offer_quantities.get(key, Decimal("0.000"))
        if quantity <= 0 or quantity > request_remaining[line_id] or quantity > offer_remaining[key]:
            raise ValidationError(f"La cantidad adjudicada de {line.product.sku} excede lo solicitado o lo cotizado.")
        reason = str(item.get("reason", "")).strip()
        if quoted.unit_cost > lowest_available_price.get(line_id, quoted.unit_cost) and len(reason) < 10:
            raise ValidationError(f"Justifica con al menos 10 caracteres por qué se elige a {offer.supplier.name} para {line.product.sku} con un precio mayor.")
        request_remaining[line_id] -= quantity
        offer_remaining[key] -= quantity
        planned.setdefault(offer_id, []).append((line, quoted, quantity, reason))

    orders = []
    for offer_id, rows in planned.items():
        offer = offers[offer_id]
        order = PurchaseOrder.objects.create(
            supplier=offer.supplier, order_date=today,
            expected_date=offer.expected_date or sourcing.desired_date,
            notes=f"Adjudicación {offer.supplier_reference or offer.id} · solicitud {sourcing.number}. {offer.notes}".strip(),
            sourcing_request=sourcing, sourcing_offer=offer, created_by=actor,
        )
        for index, (line, quoted, quantity, reason) in enumerate(rows, start=1):
            PurchaseOrderLine.objects.create(
                purchase_order=order, line_number=index, product=line.product, sourcing_line=line,
                expected_location=sourcing.target_location, description=line.description,
                quantity=quantity, unit_cost=quoted.unit_cost, award_reason=reason,
            )
        orders.append(order)
        detail_lines = ", ".join(f"{line.product.sku} × {quantity}" + (f" (motivo: {reason})" if reason else "") for line, _quoted, quantity, reason in rows)
        PurchaseSourcingEvent.objects.create(
            request=sourcing, offer=offer, action="offer_awarded",
            detail=f"{offer.supplier.name} · {order.number} · {detail_lines}"[:500],
            actor=actor,
        )
    refresh_sourcing_request(sourcing.id)
    return PurchaseSourcingRequest.objects.get(pk=sourcing.pk)


def refresh_sourcing_request(request_id):
    sourcing = PurchaseSourcingRequest.objects.select_for_update().get(pk=request_id)
    lines = list(sourcing.lines.all())
    allocated_by_line = {
        row["sourcing_line_id"]: row["total"] or Decimal("0.000")
        for row in PurchaseOrderLine.objects.filter(
            sourcing_line__request_id=request_id,
            purchase_order__status__in=[PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.ORDERED, PurchaseOrder.Status.PARTIAL, PurchaseOrder.Status.RECEIVED],
        ).values("sourcing_line_id").annotate(total=Sum("quantity"))
    }
    if not lines or all(allocated_by_line.get(line.pk, Decimal("0.000")) >= line.quantity for line in lines):
        state = PurchaseSourcingRequest.State.AWARDED
    elif any(allocated_by_line.get(line.pk, Decimal("0.000")) > 0 for line in lines):
        state = PurchaseSourcingRequest.State.PARTIAL
    else:
        state = PurchaseSourcingRequest.State.OPEN
    active_orders = list(sourcing.purchase_orders.exclude(status=PurchaseOrder.Status.CANCELLED).select_related("sourcing_offer"))
    offer_ids = {order.sourcing_offer_id for order in active_orders if order.sourcing_offer_id}
    selected_offer_id = next(iter(offer_ids)) if state == PurchaseSourcingRequest.State.AWARDED and len(offer_ids) == 1 else None
    purchase_order_id = active_orders[0].id if state == PurchaseSourcingRequest.State.AWARDED and len(active_orders) == 1 else None
    PurchaseSourcingRequest.objects.filter(pk=request_id).update(state=state, selected_offer_id=selected_offer_id, purchase_order_id=purchase_order_id)

    for offer in sourcing.offers.all():
        if offer.state == PurchaseOffer.State.REJECTED:
            continue
        awarded = PurchaseOrderLine.objects.filter(
            purchase_order__sourcing_offer=offer,
            purchase_order__status__in=[PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.ORDERED, PurchaseOrder.Status.PARTIAL, PurchaseOrder.Status.RECEIVED],
        ).aggregate(total=Sum("quantity"))["total"] or Decimal("0.000")
        offered = offer.lines.aggregate(total=Sum("quoted_quantity"))["total"] or Decimal("0.000")
        next_state = PurchaseOffer.State.SELECTED if awarded >= offered and offered > 0 else PurchaseOffer.State.PARTIAL if awarded > 0 else PurchaseOffer.State.RECEIVED
        PurchaseOffer.objects.filter(pk=offer.pk).update(state=next_state)


def send_purchase_rfq(request_id, supplier_id, actor, confirm_send):
    if not confirm_send:
        raise ValidationError("Confirma el envío del correo al proveedor.")
    if not settings.EMAIL_HOST or not settings.DEFAULT_FROM_EMAIL:
        raise ValidationError("Configura EMAIL_HOST y EMAIL_FROM antes de enviar solicitudes de cotización.")

    with transaction.atomic():
        sourcing = PurchaseSourcingRequest.objects.select_for_update().get(pk=request_id)
        if sourcing.state not in {PurchaseSourcingRequest.State.OPEN, PurchaseSourcingRequest.State.PARTIAL}:
            raise ValidationError("Solo puedes enviar solicitudes de cotización abiertas o parcialmente adjudicadas.")
        supplier = Supplier.objects.select_for_update().get(pk=supplier_id, is_active=True)
        if not supplier.email.strip():
            raise ValidationError("El proveedor no tiene correo registrado.")
        if sourcing.offers.filter(supplier=supplier).exists():
            raise ValidationError("Ya existe una cotización registrada de este proveedor para la solicitud.")
        lines = list(sourcing.lines.select_related("product").order_by("line_number"))
        if not lines:
            raise ValidationError("La solicitud no tiene productos para cotizar.")
        recipient = supplier.email.strip()
        PurchaseSourcingEvent.objects.create(
            request=sourcing, supplier=supplier, recipient_email=recipient,
            action="rfq_email_attempt", detail=f"Preparando envío para {sourcing.number}", actor=actor,
        )
        request_number = sourcing.number
        desired_date = sourcing.desired_date
        notes = sourcing.notes
        line_data = []
        for line in lines:
            awarded = PurchaseOrderLine.objects.filter(
                sourcing_line=line,
                purchase_order__status__in=[PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.ORDERED, PurchaseOrder.Status.PARTIAL, PurchaseOrder.Status.RECEIVED],
            ).aggregate(total=Sum("quantity"))["total"] or Decimal("0.000")
            remaining = line.quantity - awarded
            if remaining > 0:
                line_data.append((line.product.sku, line.description or line.product.name, remaining, line.product.unit))
        if not line_data:
            raise ValidationError("La solicitud ya tiene todas sus cantidades adjudicadas.")

    products_text = "\n".join(f"• {sku} · {name} — {quantity} {unit}" for sku, name, quantity, unit in line_data)
    desired = desired_date.strftime("%d/%m/%Y") if desired_date else "No especificada"
    text_body = (
        f"Hola {supplier.name},\n\nRedmagna solicita su cotización para la referencia {request_number}.\n\n"
        f"Productos y cantidades:\n{products_text}\n\nFecha requerida: {desired}\n\n"
        "Favor de responder indicando precio unitario antes de IVA en MXN, vigencia de la oferta y fecha estimada de entrega. "
        "Detalla impuestos y flete por separado en las condiciones. La comparación del ERP suma precios unitarios y requiere revisar esos cargos adicionales antes de elegir. "
        "Esta solicitud es únicamente para comparar ofertas; no constituye una orden de compra ni autoriza el envío de mercancía.\n\n"
        f"Notas: {notes or 'Sin notas adicionales.'}\n\nGracias,\nRedmagna"
    )
    product_rows = "".join(
        f"<tr><td style=\"padding:8px;border-bottom:1px solid #e5e9ef\">{escape(sku)} · {escape(name)}</td>"
        f"<td style=\"padding:8px;text-align:right;border-bottom:1px solid #e5e9ef\">{escape(str(quantity))} {escape(unit)}</td></tr>"
        for sku, name, quantity, unit in line_data
    )
    html_body = (
        f"<p>Hola {escape(supplier.name)},</p><p>Redmagna solicita su cotización para la referencia "
        f"<strong>{escape(request_number)}</strong>.</p><table style=\"border-collapse:collapse;width:100%;font-family:Arial,sans-serif\">"
        f"<thead><tr><th style=\"text-align:left;padding:8px\">Producto</th><th style=\"text-align:right;padding:8px\">Cantidad</th></tr></thead>"
        f"<tbody>{product_rows}</tbody></table><p>Fecha requerida: {escape(desired)}</p>"
        "<p>Favor de responder indicando precio unitario antes de IVA en MXN, vigencia de la oferta y fecha estimada de entrega. "
        "Detalla impuestos y flete por separado en las condiciones. La comparación del ERP suma precios unitarios y requiere revisar esos cargos adicionales antes de elegir. "
        "Esta solicitud es únicamente para comparar ofertas; no constituye una orden de compra ni autoriza el envío de mercancía.</p>"
        f"<p>Notas: {escape(notes or 'Sin notas adicionales.').replace(chr(10), '<br>')}</p><p>Gracias,<br>Redmagna</p>"
    )
    message = EmailMultiAlternatives(
        f"Solicitud de cotización {request_number} · Redmagna", text_body,
        from_email=settings.DEFAULT_FROM_EMAIL, to=[recipient], reply_to=[settings.DEFAULT_FROM_EMAIL],
    )
    message.attach_alternative(html_body, "text/html")
    try:
        sent_count = message.send(fail_silently=False)
    except Exception as exc:
        PurchaseSourcingEvent.objects.create(
            request_id=request_id, supplier_id=supplier_id, recipient_email=recipient,
            action="rfq_email_uncertain", detail=f"No se confirmó el resultado SMTP ({exc.__class__.__name__})", actor=actor,
        )
        raise ValidationError("No se confirmó el resultado del envío. Revisa el correo enviado antes de intentar reenviarlo.") from exc
    if sent_count != 1:
        PurchaseSourcingEvent.objects.create(
            request_id=request_id, supplier_id=supplier_id, recipient_email=recipient,
            action="rfq_email_failed", detail="El servidor de correo no confirmó el envío.", actor=actor,
        )
        raise ValidationError("El servidor de correo no confirmó el envío.")
    PurchaseSourcingEvent.objects.create(
        request_id=request_id, supplier_id=supplier_id, recipient_email=recipient,
        action="rfq_email_sent", detail=f"Solicitud {request_number} enviada al proveedor.", actor=actor,
    )
    return {"supplier": supplier.name, "recipient": recipient, "request_number": request_number}
