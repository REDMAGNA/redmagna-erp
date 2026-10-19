"""Two-person workflow for operational AR/AP opening items."""

from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.functions import Trim, Upper
from django.utils import timezone

from billing.models import CustomerInvoice
from purchasing.models import Supplier, SupplierBill
from sales.models import Customer

from .models import Account, OpeningBalanceBatch, OpeningBalanceItem
from .open_items import _control_balance, preview_open_items_csv


CENT = Decimal("0.01")


@transaction.atomic
def prepare_opening_balance_batch(actor, upload, cutoff_date, receivables_account, payables_account):
    if not actor.has_perm("accounting.prepare_openingbalancebatch"):
        raise ValidationError("Tu usuario no tiene permiso para preparar lotes de apertura.")
    receivables_account = Account.objects.select_for_update().get(pk=receivables_account.pk)
    payables_account = Account.objects.select_for_update().get(pk=payables_account.pk)
    try:
        raw = upload.read()
        upload.seek(0)
    except (AttributeError, OSError):
        raise ValidationError({"file": "No se pudo volver a leer el CSV para preparar el lote."}) from None
    from hashlib import sha256

    file_hash = sha256(raw).hexdigest()
    existing = OpeningBalanceBatch.objects.filter(
        csv_sha256=file_hash,
        cutoff_date=cutoff_date,
        receivables_account=receivables_account,
        payables_account=payables_account,
        state__in=[OpeningBalanceBatch.State.DRAFT, OpeningBalanceBatch.State.POSTED],
    ).first()
    if existing:
        return existing, False
    try:
        preview = preview_open_items_csv(upload, cutoff_date, receivables_account, payables_account)
    except ValueError as error:
        raise ValidationError({"file": str(error)}) from error
    if not preview["ready_for_review"]:
        raise ValidationError({
            "detail": "La vista previa tiene errores o las sumas no cuadran con las cuentas de control; corrige el archivo antes de preparar el lote.",
            "error_rows": preview["error_rows"],
            "totals": preview["totals"],
        })
    if preview["_csv_sha256"] != file_hash:
        raise ValidationError("El archivo cambió durante la preparación; vuelve a cargarlo y revisa la vista previa.")

    totals_by_direction = {item["direction"]: Decimal(item["open_items_total"]).quantize(CENT) for item in preview["totals"]}
    batch = OpeningBalanceBatch.objects.create(
        cutoff_date=cutoff_date,
        csv_sha256=file_hash,
        receivables_account=receivables_account,
        payables_account=payables_account,
        receivables_total=totals_by_direction.get(OpeningBalanceItem.Direction.RECEIVABLE, Decimal("0.00")),
        payables_total=totals_by_direction.get(OpeningBalanceItem.Direction.PAYABLE, Decimal("0.00")),
        item_count=preview["valid_rows"],
        created_by=actor,
    )
    for row in preview["_validated_items"]:
        OpeningBalanceItem.objects.create(
            batch=batch,
            direction=row["direction"],
            counterparty_rfc=row["counterparty_rfc"],
            source_system=row["source_system"][:120],
            external_number=row["external_number"][:120],
            issue_date=row["issue_date"],
            due_date=row["due_date"],
            currency=row["currency"],
            original_total=row["original_total"],
            paid_before_cutoff=row["paid_before_cutoff"],
            open_balance=row["open_balance"],
        )
    return batch, True


def _active_party_maps(items):
    customer_rfcs = {item.counterparty_rfc for item in items if item.direction == OpeningBalanceItem.Direction.RECEIVABLE}
    supplier_rfcs = {item.counterparty_rfc for item in items if item.direction == OpeningBalanceItem.Direction.PAYABLE}
    customer_rows = list(Customer.objects.select_for_update().annotate(normalized_rfc=Upper(Trim("rfc"))).filter(is_active=True, normalized_rfc__in=customer_rfcs))
    supplier_rows = list(Supplier.objects.select_for_update().annotate(normalized_rfc=Upper(Trim("rfc"))).filter(is_active=True, normalized_rfc__in=supplier_rfcs))
    customers = {row.rfc.strip().upper(): row for row in customer_rows}
    suppliers = {row.rfc.strip().upper(): row for row in supplier_rows}
    if len(customers) != len(customer_rows) or set(customers) != customer_rfcs:
        raise ValidationError("Algún RFC de cliente ya no corresponde a un solo cliente activo; corrige el maestro y prepara otro lote.")
    if len(suppliers) != len(supplier_rows) or set(suppliers) != supplier_rfcs:
        raise ValidationError("Algún RFC de proveedor ya no corresponde a un solo proveedor activo; corrige el maestro y prepara otro lote.")
    return customers, suppliers


@transaction.atomic
def review_opening_balance_batch(batch_id, actor, decision, note=""):
    if not actor.has_perm("accounting.review_openingbalancebatch"):
        raise ValidationError("Tu usuario no tiene permiso para revisar lotes de apertura.")
    batch = OpeningBalanceBatch.objects.select_for_update().select_related(
        "receivables_account", "payables_account", "created_by",
    ).get(pk=batch_id)
    if batch.state == OpeningBalanceBatch.State.POSTED and decision == "publish":
        return batch, False
    if batch.state != OpeningBalanceBatch.State.DRAFT:
        raise ValidationError("Solo se puede revisar un lote pendiente.")
    if batch.created_by_id == actor.pk:
        raise ValidationError("La persona revisora debe ser distinta de quien preparó el lote.")
    note = (note or "").strip()
    if decision == "reject":
        if len(note) < 10:
            raise ValidationError({"note": "Explica el rechazo en al menos 10 caracteres."})
        for item in batch.items.select_for_update().all():
            item.is_reserved = False
            item.save(update_fields=["is_reserved"])
        batch.state = OpeningBalanceBatch.State.REJECTED
        batch.reviewed_by = actor
        batch.reviewed_at = timezone.now()
        batch.review_note = note[:500]
        batch.save(update_fields=["state", "reviewed_by", "reviewed_at", "review_note"])
        return batch, True
    if decision != "publish":
        raise ValidationError({"decision": "Selecciona Publicar o Rechazar."})

    items = list(batch.items.select_for_update().filter(batch__state=OpeningBalanceBatch.State.DRAFT).order_by("direction", "counterparty_rfc", "external_number"))
    if len(items) != batch.item_count or any(not item.is_reserved for item in items):
        raise ValidationError("El lote no conserva todas sus partidas reservadas; vuelve a prepararlo.")
    receivables_total = sum((item.open_balance for item in items if item.direction == OpeningBalanceItem.Direction.RECEIVABLE), Decimal("0.00")).quantize(CENT)
    payables_total = sum((item.open_balance for item in items if item.direction == OpeningBalanceItem.Direction.PAYABLE), Decimal("0.00")).quantize(CENT)
    if receivables_total != batch.receivables_total or payables_total != batch.payables_total:
        raise ValidationError("Los totales de las partidas no coinciden con el resumen guardado del lote.")

    receivables_account = Account.objects.select_for_update().get(pk=batch.receivables_account_id)
    payables_account = Account.objects.select_for_update().get(pk=batch.payables_account_id)
    if _control_balance(receivables_account, batch.cutoff_date).quantize(CENT) != receivables_total:
        raise ValidationError("La cuenta de control CxC cambió desde la preparación o ya no cuadra con el lote.")
    if _control_balance(payables_account, batch.cutoff_date).quantize(CENT) != payables_total:
        raise ValidationError("La cuenta de control CxP cambió desde la preparación o ya no cuadra con el lote.")
    customers, suppliers = _active_party_maps(items)
    now = timezone.now()
    for item in items:
        if item.direction == OpeningBalanceItem.Direction.RECEIVABLE:
            customer = customers[item.counterparty_rfc]
            if CustomerInvoice.objects.filter(customer=customer, number__iexact=item.external_number).exists():
                raise ValidationError(f"Ya existe una factura interna con el folio {item.external_number} para un cliente.")
            invoice = CustomerInvoice.objects.create(
                customer=customer,
                currency=item.currency,
                issue_date=item.issue_date,
                due_date=item.due_date,
                memo=f"Saldo migrado · {item.source_system} · {item.external_number}"[:240],
                state=CustomerInvoice.State.OPEN,
                created_by=actor,
                opened_by=actor,
                opened_at=now,
                opening_balance_batch_id=batch.pk,
                opening_external_number=item.external_number,
                opening_source_system=item.source_system,
                opening_cutoff_date=batch.cutoff_date,
                opening_original_total=item.original_total,
                opening_paid_before_cutoff=item.paid_before_cutoff,
            )
            item.customer_invoice = invoice
        else:
            supplier = suppliers[item.counterparty_rfc]
            if SupplierBill.objects.filter(supplier=supplier, invoice_number__iexact=item.external_number).exists():
                raise ValidationError(f"Ya existe una factura de proveedor con el folio {item.external_number}.")
            bill = SupplierBill.objects.create(
                supplier=supplier,
                purchase_order=None,
                invoice_number=item.external_number,
                invoice_date=item.issue_date,
                due_date=item.due_date,
                subtotal=Decimal("0.00"),
                tax_total=Decimal("0.00"),
                total=item.original_total,
                registered_at=now,
                registered_by=actor,
                opening_balance_batch_id=batch.pk,
                opening_source_system=item.source_system,
                opening_cutoff_date=batch.cutoff_date,
                opening_original_total=item.original_total,
                opening_paid_before_cutoff=item.paid_before_cutoff,
            )
            item.supplier_bill = bill
        item.save(update_fields=["customer_invoice", "supplier_bill"])

    batch.state = OpeningBalanceBatch.State.POSTED
    batch.reviewed_by = actor
    batch.reviewed_at = now
    batch.review_note = note[:500]
    batch.save(update_fields=["state", "reviewed_by", "reviewed_at", "review_note"])
    return batch, True
