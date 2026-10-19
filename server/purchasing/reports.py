from collections import defaultdict
from decimal import Decimal
from hashlib import sha256

from django.core.exceptions import ValidationError
from django.db.models import Prefetch, Q
from django.utils import timezone
from lxml import etree

from .cfdi import CFDI_NS, MAX_SUPPLIER_CFDI_BYTES
from .models import SupplierBill, SupplierBillCFDI, SupplierPayment, SupplierPaymentApplication


ZERO = Decimal("0.00")
BUCKET_LABELS = {
    "no_due_date": "Sin vencimiento",
    "current": "Vigente",
    "days_1_30": "1–30 días",
    "days_31_60": "31–60 días",
    "days_61_90": "61–90 días",
    "over_90": "Más de 90 días",
}


def payables_aging(as_of=None):
    as_of = as_of or timezone.localdate()
    bills = (
        SupplierBill.objects.filter(
            invoice_date__lte=as_of,
        ).filter(
            Q(opening_balance_batch_id__isnull=True, registered_at__date__lte=as_of)
            | Q(opening_balance_batch_id__isnull=False, opening_cutoff_date__lte=as_of)
        ).select_related("supplier", "purchase_order")
        .prefetch_related(
            Prefetch(
                "payment_applications",
                queryset=SupplierPaymentApplication.objects.filter(
                    Q(payment__state=SupplierPayment.State.POSTED)
                    | Q(payment__state=SupplierPayment.State.REVERSED, payment__reversed_at__date__gt=as_of),
                    payment__posted_at__date__lte=as_of,
                ).only(
                    "bill_id", "amount", "payment_id"
                ),
                to_attr="posted_applications",
            )
        )
        .order_by("supplier__name", "due_date", "invoice_date", "invoice_number")
    )
    totals = {key: ZERO for key in BUCKET_LABELS}
    counts = {key: 0 for key in BUCKET_LABELS}
    supplier_totals = defaultdict(lambda: {"supplier_id": None, "supplier_name": "", "balance": ZERO, "bill_count": 0})
    rows = []

    for bill in bills:
        paid = bill.opening_paid_before_cutoff + sum((application.amount for application in bill.posted_applications), ZERO)
        balance = bill.total - paid
        if balance <= ZERO:
            continue

        if bill.due_date is None:
            bucket, overdue_days = "no_due_date", None
        elif bill.due_date >= as_of:
            bucket, overdue_days = "current", 0
        else:
            overdue_days = (as_of - bill.due_date).days
            bucket = "days_1_30" if overdue_days <= 30 else "days_31_60" if overdue_days <= 60 else "days_61_90" if overdue_days <= 90 else "over_90"

        totals[bucket] += balance
        counts[bucket] += 1
        supplier = supplier_totals[bill.supplier_id]
        supplier["supplier_id"] = str(bill.supplier_id)
        supplier["supplier_name"] = bill.supplier.name
        supplier["balance"] += balance
        supplier["bill_count"] += 1
        rows.append({
            "bill_id": str(bill.id),
            "invoice_number": bill.invoice_number,
            "supplier_id": str(bill.supplier_id),
            "supplier_name": bill.supplier.name,
            "purchase_order_number": bill.purchase_order.number if bill.purchase_order_id else "",
            "invoice_date": bill.invoice_date.isoformat(),
            "due_date": bill.due_date.isoformat() if bill.due_date else None,
            "overdue_days": overdue_days,
            "bucket": bucket,
            "bucket_label": BUCKET_LABELS[bucket],
            "bill_total": str(bill.total.quantize(Decimal("0.01"))),
            "paid_amount": str(paid.quantize(Decimal("0.01"))),
            "balance_due": str(balance.quantize(Decimal("0.01"))),
        })

    return {
        "as_of": as_of.isoformat(),
        "currency": "MXN",
        "total_balance": str(sum(totals.values(), ZERO).quantize(Decimal("0.01"))),
        "bill_count": len(rows),
        "buckets": [
            {"key": key, "label": label, "balance": str(totals[key].quantize(Decimal("0.01"))), "bill_count": counts[key]}
            for key, label in BUCKET_LABELS.items()
        ],
        "suppliers": [
            {**item, "balance": str(item["balance"].quantize(Decimal("0.01")))}
            for item in sorted(supplier_totals.values(), key=lambda value: value["supplier_name"].casefold())
        ],
        "bills": rows,
    }


def supplier_statement(supplier, as_of=None):
    """Return an internal AP ledger for one supplier through a cutoff date."""
    as_of = as_of or timezone.localdate()
    bills = (
        SupplierBill.objects.filter(
            supplier=supplier,
            invoice_date__lte=as_of,
        ).filter(
            Q(opening_balance_batch_id__isnull=True, registered_at__date__lte=as_of)
            | Q(opening_balance_batch_id__isnull=False, opening_cutoff_date__lte=as_of)
        )
        .select_related("purchase_order")
        .prefetch_related(
            Prefetch(
                "payment_applications",
                queryset=SupplierPaymentApplication.objects.filter(
                    payment__state__in=[SupplierPayment.State.POSTED, SupplierPayment.State.REVERSED],
                    payment__posted_at__date__lte=as_of,
                    payment__paid_at__date__lte=as_of,
                ).select_related("payment").only(
                    "bill_id", "amount", "payment_id", "payment__number", "payment__paid_at",
                    "payment__reference", "payment__memo", "payment__posted_at", "payment__state",
                    "payment__reversal_reason", "payment__reversed_at",
                ),
                to_attr="statement_applications",
            )
        )
        .order_by("invoice_date", "invoice_number")
    )

    entries = []
    charged = ZERO
    credited = ZERO
    payment_totals = defaultdict(lambda: {"payment": None, "amount": ZERO})
    reversed_total = ZERO
    for bill in bills:
        amount = bill.total.quantize(Decimal("0.01"))
        charged += amount
        entries.append({
            "date": (bill.opening_cutoff_date if bill.opening_balance_batch_id else bill.invoice_date).isoformat(),
            "type": "bill",
            "document_number": bill.invoice_number,
            "description": f"Saldo inicial · {bill.opening_source_system}" if bill.opening_balance_batch_id else f"Factura de proveedor · OC {bill.purchase_order.number}",
            "debit": ZERO,
            "credit": amount,
            "sort_order": 0,
        })
        if bill.opening_balance_batch_id and bill.opening_paid_before_cutoff:
            prior_paid = bill.opening_paid_before_cutoff.quantize(Decimal("0.01"))
            credited += prior_paid
            entries.append({
                "date": bill.opening_cutoff_date.isoformat(),
                "type": "opening_payment_summary",
                "document_number": bill.invoice_number,
                "description": "Pagos previos al corte de apertura (resumen)",
                "debit": prior_paid,
                "credit": ZERO,
                "sort_order": 1,
            })
        for application in bill.statement_applications:
            item = payment_totals[application.payment_id]
            item["payment"] = application.payment
            item["amount"] += application.amount

    for item in payment_totals.values():
        payment = item["payment"]
        amount = item["amount"].quantize(Decimal("0.01"))
        credited += amount
        entries.append({
            "date": payment.paid_at.date().isoformat(),
            "type": "payment",
            "document_number": payment.number,
            "description": payment.reference or payment.memo or "Pago aplicado",
            "debit": amount,
            "credit": ZERO,
            "sort_order": 1,
        })
        if payment.state == SupplierPayment.State.REVERSED and payment.reversed_at and payment.reversed_at.date() <= as_of:
            reversed_total += amount
            entries.append({
                "date": payment.reversed_at.date().isoformat(),
                "type": "payment_reversal",
                "document_number": f"REV-{payment.number}",
                "description": f"Reversa de pago · {payment.reversal_reason}",
                "debit": ZERO,
                "credit": amount,
                "sort_order": 2,
            })

    entries.sort(key=lambda row: (row["date"], row["sort_order"], row["document_number"]))
    balance = ZERO
    serialized_entries = []
    for entry in entries:
        balance += entry["credit"] - entry["debit"]
        serialized_entries.append({
            **entry,
            "debit": str(entry["debit"].quantize(Decimal("0.01"))),
            "credit": str(entry["credit"].quantize(Decimal("0.01"))),
            "running_balance": str(balance.quantize(Decimal("0.01"))),
        })
        serialized_entries[-1].pop("sort_order")

    return {
        "supplier_id": str(supplier.pk),
        "supplier_name": supplier.name,
        "supplier_rfc": supplier.rfc,
        "as_of": as_of.isoformat(),
        "currency": "MXN",
        "bill_count": sum(1 for row in entries if row["type"] == "bill"),
        "payment_count": len({row["document_number"] for row in entries if row["type"] == "payment"}),
        "total_billed": str(charged.quantize(Decimal("0.01"))),
        "total_paid": str((credited - reversed_total).quantize(Decimal("0.01"))),
        "balance_due": str(balance.quantize(Decimal("0.01"))),
        "entries": serialized_entries,
    }


def supplier_cfdi_register(date_from=None, date_to=None):
    """Report attached supplier XML totals as declared, without claiming tax deductibility."""
    records = SupplierBillCFDI.objects.select_related("supplier_bill", "supplier_bill__supplier").all()
    if date_from:
        records = records.filter(invoice_date__gte=date_from)
    if date_to:
        records = records.filter(invoice_date__lte=date_to)
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, recover=False)
    rows = []
    subtotal_total = ZERO
    tax_total = ZERO
    invoice_total = ZERO
    tax_totals = defaultdict(lambda: {"tax_code": "", "rate": "", "base": ZERO, "amount": ZERO})
    for record in records.order_by("invoice_date", "supplier_bill__invoice_number", "cfdi_uuid"):
        try:
            with record.xml_file.open("rb") as xml_file:
                xml_bytes = xml_file.read(MAX_SUPPLIER_CFDI_BYTES + 1)
            if not xml_bytes or len(xml_bytes) > MAX_SUPPLIER_CFDI_BYTES:
                raise ValueError("XML vacío o excede el tamaño permitido")
            if sha256(xml_bytes).hexdigest() != record.sha256:
                raise ValueError("la huella SHA-256 no coincide")
            root = etree.fromstring(xml_bytes, parser)
            if root.tag != f"{{{CFDI_NS}}}Comprobante" or root.get("Version") != "4.0" or root.get("TipoDeComprobante") != "I":
                raise ValueError("raíz, versión o tipo CFDI no reconocido")
            stamp = root.find(f".//{{http://www.sat.gob.mx/TimbreFiscalDigital}}TimbreFiscalDigital")
            if stamp is None or stamp.get("UUID", "").lower() != str(record.cfdi_uuid).lower():
                raise ValueError("el UUID del Timbre Fiscal Digital no coincide")
            subtotal = Decimal(root.get("SubTotal", ""))
            total = Decimal(root.get("Total", ""))
            taxes = {}
            for transfer in root.findall(f"{{{CFDI_NS}}}Impuestos/{{{CFDI_NS}}}Traslados/{{{CFDI_NS}}}Traslado"):
                tax_code = transfer.get("Impuesto", "")
                factor = transfer.get("TipoFactor", "")
                rate = "Exento" if factor == "Exento" else transfer.get("TasaOCuota", "")
                key = (tax_code, rate)
                value = taxes.setdefault(key, {"tax_code": tax_code, "rate": rate, "base": ZERO, "amount": ZERO})
                value["base"] += Decimal(transfer.get("Base", "0"))
                value["amount"] += Decimal(transfer.get("Importe", "0"))
            declared_tax = Decimal(root.find(f"{{{CFDI_NS}}}Impuestos").get("TotalImpuestosTrasladados", "0")) if root.find(f"{{{CFDI_NS}}}Impuestos") is not None else ZERO
            if subtotal != record.subtotal or total != record.total or declared_tax != record.tax_total:
                raise ValueError("los importes del XML no coinciden con los metadatos registrados")
            subtotal_total += subtotal
            tax_total += declared_tax
            invoice_total += total
            for key, value in taxes.items():
                aggregate = tax_totals[key]
                aggregate["tax_code"] = value["tax_code"]
                aggregate["rate"] = value["rate"]
                aggregate["base"] += value["base"]
                aggregate["amount"] += value["amount"]
            bill = record.supplier_bill
            rows.append({
                "supplier_bill_id": str(bill.pk),
                "invoice_number": bill.invoice_number,
                "cfdi_number": record.invoice_number,
                "invoice_date": record.invoice_date.isoformat(),
                "uuid": str(record.cfdi_uuid),
                "supplier_name": bill.supplier.name,
                "issuer_rfc": record.issuer_rfc,
                "receiver_rfc": record.receiver_rfc,
                "currency": root.get("Moneda", ""),
                "subtotal": str(subtotal.quantize(Decimal("0.01"))),
                "tax_total": str(declared_tax.quantize(Decimal("0.01"))),
                "taxes": [
                    {"tax_code": v["tax_code"], "rate": v["rate"], "base": str(v["base"].quantize(Decimal("0.01"))), "amount": str(v["amount"].quantize(Decimal("0.01")))}
                    for v in taxes.values()
                ],
                "total": str(total.quantize(Decimal("0.01"))),
                "payable_status": bill.payment_status,
                "review_status": "XML y datos comparados localmente; sello y estado SAT sin verificar",
            })
        except (OSError, etree.XMLSyntaxError, UnicodeError, ArithmeticError, ValueError, TypeError) as error:
            raise ValidationError(f"No se pudo revisar el CFDI de proveedor {record.cfdi_uuid}; confirma el archivo privado almacenado.") from error

    return {
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
        "document_count": len(rows),
        "subtotal": str(subtotal_total.quantize(Decimal("0.01"))),
        "declared_tax_total": str(tax_total.quantize(Decimal("0.01"))),
        "total": str(invoice_total.quantize(Decimal("0.01"))),
        "taxes": [
            {"tax_code": v["tax_code"], "rate": v["rate"], "base": str(v["base"].quantize(Decimal("0.01"))), "amount": str(v["amount"].quantize(Decimal("0.01")))}
            for _, v in sorted(tax_totals.items())
        ],
        "rows": rows,
    }
