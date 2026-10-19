from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError as DRFValidationError

from inventory.models import StockLocation
from .models import AuditEvent, Opportunity, Quote, QuoteAcceptance, QuoteCostItem, QuoteCostSheet, QuoteDiscountApproval, QuoteDiscountPolicy, QuoteLine, SalesOrder, WorkOrder, WorkOrderCustomerAcceptance, WorkOrderMaterialRequirement


def quote_discount_snapshot(quote, lines=None):
    lines = list(lines if lines is not None else quote.lines.all())
    commercial_lines = [{
        "id": str(line.id),
        "kind": line.kind,
        "catalog_product": str(line.catalog_product_id or ""),
        "description": line.description,
        "quantity": str(line.quantity),
        "unit_price": str(line.unit_price),
        "discount_percent": str(line.discount_percent),
        "tax_rate": str(line.tax_rate),
        "is_optional": line.is_optional,
    } for line in sorted(lines, key=lambda item: str(item.id))]
    maximum_discount = max((line.discount_percent for line in lines), default=Decimal("0.00"))
    serialized = json.dumps(commercial_lines, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return maximum_discount, sha256(serialized.encode("utf-8")).hexdigest()


def quote_discount_review(quote, lines=None):
    policy = QuoteDiscountPolicy.objects.filter(pk=1).first()
    maximum_discount, snapshot_hash = quote_discount_snapshot(quote, lines)
    if not policy or not policy.enabled or maximum_discount <= policy.maximum_discount_percent:
        return {
            "required": False,
            "approved": False,
            "maximum_discount_percent": maximum_discount,
            "threshold_percent": policy.maximum_discount_percent if policy else Decimal("0.00"),
        }
    approved = QuoteDiscountApproval.objects.filter(
        quote=quote, quote_snapshot_hash=snapshot_hash,
        threshold_percent=policy.maximum_discount_percent,
    ).exists()
    return {
        "required": True,
        "approved": approved,
        "maximum_discount_percent": maximum_discount,
        "threshold_percent": policy.maximum_discount_percent,
    }


@transaction.atomic
def approve_quote_discount(quote_id, actor):
    quote = Quote.objects.select_for_update().get(pk=quote_id)
    if quote.status != Quote.Status.SENT:
        raise DjangoValidationError("Solo una cotización enviada puede recibir autorización de descuento.")
    lines = list(QuoteLine.objects.select_for_update().filter(quote=quote).order_by("id"))
    review = quote_discount_review(quote, lines)
    if not review["required"]:
        raise DjangoValidationError("La política actual no requiere autorización adicional para este descuento.")
    if review["approved"]:
        return quote, False
    QuoteDiscountApproval.objects.create(
        quote=quote,
        quote_snapshot_hash=quote_discount_snapshot(quote, lines)[1],
        threshold_percent=review["threshold_percent"],
        maximum_discount_percent=review["maximum_discount_percent"],
        approved_by=actor,
    )
    AuditEvent.objects.create(
        entity_type="quote", entity_id=quote.id, action="discount_exception_approved",
        from_value=str(review["threshold_percent"]),
        to_value=str(review["maximum_discount_percent"]), actor=actor,
    )
    return quote, True


@transaction.atomic
def revise_quote(quote_id, actor):
    quote = Quote.objects.select_for_update().select_related("customer", "opportunity").get(pk=quote_id)
    if quote.status == Quote.Status.SUPERSEDED:
        current = quote
        while current.status == Quote.Status.SUPERSEDED:
            descendants = list(
                Quote.objects.select_for_update()
                .filter(revision_of=current)
                .order_by("-revision_number")[:2]
            )
            if len(descendants) != 1:
                raise DjangoValidationError("La cadena de revisiones de esta cotización es ambigua o está incompleta.")
            current = descendants[0]
        return current, False
    if quote.status != Quote.Status.SENT:
        raise DjangoValidationError("Solo una cotización enviada puede convertirse en una nueva revisión.")

    lines = list(quote.lines.select_related("catalog_product").order_by("id"))
    if not lines:
        raise DjangoValidationError("Agrega conceptos antes de crear una revisión.")

    revision = Quote.objects.create(
        customer=quote.customer,
        customer_contact=quote.customer_contact,
        recipient_name_snapshot=quote.recipient_name_snapshot,
        recipient_email_snapshot=quote.recipient_email_snapshot,
        opportunity=quote.opportunity,
        title=quote.title,
        customer_site=quote.customer_site,
        service_site_name=quote.service_site_name,
        service_address=quote.service_address,
        service_contact_name=quote.service_contact_name,
        service_contact_phone=quote.service_contact_phone,
        service_contact_email=quote.service_contact_email,
        issue_date=timezone.localdate(),
        valid_until=quote.valid_until,
        payment_term_days=quote.payment_term_days,
        notes=quote.notes,
        created_by=actor,
        revision_of=quote,
        revision_number=quote.revision_number + 1,
    )
    QuoteLine.objects.bulk_create([
        QuoteLine(
            quote=revision,
            kind=line.kind,
            catalog_product=line.catalog_product,
            description=line.description,
            quantity=line.quantity,
            unit_price=line.unit_price,
            discount_percent=line.discount_percent,
            tax_rate=line.tax_rate,
            is_optional=line.is_optional,
        )
        for line in lines
    ])
    if hasattr(quote, "cost_sheet"):
        source_sheet = quote.cost_sheet
        revision_sheet = QuoteCostSheet.objects.create(
            quote=revision,
            target_margin_percent=source_sheet.target_margin_percent,
            created_by=actor,
            updated_by=actor,
        )
        QuoteCostItem.objects.bulk_create([
            QuoteCostItem(
                cost_sheet=revision_sheet,
                category=item.category,
                description=item.description,
                quantity=item.quantity,
                unit_cost=item.unit_cost,
                is_optional=item.is_optional,
                sort_order=item.sort_order,
            )
            for item in source_sheet.items.all()
        ])

    before = quote.status
    quote.status = Quote.Status.SUPERSEDED
    quote.save(update_fields=["status", "updated_at"])
    AuditEvent.objects.create(
        entity_type="quote", entity_id=quote.id, action="superseded",
        from_value=before, to_value=quote.status, actor=actor,
    )
    AuditEvent.objects.create(
        entity_type="quote", entity_id=revision.id, action="revision_created",
        from_value=quote.number, to_value=revision.number, actor=actor,
    )
    return revision, True


@transaction.atomic
def record_work_order_customer_acceptance(work_order_id, actor, customer_contact_name, customer_contact_email="", notes=""):
    work_order = WorkOrder.objects.select_for_update().get(pk=work_order_id)
    if work_order.status != WorkOrder.Status.IN_PROGRESS:
        raise DjangoValidationError("El acuse se captura mientras la orden está en curso y antes de terminarla.")
    if not work_order.completion_notes.strip():
        raise DjangoValidationError("Agrega primero la nota de cierre del servicio.")
    checklist = list(work_order.checklist_items.values_list("is_completed", flat=True))
    if not checklist or not all(checklist):
        raise DjangoValidationError("Completa todos los puntos de la lista antes de registrar la conformidad del cliente.")
    if hasattr(work_order, "customer_acceptance"):
        raise DjangoValidationError("Esta orden ya tiene un acuse de conformidad registrado.")
    acceptance = WorkOrderCustomerAcceptance.objects.create(
        work_order=work_order,
        customer_contact_name=customer_contact_name.strip(),
        customer_contact_email=customer_contact_email.strip().lower(),
        notes=notes.strip(),
        captured_by=actor,
    )
    AuditEvent.objects.create(
        entity_type="work_order",
        entity_id=work_order.id,
        action="customer_acceptance_recorded",
        to_value="captured",
        actor=actor,
    )
    return acceptance


@transaction.atomic
def approve_quote(quote_id, actor=None, customer_acceptance=None, optional_line_ids=None, accepted_quantities=None):
    quote = Quote.objects.select_for_update().select_related("customer").get(pk=quote_id)
    if quote.status != Quote.Status.SENT:
        raise DRFValidationError("Solo se puede aceptar una cotización enviada.")
    if quote.valid_until and quote.valid_until < timezone.localdate():
        raise DRFValidationError("La vigencia de la cotización ya terminó.")
    opportunity = Opportunity.objects.select_for_update().get(pk=quote.opportunity_id) if quote.opportunity_id else None
    if opportunity and opportunity.stage == Opportunity.Stage.LOST:
        raise DRFValidationError("Reabre la oportunidad antes de aceptar esta cotización.")

    lines = list(QuoteLine.objects.select_for_update().filter(quote=quote).order_by("id"))
    if not lines:
        raise DRFValidationError("La cotización no tiene conceptos para aceptar.")
    discount_review = quote_discount_review(quote, lines)
    if discount_review["required"] and not discount_review["approved"]:
        raise DRFValidationError("La cotización supera el límite de descuento y requiere autorización de Gerencia antes de aceptarse.")
    selected_optional_ids = {str(line_id) for line_id in (optional_line_ids or [])}
    valid_optional_ids = {str(line.id) for line in lines if line.is_optional}
    if not selected_optional_ids.issubset(valid_optional_ids):
        raise DRFValidationError({"optional_line_ids": "La selección contiene conceptos que no son opcionales o no pertenecen a esta cotización."})
    parsed_quantities = None
    if accepted_quantities is not None:
        valid_line_ids = {str(line.id) for line in lines}
        if set(accepted_quantities) != valid_line_ids:
            raise DRFValidationError({"accepted_quantities": "Envía una cantidad para cada concepto de la cotización."})
        parsed_quantities = {}
        for line in lines:
            try:
                value = Decimal(str(accepted_quantities[str(line.id)]))
            except (InvalidOperation, TypeError, ValueError):
                raise DRFValidationError({"accepted_quantities": f"La cantidad de '{line.description}' no es válida."})
            if not value.is_finite() or value < 0 or value > line.quantity or value * 1000 != (value * 1000).to_integral_value():
                raise DRFValidationError({"accepted_quantities": f"La cantidad de '{line.description}' debe estar entre cero y {line.quantity}, con hasta tres decimales."})
            if not line.is_optional and value == 0:
                raise DRFValidationError({"accepted_quantities": f"El concepto base '{line.description}' requiere una cantidad mayor que cero; solo se pueden excluir conceptos opcionales."})
            parsed_quantities[str(line.id)] = value
        if not any(parsed_quantities.values()):
            raise DRFValidationError({"accepted_quantities": "Acepta al menos una cantidad mayor que cero."})
    material_lines = []
    for line in lines:
        if parsed_quantities is not None:
            accepted_quantity = parsed_quantities[str(line.id)]
        else:
            accepted_quantity = line.quantity if not line.is_optional or str(line.id) in selected_optional_ids else Decimal("0.000")
        QuoteLine.objects.filter(pk=line.pk).update(approved_quantity=accepted_quantity)
        if accepted_quantity > 0 and line.catalog_product_id and line.kind in {QuoteLine.Kind.EQUIPMENT, QuoteLine.Kind.MATERIAL}:
            material_lines.append((line, accepted_quantity))

    if customer_acceptance:
        email = customer_acceptance["email"].strip().lower()
        if email != quote.customer.email.strip().lower():
            raise DRFValidationError("El correo no coincide con el del cliente registrado.")
        QuoteAcceptance.objects.create(
            quote=quote,
            accepted_by_name=customer_acceptance["name"].strip(),
            accepted_by_email=email,
        )

    previous_status = quote.status
    quote.status = Quote.Status.APPROVED
    quote.save(update_fields=["status", "updated_at"])
    order = SalesOrder.objects.create(
        quote=quote,
        confirmed_by=actor,
        confirmation_source=SalesOrder.ConfirmationSource.CUSTOMER if customer_acceptance else SalesOrder.ConfirmationSource.STAFF,
    )
    work_order = WorkOrder.objects.create(
        sales_order=order,
        customer_site=quote.customer_site,
        title=quote.title,
        service_site_name=quote.service_site_name,
        service_address=quote.service_address,
        service_contact_name=quote.service_contact_name,
        service_contact_phone=quote.service_contact_phone,
        service_contact_email=quote.service_contact_email,
    )
    default_supply_location = StockLocation.objects.filter(code="MAIN", is_active=True).first() or StockLocation.objects.filter(is_active=True).order_by("code").first()
    if material_lines and not default_supply_location:
        raise DjangoValidationError("Activa al menos una ubicación de inventario antes de aprobar cotizaciones con materiales.")
    for line, accepted_quantity in material_lines:
        WorkOrderMaterialRequirement.objects.create(
            work_order=work_order,
            source_quote_line=line,
            product_id=line.catalog_product_id,
            supply_location=default_supply_location,
            required_quantity=accepted_quantity,
        )
    AuditEvent.objects.create(
        entity_type="quote", entity_id=quote.id, action="approved",
        from_value=previous_status, to_value=quote.status, actor=actor,
    )
    if opportunity and opportunity.stage != Opportunity.Stage.WON:
        previous_stage = opportunity.stage
        opportunity.stage = Opportunity.Stage.WON
        opportunity.probability = 100
        opportunity.save(update_fields=["stage", "probability", "updated_at"])
        AuditEvent.objects.create(
            entity_type="opportunity", entity_id=opportunity.id, action="quote_approved",
            from_value=previous_stage, to_value=Opportunity.Stage.WON, actor=actor,
        )
    return quote, order
