from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import connection, transaction

from .models import JournalEntry, JournalLine, PostingConfiguration


@transaction.atomic
def create_source_draft(event_type, source_id, actor, entry_date, memo, amount, base_amount=None, tax_amount=None):
    """Create an idempotent draft journal entry when the accountant enabled a mapping."""
    config = PostingConfiguration.objects.select_related(
        "journal", "receivable_account", "revenue_account", "tax_account", "funds_account",
        "payable_account", "purchase_account", "supplier_tax_account",
    ).filter(event_type=event_type, is_active=True).first()
    if config is None:
        return None
    config.clean()

    supplier_event = event_type in [PostingConfiguration.EventType.SUPPLIER_BILL, PostingConfiguration.EventType.SUPPLIER_PAYMENT]
    origin_type = f"{'purchasing' if supplier_event else 'billing'}_{event_type}"
    # Serialize concurrent retries for the same source before checking whether
    # its draft already exists. A row lock cannot protect an absent row.
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
            [origin_type, str(source_id)],
        )
    existing = JournalEntry.objects.select_for_update().filter(origin_type=origin_type, origin_id=source_id).first()
    if existing:
        return existing

    amount = Decimal(amount).quantize(Decimal("0.01"))
    base_amount = Decimal(base_amount or 0).quantize(Decimal("0.01"))
    tax_amount = Decimal(tax_amount or 0).quantize(Decimal("0.01"))
    if amount <= 0:
        raise ValidationError("No se puede generar una póliza con importe cero.")

    if event_type == PostingConfiguration.EventType.CUSTOMER_INVOICE:
        if base_amount + tax_amount != amount:
            raise ValidationError("El total de factura no coincide con base más impuesto.")
        if tax_amount and not config.tax_account_id:
            raise ValidationError("Configura la cuenta de impuestos antes de generar pólizas de facturas con impuesto.")
        lines = [(config.receivable_account, amount, Decimal("0.00"), "Cuenta por cobrar")]
        if base_amount:
            lines.append((config.revenue_account, Decimal("0.00"), base_amount, "Ingreso por venta"))
        if tax_amount:
            lines.append((config.tax_account, Decimal("0.00"), tax_amount, "Impuesto trasladado estimado"))
    elif event_type == PostingConfiguration.EventType.CUSTOMER_CREDIT_NOTE:
        if base_amount + tax_amount != amount:
            raise ValidationError("El total de la nota de crédito no coincide con base más impuesto.")
        if tax_amount and not config.tax_account_id:
            raise ValidationError("Configura la cuenta de impuestos antes de generar pólizas de notas de crédito.")
        lines = [(config.receivable_account, Decimal("0.00"), amount, "Disminución de cuentas por cobrar")]
        if base_amount:
            lines.append((config.revenue_account, base_amount, Decimal("0.00"), "Devolución / bonificación sobre ventas"))
        if tax_amount:
            lines.append((config.tax_account, tax_amount, Decimal("0.00"), "Disminución de impuesto trasladado estimado"))
    elif event_type == PostingConfiguration.EventType.CUSTOMER_PAYMENT:
        lines = [
            (config.funds_account, amount, Decimal("0.00"), "Cobro recibido"),
            (config.receivable_account, Decimal("0.00"), amount, "Aplicación a cuentas por cobrar"),
        ]
    elif event_type == PostingConfiguration.EventType.SUPPLIER_BILL:
        if base_amount + tax_amount != amount:
            raise ValidationError("El total de la factura de proveedor no coincide con subtotal más impuesto declarado.")
        if tax_amount and not config.supplier_tax_account_id:
            raise ValidationError("Configura una cuenta para el impuesto declarado antes de generar pólizas de compras con impuesto.")
        lines = []
        if base_amount:
            lines.append((config.purchase_account, base_amount, Decimal("0.00"), "Compra / inventario según configuración"))
        if tax_amount:
            lines.append((config.supplier_tax_account, tax_amount, Decimal("0.00"), "Impuesto de compra declarado · pendiente de revisión"))
        lines.append((config.payable_account, Decimal("0.00"), amount, "Cuenta por pagar a proveedor"))
    elif event_type == PostingConfiguration.EventType.SUPPLIER_PAYMENT:
        lines = [
            (config.payable_account, amount, Decimal("0.00"), "Aplicación a cuenta por pagar"),
            (config.funds_account, Decimal("0.00"), amount, "Pago a proveedor · pendiente de conciliación"),
        ]
    else:
        raise ValidationError("Tipo de movimiento contable automático no reconocido.")

    entry = JournalEntry.objects.create(
        journal=config.journal,
        entry_date=entry_date,
        memo=memo[:240],
        origin_type=origin_type,
        origin_id=source_id,
        created_by=actor,
    )
    for line_number, (account, debit, credit, description) in enumerate(lines, start=1):
        JournalLine.objects.create(
            entry=entry,
            line_number=line_number,
            account=account,
            description=description,
            debit=debit,
            credit=credit,
        )
    return entry
