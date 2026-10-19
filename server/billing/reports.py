from collections import defaultdict
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from lxml import etree
from django.db.models import Prefetch, Q
from django.utils import timezone

from .models import CustomerCreditNote, CustomerInvoice, FiscalDocument, Payment, PaymentAllocation
from .fiscal.validator import CFDIValidationError, MAX_CFDI_BYTES, require_valid_cfdi_xml


ZERO = Decimal("0.00")
BUCKET_LABELS = {
    "no_due_date": "Sin vencimiento",
    "current": "Vigente",
    "days_1_30": "1–30 días",
    "days_31_60": "31–60 días",
    "days_61_90": "61–90 días",
    "over_90": "Más de 90 días",
}

CFDI_NS = "http://www.sat.gob.mx/cfd/4"
TAX_REGISTER_STATES = [
    FiscalDocument.State.STAMPED,
    FiscalDocument.State.CANCEL_PENDING,
    FiscalDocument.State.CANCEL_REJECTED,
    FiscalDocument.State.CANCELLED,
]


def receivables_aging(as_of=None):
    as_of = as_of or timezone.localdate()
    invoices = (
        CustomerInvoice.objects.filter(
            state__in=[CustomerInvoice.State.OPEN, CustomerInvoice.State.PARTIAL, CustomerInvoice.State.PAID, CustomerInvoice.State.CREDITED],
            issue_date__lte=as_of,
        ).filter(
            Q(opening_balance_batch_id__isnull=True, opened_at__date__lte=as_of)
            | Q(opening_balance_batch_id__isnull=False, opening_cutoff_date__lte=as_of)
        )
        .select_related("customer")
        .prefetch_related(
            "lines",
            Prefetch(
                "credit_notes",
                queryset=CustomerCreditNote.objects.filter(
                    issue_date__lte=as_of, posted_at__date__lte=as_of,
                ).filter(
                    Q(state=CustomerCreditNote.State.POSTED)
                    | Q(state=CustomerCreditNote.State.REVERSED, reversed_at__date__gt=as_of)
                ).prefetch_related("lines__invoice_line"),
                to_attr="as_of_credit_notes",
            ),
            Prefetch(
                "allocations",
                queryset=PaymentAllocation.objects.filter(
                    payment__posted_at__date__lte=as_of,
                    payment__received_at__date__lte=as_of,
                ).filter(
                    Q(payment__state=Payment.State.POSTED)
                    | Q(payment__state=Payment.State.REVERSED, payment__reversed_at__date__gt=as_of)
                ).only(
                    "invoice_id", "amount", "payment_id"
                ),
                to_attr="posted_allocations",
            ),
        )
        .order_by("customer__name", "due_date", "number")
    )
    totals = {key: ZERO for key in BUCKET_LABELS}
    counts = {key: 0 for key in BUCKET_LABELS}
    customer_totals = defaultdict(lambda: {"customer_id": None, "customer_name": "", "balance": ZERO, "invoice_count": 0})
    rows = []

    for invoice in invoices:
        gross = invoice.total
        paid = invoice.opening_paid_before_cutoff + sum((allocation.amount for allocation in invoice.posted_allocations), ZERO)
        credited = sum((note.total for note in invoice.as_of_credit_notes), ZERO)
        balance = max(ZERO, gross - paid - credited)
        if balance <= ZERO:
            continue

        if invoice.due_date is None:
            bucket, overdue_days = "no_due_date", None
        elif invoice.due_date >= as_of:
            bucket, overdue_days = "current", 0
        else:
            overdue_days = (as_of - invoice.due_date).days
            bucket = "days_1_30" if overdue_days <= 30 else "days_31_60" if overdue_days <= 60 else "days_61_90" if overdue_days <= 90 else "over_90"

        totals[bucket] += balance
        counts[bucket] += 1
        customer = customer_totals[invoice.customer_id]
        customer["customer_id"] = str(invoice.customer_id)
        customer["customer_name"] = invoice.customer.name
        customer["balance"] += balance
        customer["invoice_count"] += 1
        rows.append({
            "invoice_id": str(invoice.id),
            "number": invoice.number,
            "customer_id": str(invoice.customer_id),
            "customer_name": invoice.customer.name,
            "issue_date": invoice.issue_date.isoformat(),
            "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
            "overdue_days": overdue_days,
            "bucket": bucket,
            "bucket_label": BUCKET_LABELS[bucket],
            "invoice_total": str(gross.quantize(Decimal("0.01"))),
            "paid_amount": str(paid.quantize(Decimal("0.01"))),
            "credited_amount": str(credited.quantize(Decimal("0.01"))),
            "balance_due": str(balance.quantize(Decimal("0.01"))),
        })

    return {
        "as_of": as_of.isoformat(),
        "currency": "MXN",
        "total_balance": str(sum(totals.values(), ZERO).quantize(Decimal("0.01"))),
        "invoice_count": len(rows),
        "buckets": [
            {"key": key, "label": label, "balance": str(totals[key].quantize(Decimal("0.01"))), "invoice_count": counts[key]}
            for key, label in BUCKET_LABELS.items()
        ],
        "customers": [
            {**item, "balance": str(item["balance"].quantize(Decimal("0.01")))}
            for item in sorted(customer_totals.values(), key=lambda value: value["customer_name"].casefold())
        ],
        "invoices": rows,
    }


def customer_statement(customer, as_of=None):
    """Return an internal AR ledger for one customer through a cutoff date."""
    as_of = as_of or timezone.localdate()
    invoices = (
        CustomerInvoice.objects.filter(
            customer=customer,
            state__in=[CustomerInvoice.State.OPEN, CustomerInvoice.State.PARTIAL, CustomerInvoice.State.PAID, CustomerInvoice.State.CREDITED],
            issue_date__lte=as_of,
        ).filter(
            Q(opening_balance_batch_id__isnull=True, opened_at__date__lte=as_of)
            | Q(opening_balance_batch_id__isnull=False, opening_cutoff_date__lte=as_of)
        )
        .prefetch_related(
            "lines",
            Prefetch(
                "credit_notes",
                queryset=CustomerCreditNote.objects.filter(
                    state__in=[CustomerCreditNote.State.POSTED, CustomerCreditNote.State.REVERSED],
                    issue_date__lte=as_of, posted_at__date__lte=as_of,
                ).prefetch_related("lines__invoice_line"),
                to_attr="statement_credit_notes",
            ),
            Prefetch(
                "allocations",
                queryset=PaymentAllocation.objects.filter(
                    payment__posted_at__date__lte=as_of,
                    payment__received_at__date__lte=as_of,
                ).filter(
                    Q(payment__state=Payment.State.POSTED)
                    | Q(payment__state=Payment.State.REVERSED, payment__reversed_at__date__gt=as_of)
                ).select_related("payment").only(
                    "invoice_id", "amount", "payment_id", "payment__number", "payment__received_at",
                    "payment__reference", "payment__memo", "payment__posted_at", "payment__reversed_at",
                ),
                to_attr="statement_allocations",
            ),
        )
        .order_by("issue_date", "number")
    )

    entries = []
    charged = ZERO
    credited = ZERO
    payment_totals = defaultdict(lambda: {"payment": None, "amount": ZERO})
    credited_notes_total = ZERO
    for invoice in invoices:
        total = invoice.total.quantize(Decimal("0.01"))
        charged += total
        entries.append({
            "date": (invoice.opening_cutoff_date if invoice.opening_balance_batch_id else invoice.issue_date).isoformat(),
            "type": "invoice",
            "document_number": invoice.opening_external_number if invoice.opening_balance_batch_id else invoice.number,
            "description": (f"Saldo inicial · {invoice.opening_source_system}" if invoice.opening_balance_batch_id else invoice.memo or "Factura interna"),
            "debit": total,
            "credit": ZERO,
            "sort_order": 0,
        })

        if invoice.opening_balance_batch_id and invoice.opening_paid_before_cutoff:
            prior_paid = invoice.opening_paid_before_cutoff.quantize(Decimal("0.01"))
            credited += prior_paid
            entries.append({
                "date": invoice.opening_cutoff_date.isoformat(),
                "type": "opening_payment_summary",
                "document_number": invoice.opening_external_number,
                "description": "Pagos previos al corte de apertura (resumen)",
                "debit": ZERO,
                "credit": prior_paid,
                "sort_order": 1,
            })

        for note in invoice.statement_credit_notes:
            amount = note.total.quantize(Decimal("0.01"))
            credited_notes_total += amount
            entries.append({
                "date": note.issue_date.isoformat(),
                "type": "credit_note",
                "document_number": note.number,
                "description": note.reason,
                "debit": ZERO,
                "credit": amount,
                "sort_order": 1,
            })
            if note.state == CustomerCreditNote.State.REVERSED and note.reversed_at and note.reversed_at.date() <= as_of:
                credited_notes_total -= amount
                entries.append({
                    "date": note.reversed_at.date().isoformat(),
                    "type": "credit_note_reversal",
                    "document_number": note.number,
                    "description": note.reversal_reason or "Reversa de nota de crédito",
                    "debit": amount,
                    "credit": ZERO,
                    "sort_order": 3,
                })

        for allocation in invoice.statement_allocations:
            item = payment_totals[allocation.payment_id]
            item["payment"] = allocation.payment
            item["amount"] += allocation.amount

    # Show one statement line per posted receipt, even if it was allocated
    # across multiple invoices for this same customer.
    for item in payment_totals.values():
        payment = item["payment"]
        amount = item["amount"].quantize(Decimal("0.01"))
        credited += amount
        entries.append({
            "date": payment.received_at.date().isoformat(),
            "type": "payment",
            "document_number": payment.number,
            "description": payment.reference or payment.memo or "Cobro aplicado",
            "debit": ZERO,
            "credit": amount,
            "sort_order": 2,
        })

    reversals = Payment.objects.filter(
        customer=customer, state=Payment.State.REVERSED,
        posted_at__date__lte=as_of, received_at__date__lte=as_of,
        reversed_at__date__lte=as_of,
    ).prefetch_related("allocations").order_by("reversed_at", "number")
    for payment in reversals:
        amount = sum((allocation.amount for allocation in payment.allocations.all()), ZERO).quantize(Decimal("0.01"))
        if not amount:
            continue
        credited -= amount
        entries.append({
            "date": payment.reversed_at.date().isoformat(),
            "type": "payment_reversal",
            "document_number": payment.number,
            "description": payment.reversal_reason or "Reversa de cobro",
            "debit": amount,
            "credit": ZERO,
            "sort_order": 4,
        })

    entries.sort(key=lambda row: (row["date"], row["sort_order"], row["document_number"]))
    balance = ZERO
    serialized_entries = []
    for entry in entries:
        balance += entry["debit"] - entry["credit"]
        serialized_entries.append({
            **entry,
            "debit": str(entry["debit"].quantize(Decimal("0.01"))),
            "credit": str(entry["credit"].quantize(Decimal("0.01"))),
            "running_balance": str(balance.quantize(Decimal("0.01"))),
        })
        serialized_entries[-1].pop("sort_order")

    return {
        "customer_id": str(customer.pk),
        "customer_name": customer.name,
        "customer_rfc": customer.rfc,
        "as_of": as_of.isoformat(),
        "currency": "MXN",
        "invoice_count": sum(1 for row in entries if row["type"] == "invoice"),
        "payment_count": len({row["document_number"] for row in entries if row["type"] == "payment"}),
        "total_charged": str(charged.quantize(Decimal("0.01"))),
        "total_paid": str(credited.quantize(Decimal("0.01"))),
        "total_credited": str(credited_notes_total.quantize(Decimal("0.01"))),
        "balance_due": str(balance.quantize(Decimal("0.01"))),
        "entries": serialized_entries,
    }


def issued_cfdi_register(date_from=None, date_to=None):
    """Return a source-linked register of stamped CFDI I/E documents, not a tax filing."""
    documents = FiscalDocument.objects.filter(
        Q(invoice__isnull=False) | Q(credit_note__isnull=False),
        document_type__in=[FiscalDocument.DocumentType.INCOME, FiscalDocument.DocumentType.CREDIT_NOTE],
        state__in=TAX_REGISTER_STATES,
        cfdi_uuid__isnull=False,
    ).exclude(xml_content="").select_related("invoice", "credit_note", "credit_note__invoice", "invoice__customer")
    if date_from:
        documents = documents.filter(Q(invoice__issue_date__gte=date_from) | Q(credit_note__issue_date__gte=date_from))
    if date_to:
        documents = documents.filter(Q(invoice__issue_date__lte=date_to) | Q(credit_note__issue_date__lte=date_to))

    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, recover=False)
    rows = []
    active = {"I": {"subtotal": ZERO, "total": ZERO}, "E": {"subtotal": ZERO, "total": ZERO}}
    cancelled_totals = {"I": {"subtotal": ZERO, "total": ZERO}, "E": {"subtotal": ZERO, "total": ZERO}}
    tax_totals = {"I": defaultdict(lambda: {"tax_code": "", "rate": "", "base": ZERO, "amount": ZERO}),
                  "E": defaultdict(lambda: {"tax_code": "", "rate": "", "base": ZERO, "amount": ZERO})}
    ordered_documents = sorted(
        documents,
        key=lambda item: (
            item.invoice.issue_date if item.invoice_id else item.credit_note.issue_date,
            item.invoice.number if item.invoice_id else item.credit_note.number,
            str(item.pk),
        ),
    )
    state_labels = {
        FiscalDocument.State.STAMPED: "Timbrado",
        FiscalDocument.State.CANCEL_PENDING: "Cancelación pendiente",
        FiscalDocument.State.CANCEL_REJECTED: "Cancelación rechazada",
        FiscalDocument.State.CANCELLED: "Cancelado",
    }
    for document in ordered_documents:
        try:
            xml_data = document.xml_content.encode("utf-8")
            if not xml_data or len(xml_data) > MAX_CFDI_BYTES:
                raise ValueError("XML vacío o excede el tamaño permitido")
            require_valid_cfdi_xml(xml_data)
            root = etree.fromstring(xml_data, parser)
            if (root.tag != f"{{{CFDI_NS}}}Comprobante" or root.get("Version") != "4.0"
                    or root.get("TipoDeComprobante") != document.document_type):
                raise ValueError("raíz, versión o tipo CFDI no coinciden con el registro")
            subtotal = Decimal(root.get("SubTotal", ""))
            total = Decimal(root.get("Total", ""))
            expected_source = document.invoice if document.invoice_id else document.credit_note
            expected_subtotal = expected_source.subtotal
            expected_total = expected_source.total
            if (root.get("Moneda") != document.currency or subtotal != expected_subtotal
                    or total != expected_total):
                raise ValueError("moneda, subtotal o total no coincide con el documento interno relacionado")
            issuer = root.find(f"{{{CFDI_NS}}}Emisor")
            recipient = root.find(f"{{{CFDI_NS}}}Receptor")
            timbre = root.find(f".//{{http://www.sat.gob.mx/TimbreFiscalDigital}}TimbreFiscalDigital")
            if issuer is None or issuer.get("Rfc", "").upper() != document.issuer_rfc.upper():
                raise ValueError("RFC emisor no coincide con el registro fiscal")
            if recipient is None or recipient.get("Rfc", "").upper() != document.recipient_rfc.upper():
                raise ValueError("RFC receptor no coincide con el registro fiscal")
            if timbre is None or timbre.get("UUID", "").upper() != str(document.cfdi_uuid).upper():
                raise ValueError("UUID del timbre no coincide con el registro fiscal")
            if document.document_type == FiscalDocument.DocumentType.CREDIT_NOTE:
                relation = root.find(f"{{{CFDI_NS}}}CfdiRelacionados")
                related_nodes = root.findall(f"{{{CFDI_NS}}}CfdiRelacionados/{{{CFDI_NS}}}CfdiRelacionado")
                expected_uuid = str(document.request_payload.get("related_cfdi_uuid", "")).upper()
                if (relation is None or relation.get("TipoRelacion") != document.request_payload.get("relation_type")
                        or [node.get("UUID", "").upper() for node in related_nodes] != [expected_uuid]):
                    raise ValueError("CFDI relacionados no coinciden con el snapshot de la nota de crédito")
            taxes = {}
            for transfer in root.findall(f"{{{CFDI_NS}}}Impuestos/{{{CFDI_NS}}}Traslados/{{{CFDI_NS}}}Traslado"):
                tax_code = transfer.get("Impuesto", "")
                factor = transfer.get("TipoFactor", "")
                rate = "Exento" if factor == "Exento" else transfer.get("TasaOCuota", "")
                key = (tax_code, rate)
                value = taxes.setdefault(key, {"tax_code": tax_code, "rate": rate, "base": ZERO, "amount": ZERO})
                value["base"] += Decimal(transfer.get("Base", "0"))
                value["amount"] += Decimal(transfer.get("Importe", "0"))
            cancelled = document.state == FiscalDocument.State.CANCELLED
            bucket = cancelled_totals if cancelled else active
            bucket[document.document_type]["subtotal"] += subtotal
            bucket[document.document_type]["total"] += total
            if not cancelled:
                for key, value in taxes.items():
                    aggregate = tax_totals[document.document_type][key]
                    aggregate["tax_code"] = value["tax_code"]
                    aggregate["rate"] = value["rate"]
                    aggregate["base"] += value["base"]
                    aggregate["amount"] += value["amount"]
            source = expected_source
            related_nodes = root.findall(f"{{{CFDI_NS}}}CfdiRelacionados/{{{CFDI_NS}}}CfdiRelacionado")
            rows.append({
                "fiscal_document_id": str(document.pk),
                "document_type": document.document_type,
                "document_type_label": "Ingreso" if document.document_type == "I" else "Egreso",
                "source_number": source.number,
                "invoice_number": source.number,
                "related_uuids": [item.get("UUID", "").upper() for item in related_nodes],
                "issue_date": source.issue_date.isoformat(),
                "stamped_at": document.stamped_at.isoformat() if document.stamped_at else None,
                "uuid": str(document.cfdi_uuid),
                "state": document.state,
                "state_label": state_labels[document.state],
                "issuer_rfc": document.issuer_rfc,
                "recipient_rfc": document.recipient_rfc,
                "recipient_name": document.recipient_name,
                "series": root.get("Serie", ""),
                "folio": root.get("Folio", ""),
                "currency": root.get("Moneda", ""),
                "subtotal": str(subtotal.quantize(Decimal("0.01"))),
                "taxes": [
                    {"tax_code": v["tax_code"], "rate": v["rate"], "base": str(v["base"].quantize(Decimal("0.01"))), "amount": str(v["amount"].quantize(Decimal("0.01")))}
                    for v in taxes.values()
                ],
                "total": str(total.quantize(Decimal("0.01"))),
                "cancelled": cancelled,
            })
        except (CFDIValidationError, etree.XMLSyntaxError, UnicodeError, InvalidOperation, ValueError, TypeError) as error:
            raise ValidationError(f"No se pudo leer el CFDI timbrado {document.cfdi_uuid}; revisa su XML almacenado.") from error

    return {
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
        "document_count": len(rows),
        "active_count": sum(1 for row in rows if not row["cancelled"]),
        "cancelled_count": sum(1 for row in rows if row["cancelled"]),
        "income_active_subtotal": str(active["I"]["subtotal"].quantize(Decimal("0.01"))),
        "income_active_total": str(active["I"]["total"].quantize(Decimal("0.01"))),
        "egress_active_subtotal": str(active["E"]["subtotal"].quantize(Decimal("0.01"))),
        "egress_active_total": str(active["E"]["total"].quantize(Decimal("0.01"))),
        "active_subtotal": str(sum((value["subtotal"] for value in active.values()), ZERO).quantize(Decimal("0.01"))),
        "active_total": str(sum((value["total"] for value in active.values()), ZERO).quantize(Decimal("0.01"))),
        "cancelled_subtotal": str(sum((value["subtotal"] for value in cancelled_totals.values()), ZERO).quantize(Decimal("0.01"))),
        "cancelled_total": str(sum((value["total"] for value in cancelled_totals.values()), ZERO).quantize(Decimal("0.01"))),
        "cancelled_income_total": str(cancelled_totals["I"]["total"].quantize(Decimal("0.01"))),
        "cancelled_egress_total": str(cancelled_totals["E"]["total"].quantize(Decimal("0.01"))),
        "income_taxes": [
            {"tax_code": v["tax_code"], "rate": v["rate"], "base": str(v["base"].quantize(Decimal("0.01"))), "amount": str(v["amount"].quantize(Decimal("0.01")))}
            for _, v in sorted(tax_totals["I"].items())
        ],
        "egress_taxes": [
            {"tax_code": v["tax_code"], "rate": v["rate"], "base": str(v["base"].quantize(Decimal("0.01"))), "amount": str(v["amount"].quantize(Decimal("0.01")))}
            for _, v in sorted(tax_totals["E"].items())
        ],
        "rows": rows,
    }
