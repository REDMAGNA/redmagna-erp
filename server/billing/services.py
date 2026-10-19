from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
import base64
import binascii
import re
import uuid

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.mail import EmailMultiAlternatives
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from .cfdi_payment import allocate_payment_taxes, issued_invoice_tax_basis, summarize_payment_taxes
from .fiscal.cfdi40 import build_signed_credit_note_cfdi, build_signed_income_cfdi
from .fiscal.cfdi_payment20 import (
    PaymentCFDIError,
    build_signed_payment_cfdi,
    require_valid_payment_cfdi_xml,
    validate_payment_cfdi_snapshot,
)
from .fiscal.catalogs import is_sat_catalog_value
from .models import CustomerCreditNote, CustomerCreditNoteLine, CustomerInvoice, FiscalDocument, FiscalEvent, InvoiceLine, Payment, PaymentAllocation


def query_fiscal_document(document_id, actor):
    """Query an uncertain FEL submission by its persisted reference, never resubmit it."""
    from .providers.fel import FELConfigurationError, FELTransportError, query_cancellation_status, query_stamp_by_reference

    document = FiscalDocument.objects.get(pk=document_id)
    if document.state == FiscalDocument.State.CANCEL_PENDING:
        if document.provider_code != "fel-premium" or not document.cfdi_uuid:
            raise ValidationError("La consulta de cancelación requiere un UUID timbrado de FEL.")
        try:
            result = query_cancellation_status(document.cfdi_uuid)
        except (FELConfigurationError, FELTransportError) as error:
            FiscalEvent.objects.create(
                fiscal_document=document,
                action=FiscalEvent.Action.QUERY,
                state_before=document.state,
                state_after=document.state,
                response_code="transport_or_configuration_error",
                response_payload={"message": str(error)[:500], "status_remains_pending": True},
                actor=actor,
            )
            raise
        before = document.state
        expected_uuid = str(document.cfdi_uuid).replace("-", "").casefold()
        returned_uuid = str(result.cfdi_uuid or "").replace("-", "").casefold()
        uuid_matches = bool(expected_uuid and returned_uuid and returned_uuid == expected_uuid)
        confirmed_cancelled = (
            result.succeeded
            and uuid_matches
            and result.status.strip().casefold() == "cancelado"
        )
        if confirmed_cancelled:
            document.state = FiscalDocument.State.CANCELLED
            document.save(update_fields=["state"])
        FiscalEvent.objects.create(
            fiscal_document=document,
            action=FiscalEvent.Action.QUERY,
            state_before=before,
            state_after=document.state,
            response_code=result.response_code,
            response_payload={
                "message": result.message,
                "status": result.status,
                "operation_succeeded": result.succeeded,
                "returned_uuid": result.cfdi_uuid,
                "uuid_matches_document": uuid_matches,
                "cancellation_confirmed": confirmed_cancelled,
            },
            actor=actor,
        )
        return document
    if document.state != FiscalDocument.State.SUBMITTED:
        raise ValidationError("Solo un comprobante enviado puede consultarse por referencia.")
    if document.provider_code != "fel-premium":
        raise ValidationError("La consulta por referencia solo está disponible para FEL Premium.")
    reference = document.provider_request_id.strip()
    if len(reference) < 4:
        raise ValidationError("El comprobante enviado no conserva una referencia FEL válida.")

    def record_query(code, payload):
        FiscalEvent.objects.create(
            fiscal_document=document,
            action=FiscalEvent.Action.QUERY,
            state_before=document.state,
            state_after=document.state,
            provider_request_id=reference,
            response_code=code,
            response_payload=payload,
            actor=actor,
        )

    try:
        result = query_stamp_by_reference(reference)
    except (FELConfigurationError, FELTransportError) as error:
        record_query("transport_or_configuration_error", {"message": str(error)[:500]})
        raise

    if not result.succeeded:
        record_query(result.response_code, {"message": result.message[:500], "operation_succeeded": False})
        return document
    if not result.cfdi_uuid or not result.xml_content:
        record_query(result.response_code or "incomplete_result", {"message": "La consulta respondió sin UUID o XML.", "found": True})
        raise ValidationError("FEL encontró una referencia, pero la respuesta no contiene UUID y XML completos.")

    record_query(result.response_code, {"found": True, "cfdi_uuid": result.cfdi_uuid, "status": result.status})
    return record_stamp(
        document.pk, actor, result.cfdi_uuid, result.xml_content,
        provider_request_id=reference, response_code=result.response_code,
        response_payload={"source": "reference_query", "status": result.status},
        pdf_base64=result.pdf_base64,
    )


MAX_FEL_PDF_BYTES = 4 * 1024 * 1024
CFDI_NS = "http://www.sat.gob.mx/cfd/4"
TFD_NS = "http://www.sat.gob.mx/TimbreFiscalDigital"
XSI_SCHEMA_LOCATION = "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation"


class CustomerCopyDeliveryError(Exception):
    """The mail transport did not confirm the customer's fiscal copy."""


def send_fiscal_copy_to_customer(document_id, actor):
    """Email a stamped CFDI to its registered customer contact and audit the attempt."""
    from django.conf import settings

    document = FiscalDocument.objects.select_related(
        "invoice__customer", "credit_note__invoice__customer", "payment__customer",
    ).get(pk=document_id)
    if document.state != FiscalDocument.State.STAMPED:
        raise ValidationError("Solo un CFDI timbrado y vigente puede enviarse al cliente.")
    if not document.xml_content or not document.cfdi_uuid:
        raise ValidationError("El CFDI timbrado debe conservar su UUID y XML antes de enviarlo.")

    if document.payment_id:
        customer = document.payment.customer
    elif document.credit_note_id:
        customer = document.credit_note.invoice.customer
    else:
        customer = document.invoice.customer
    recipient = (customer.email or "").strip()
    if not recipient:
        raise ValidationError("Registra un correo en la ficha del cliente antes de enviar el CFDI.")

    attachments = []
    message = EmailMultiAlternatives(
        subject=f"CFDI timbrado {document.cfdi_uuid} · Redmagna",
        body=(
            f"Hola {customer.name},\n\n"
            f"Adjuntamos el comprobante fiscal timbrado {document.cfdi_uuid}. "
            "Conserva el XML como comprobante fiscal.\n\nRedmagna"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
    )
    message.attach(f"CFDI-{document.cfdi_uuid}.xml", document.xml_content, "application/xml")
    attachments.append("xml")
    expected_key = f"fiscal_documents/{document.pk}/{document.pk}.pdf"
    if document.pdf_storage_key == expected_key:
        try:
            with default_storage.open(expected_key, "rb") as pdf_file:
                pdf_bytes = pdf_file.read(MAX_FEL_PDF_BYTES + 1)
            if pdf_bytes.startswith(b"%PDF-") and len(pdf_bytes) <= MAX_FEL_PDF_BYTES:
                message.attach(f"CFDI-{document.cfdi_uuid}.pdf", pdf_bytes, "application/pdf")
                attachments.append("pdf")
        except OSError:
            pass

    try:
        delivered = message.send(fail_silently=False)
        if delivered != 1:
            raise RuntimeError("El servidor de correo no confirmó la aceptación del mensaje.")
    except Exception as error:
        FiscalEvent.objects.create(
            fiscal_document=document,
            action=FiscalEvent.Action.ERROR,
            state_before=document.state,
            state_after=document.state,
            response_code="customer_copy_email_uncertain",
            response_payload={
                "type": "customer_copy_email",
                "recipient": recipient,
                "attachments": attachments,
                "error": type(error).__name__[:120],
                "delivery_may_be_uncertain": True,
            },
            actor=actor,
        )
        raise CustomerCopyDeliveryError(
            "El servidor de correo no confirmó el envío. Revisa el correo y la bitácora antes de volver a intentarlo."
        ) from error

    FiscalEvent.objects.create(
        fiscal_document=document,
        action=FiscalEvent.Action.RESPONSE,
        state_before=document.state,
        state_after=document.state,
        response_code="customer_copy_email_sent",
        response_payload={
            "type": "customer_copy_email",
            "recipient": recipient,
            "attachments": attachments,
        },
        actor=actor,
    )
    return document


def _cfdi_business_tree(node):
    """Represent the signed CFDI content, excluding only PAC-added stamp metadata."""
    if node.tag == f"{{{TFD_NS}}}TimbreFiscalDigital":
        return None
    children = tuple(
        child_tree
        for child in node
        if (child_tree := _cfdi_business_tree(child)) is not None
    )
    if node.tag == f"{{{CFDI_NS}}}Complemento" and not children:
        return None
    attributes = tuple(sorted(
        (name, value)
        for name, value in node.attrib.items()
        if name != XSI_SCHEMA_LOCATION
    ))
    text = node.text or ""
    if not text.strip():
        text = ""
    return node.tag, attributes, text, children


def _store_fel_pdf(document_id, pdf_base64):
    if not pdf_base64:
        return "", "not_returned"
    encoded = re.sub(r"\s+", "", str(pdf_base64))
    if len(encoded) > ((MAX_FEL_PDF_BYTES + 2) // 3) * 4:
        return "", "too_large"
    try:
        pdf_bytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return "", "invalid_base64"
    if not pdf_bytes or len(pdf_bytes) > MAX_FEL_PDF_BYTES or not pdf_bytes.startswith(b"%PDF-"):
        return "", "invalid_pdf"

    key = f"fiscal_documents/{document_id}/{document_id}.pdf"
    try:
        if default_storage.exists(key):
            default_storage.delete(key)
        saved_key = default_storage.save(key, ContentFile(pdf_bytes))
        if saved_key != key:
            default_storage.delete(saved_key)
            return "", "storage_key_conflict"
    except Exception:
        return "", "storage_error"
    return key, "stored"


@transaction.atomic
def open_invoice(invoice_id, actor):
    invoice = CustomerInvoice.objects.select_for_update().get(pk=invoice_id)
    if invoice.state != CustomerInvoice.State.DRAFT:
        raise ValidationError("Solo un borrador puede abrirse en cuentas por cobrar.")
    if not invoice.lines.exists():
        raise ValidationError("Agrega conceptos antes de abrir la cuenta por cobrar.")
    if invoice.total <= Decimal("0.00"):
        raise ValidationError("El total de la factura debe ser mayor que cero.")
    if invoice.due_date and invoice.due_date < invoice.issue_date:
        raise ValidationError("El vencimiento no puede ser anterior a la fecha de emisión.")

    invoice.state = CustomerInvoice.State.OPEN
    invoice.opened_by = actor
    invoice.opened_at = timezone.now()
    invoice.save(update_fields=["state", "opened_by", "opened_at"])
    from accounting.models import PostingConfiguration
    from accounting.posting import create_source_draft
    create_source_draft(
        PostingConfiguration.EventType.CUSTOMER_INVOICE,
        invoice.id,
        actor,
        invoice.issue_date,
        f"Factura interna {invoice.number} · {invoice.customer.name}",
        invoice.total,
        base_amount=invoice.subtotal,
        tax_amount=invoice.tax_total,
    )
    return invoice


@transaction.atomic
def create_invoice_from_work_order(work_order_id, actor, lines=None):
    from sales.models import QuoteLine, SalesOrder, WorkOrder

    work_order = WorkOrder.objects.select_for_update().select_related("sales_order__quote__customer").get(pk=work_order_id)
    if work_order.status == WorkOrder.Status.CANCELLED:
        raise ValidationError("No se pueden facturar avances de una orden de trabajo cancelada.")
    sales_order = SalesOrder.objects.select_for_update().get(pk=work_order.sales_order_id)
    existing_invoices = list(CustomerInvoice.objects.select_for_update().filter(sales_order=sales_order).order_by("id"))
    if InvoiceLine.objects.filter(invoice__in=existing_invoices, quote_line__isnull=True).exists():
        raise ValidationError("Hay una factura anterior de esta orden sin vínculo a sus conceptos. Revisa y relaciona esa factura antes de continuar.")

    quote = sales_order.quote
    quote_lines = list(QuoteLine.objects.select_for_update().filter(quote=quote).order_by("id"))
    if not quote_lines:
        raise ValidationError("La cotización aprobada no tiene conceptos para facturar.")
    billed = dict(InvoiceLine.objects.filter(invoice__sales_order=sales_order, quote_line__isnull=False)
        .values("quote_line_id").annotate(quantity=Sum("quantity")).values_list("quote_line_id", "quantity"))
    remaining = {line.id: line.billable_quantity - billed.get(line.id, Decimal("0.000")) for line in quote_lines}
    if any(quantity < 0 for quantity in remaining.values()):
        raise ValidationError("Una factura anterior excede las cantidades de la cotización; revisa las facturas antes de continuar.")
    if lines:
        requested = {item["quote_line"].pk: item["quantity"] for item in lines}
        quote_line_ids = {line.id for line in quote_lines}
        if not set(requested).issubset(quote_line_ids):
            raise ValidationError({"lines": "Selecciona conceptos que pertenezcan a la cotización aprobada."})
    else:
        requested = {line.id: remaining[line.id] for line in quote_lines if remaining[line.id] > 0}
    selected = []
    quote_by_id = {line.id: line for line in quote_lines}
    for quote_line_id, quantity in requested.items():
        if quantity <= 0:
            raise ValidationError({"lines": "La cantidad a facturar debe ser mayor que cero."})
        if quantity > remaining[quote_line_id]:
            raise ValidationError({"lines": f"La cantidad excede lo pendiente por facturar para el concepto {quote_by_id[quote_line_id].description}."})
        selected.append((quote_by_id[quote_line_id], quantity))
    if not selected:
        raise ValidationError("No quedan cantidades pendientes por facturar en esta orden.")

    invoice_issue_date = timezone.localdate()
    invoice = CustomerInvoice.objects.create(
        customer=quote.customer,
        sales_order=sales_order,
        currency="MXN",
        issue_date=invoice_issue_date,
        due_date=(invoice_issue_date + timedelta(days=quote.payment_term_days)) if quote.payment_term_days is not None else None,
        memo=f"Factura de orden de venta {quote.number}",
        created_by=actor,
    )
    for line_number, (quote_line, quantity) in enumerate(selected, start=1):
        InvoiceLine.objects.create(
            invoice=invoice,
            quote_line=quote_line,
            line_number=line_number,
            catalog_product=quote_line.catalog_product,
            description=quote_line.description,
            quantity=quantity,
            unit_price=quote_line.unit_price,
            discount_percent=quote_line.discount_percent,
            tax_rate=quote_line.tax_rate,
        )
    return invoice


@transaction.atomic
def post_payment(payment_id, actor):
    payment = Payment.objects.select_for_update().get(pk=payment_id)
    if payment.state != Payment.State.DRAFT:
        raise ValidationError("Solo un cobro en borrador puede aplicarse.")

    allocations = list(payment.allocations.select_for_update().select_related("invoice").order_by("invoice_id"))
    if not allocations:
        raise ValidationError("Agrega al menos una factura al cobro.")
    allocated = sum((item.amount for item in allocations), Decimal("0.00"))
    if allocated != payment.amount:
        raise ValidationError("El importe del cobro debe quedar aplicado exactamente a facturas en esta versión.")

    invoice_ids = sorted({item.invoice_id for item in allocations}, key=str)
    locked_invoices = {
        invoice.id: invoice
        for invoice in CustomerInvoice.objects.select_for_update().filter(id__in=invoice_ids).order_by("id")
    }
    by_invoice = {}
    for allocation in allocations:
        invoice = locked_invoices.get(allocation.invoice_id)
        if invoice is None:
            raise ValidationError("No se encontró una factura asociada al cobro.")
        if invoice.state not in [CustomerInvoice.State.OPEN, CustomerInvoice.State.PARTIAL]:
            raise ValidationError(f"La factura {invoice.number} no está abierta para recibir pagos.")
        if invoice.customer_id != payment.customer_id or invoice.currency != payment.currency:
            raise ValidationError("Cliente y moneda del cobro deben coincidir con cada factura aplicada.")
        by_invoice[invoice.id] = by_invoice.get(invoice.id, Decimal("0.00")) + allocation.amount

    for invoice_id, amount in by_invoice.items():
        invoice = locked_invoices[invoice_id]
        if amount > invoice.balance_due:
            raise ValidationError(f"El pago excede el saldo de la factura {invoice.number}.")

    payment.state = Payment.State.POSTED
    payment.posted_by = actor
    payment.posted_at = timezone.now()
    payment.save(update_fields=["state", "posted_by", "posted_at"])

    for invoice in locked_invoices.values():
        invoice.state = (
            CustomerInvoice.State.CREDITED if invoice.balance_due == Decimal("0.00") and invoice.credited_amount > 0
            else CustomerInvoice.State.PAID if invoice.balance_due == Decimal("0.00")
            else CustomerInvoice.State.PARTIAL
        )
        invoice.save(update_fields=["state"])
    from accounting.models import PostingConfiguration
    from accounting.posting import create_source_draft
    create_source_draft(
        PostingConfiguration.EventType.CUSTOMER_PAYMENT,
        payment.id,
        actor,
        payment.received_at.date(),
        f"Cobro {payment.number} · {payment.customer.name}",
        payment.amount,
    )
    return payment


@transaction.atomic
def post_customer_credit_note(credit_note_id, actor):
    note = CustomerCreditNote.objects.select_for_update().select_related("invoice__customer").get(pk=credit_note_id)
    if note.state != CustomerCreditNote.State.DRAFT:
        raise ValidationError("Solo se puede aplicar una nota de crédito en borrador.")
    invoice = CustomerInvoice.objects.select_for_update().get(pk=note.invoice_id)
    if invoice.state not in [CustomerInvoice.State.OPEN, CustomerInvoice.State.PARTIAL, CustomerInvoice.State.PAID, CustomerInvoice.State.CREDITED]:
        raise ValidationError("La factura origen debe estar abierta o liquidada para aplicar una nota.")
    if invoice.opening_balance_batch_id:
        raise ValidationError("Las facturas migradas solo conservan saldo operativo; importa y revisa su detalle fiscal antes de emitir una nota de crédito.")
    lines = list(note.lines.select_for_update().select_related("invoice_line").order_by("line_number"))
    if not lines:
        raise ValidationError("Agrega al menos un concepto de la factura origen.")

    requested_by_line = {}
    for line in lines:
        if line.invoice_line.invoice_id != invoice.id:
            raise ValidationError("Todos los conceptos deben pertenecer a la factura origen.")
        requested_by_line[line.invoice_line_id] = requested_by_line.get(line.invoice_line_id, Decimal("0.000")) + line.quantity
    for invoice_line_id, quantity in requested_by_line.items():
        already_credited = CustomerCreditNoteLine.objects.filter(
            invoice_line_id=invoice_line_id,
            credit_note__state=CustomerCreditNote.State.POSTED,
        ).aggregate(total=Sum("quantity"))["total"] or Decimal("0.000")
        source_line = next(line.invoice_line for line in lines if line.invoice_line_id == invoice_line_id)
        if already_credited + quantity > source_line.quantity:
            raise ValidationError(f"La cantidad acreditada excedería el concepto original: {source_line.description}.")

    subtotal = sum((line.line_subtotal for line in lines), Decimal("0.00"))
    tax_total = sum((line.tax_amount for line in lines), Decimal("0.00"))
    total = subtotal + tax_total
    if total <= 0:
        raise ValidationError("El importe de la nota debe ser mayor que cero.")
    if total > invoice.balance_due:
        raise ValidationError("La nota excede el saldo pendiente; reembolsos y saldos a favor aún no están disponibles.")

    note.state = CustomerCreditNote.State.POSTED
    note.posted_by = actor
    note.posted_at = timezone.now()
    note.save(update_fields=["state", "posted_by", "posted_at"])

    invoice.refresh_from_db()
    invoice.state = CustomerInvoice.State.CREDITED if invoice.balance_due == Decimal("0.00") else CustomerInvoice.State.PARTIAL
    invoice.save(update_fields=["state"])

    from accounting.models import PostingConfiguration
    from accounting.posting import create_source_draft
    create_source_draft(
        PostingConfiguration.EventType.CUSTOMER_CREDIT_NOTE,
        note.id,
        actor,
        note.issue_date,
        f"Nota de crédito {note.number} · {invoice.number}",
        total,
        base_amount=subtotal,
        tax_amount=tax_total,
    )
    return note


@transaction.atomic
def reverse_customer_credit_note(credit_note_id, actor, reason, confirm_irreversible):
    note = CustomerCreditNote.objects.select_for_update().select_related("invoice").get(pk=credit_note_id)
    if not confirm_irreversible:
        raise ValidationError("Confirma que la nota de crédito no debe conservar efecto en la cuenta por cobrar.")
    if note.state != CustomerCreditNote.State.POSTED:
        raise ValidationError("Solo se pueden revertir notas de crédito aplicadas que todavía no estén revertidas.")
    reason = (reason or "").strip()
    if len(reason) < 10:
        raise ValidationError({"reason": "Escribe un motivo de al menos 10 caracteres."})
    active_cfdi_states = [
        FiscalDocument.State.PREPARED, FiscalDocument.State.SUBMITTED,
        FiscalDocument.State.STAMPED, FiscalDocument.State.CANCEL_PENDING,
        FiscalDocument.State.CANCEL_REJECTED,
    ]
    if note.fiscal_documents.filter(state__in=active_cfdi_states).exists():
        raise ValidationError("Cancela primero en FEL el CFDI de egreso preparado, timbrado o pendiente; después revierte la nota interna.")

    from accounting.models import JournalEntry
    from accounting.services import reverse_entry
    journal_entry = JournalEntry.objects.select_for_update().filter(
        origin_type="billing_customer_credit_note", origin_id=note.id,
    ).first()
    if journal_entry and journal_entry.state == JournalEntry.State.DRAFT:
        raise ValidationError("La póliza de la nota sigue en borrador. Contabilidad debe contabilizarla o corregirla antes de revertirla.")
    if journal_entry and journal_entry.state == JournalEntry.State.POSTED:
        reverse_entry(journal_entry.id, actor, authorized_customer_credit_note=True)

    note.state = CustomerCreditNote.State.REVERSED
    note.reversed_by = actor
    note.reversed_at = timezone.now()
    note.reversal_reason = reason
    note.save(update_fields=["state", "reversed_by", "reversed_at", "reversal_reason"])

    invoice = CustomerInvoice.objects.select_for_update().get(pk=note.invoice_id)
    paid = invoice.paid_amount
    credited = invoice.credited_amount
    invoice.state = (
        CustomerInvoice.State.CREDITED if credited and invoice.balance_due == Decimal("0.00")
        else CustomerInvoice.State.PAID if invoice.balance_due == Decimal("0.00")
        else CustomerInvoice.State.PARTIAL if paid > 0 or credited > 0
        else CustomerInvoice.State.OPEN
    )
    invoice.save(update_fields=["state"])
    return note


@transaction.atomic
def reverse_payment(payment_id, actor, reason, confirm_irreversible):
    payment = Payment.objects.select_for_update().select_related("customer").get(pk=payment_id)
    if not confirm_irreversible:
        raise ValidationError("Confirma que el pago fue devuelto o cancelado antes de registrar la reversa.")
    if payment.state != Payment.State.POSTED:
        raise ValidationError("Solo se pueden revertir cobros aplicados que todavía no estén revertidos.")
    reason = (reason or "").strip()
    if len(reason) < 10:
        raise ValidationError({"reason": "Escribe un motivo de al menos 10 caracteres."})

    active_fiscal_states = [
        FiscalDocument.State.SUBMITTED,
        FiscalDocument.State.STAMPED,
        FiscalDocument.State.CANCEL_PENDING,
        FiscalDocument.State.CANCEL_REJECTED,
    ]
    if payment.fiscal_documents.filter(state__in=active_fiscal_states).exists():
        raise ValidationError("Cancela primero en FEL el complemento de pago timbrado o pendiente; después revierte el cobro.")

    allocations = list(payment.allocations.select_for_update().select_related("invoice").order_by("invoice_id"))
    invoice_ids = sorted({allocation.invoice_id for allocation in allocations}, key=str)
    invoices = list(CustomerInvoice.objects.select_for_update().filter(pk__in=invoice_ids).order_by("id"))

    from accounting.models import JournalEntry
    from accounting.services import reverse_entry
    journal_entry = JournalEntry.objects.select_for_update().filter(origin_type="customer_payment", origin_id=payment.id).first()
    if journal_entry and journal_entry.state == JournalEntry.State.DRAFT:
        raise ValidationError("La póliza del cobro sigue en borrador. Contabilidad debe contabilizarla o corregirla antes de revertir el pago.")
    if journal_entry and journal_entry.state == JournalEntry.State.POSTED:
        reverse_entry(journal_entry.id, actor, authorized_customer_payment=True)

    payment.state = Payment.State.REVERSED
    payment.reversed_by = actor
    payment.reversed_at = timezone.now()
    payment.reversal_reason = reason
    payment.save(update_fields=["state", "reversed_by", "reversed_at", "reversal_reason"])

    for invoice in invoices:
        if invoice.state in [CustomerInvoice.State.OPEN, CustomerInvoice.State.PARTIAL, CustomerInvoice.State.PAID, CustomerInvoice.State.CREDITED]:
            paid = invoice.paid_amount
            credited = invoice.credited_amount
            invoice.state = (
                CustomerInvoice.State.CREDITED if credited and invoice.balance_due == Decimal("0.00")
                else CustomerInvoice.State.PAID if invoice.balance_due == Decimal("0.00")
                else CustomerInvoice.State.PARTIAL if paid > 0 or credited > 0
                else CustomerInvoice.State.OPEN
            )
            invoice.save(update_fields=["state"])
    return payment


@transaction.atomic
def submit_fiscal_document(document_id, actor, provider_request_id=""):
    document = FiscalDocument.objects.select_for_update().get(pk=document_id)
    if document.state != FiscalDocument.State.PREPARED:
        raise ValidationError("Solo un comprobante preparado puede enviarse al PAC.")
    if not document.request_xml:
        raise ValidationError("Genera y firma el XML CFDI antes de enviarlo al PAC.")
    if not provider_request_id or len(provider_request_id.strip()) < 4:
        raise ValidationError("Guarda la referencia FEL usada para el envío antes de marcarlo como enviado.")
    provider_request_id = provider_request_id.strip()
    before = document.state
    document.state = FiscalDocument.State.SUBMITTED
    document.provider_request_id = provider_request_id
    document.save(update_fields=["state", "provider_request_id"])
    FiscalEvent.objects.create(
        fiscal_document=document,
        action=FiscalEvent.Action.SUBMIT,
        state_before=before,
        state_after=document.state,
        provider_request_id=provider_request_id,
        actor=actor,
    )
    return document


def send_fiscal_document(document_id, actor):
    """Submit the persisted signed XML once; uncertain outcomes stay queryable."""
    from django.conf import settings
    from .fiscal.validator import CFDIValidationError, require_valid_cfdi_xml
    from .providers.fel import (
        FELConfigurationError, FELTransportError, stamp_cfdi, validate_fel_configuration,
    )

    document = FiscalDocument.objects.get(pk=document_id)
    if document.state != FiscalDocument.State.PREPARED:
        raise ValidationError("Solo un CFDI preparado puede enviarse; si ya está enviado, consulta su referencia FEL.")
    supported_source = (
        (document.document_type == FiscalDocument.DocumentType.INCOME and document.invoice_id)
        or (document.document_type == FiscalDocument.DocumentType.CREDIT_NOTE and document.credit_note_id)
        or (document.document_type == FiscalDocument.DocumentType.PAYMENT and document.payment_id)
    )
    if not supported_source:
        raise ValidationError("El comprobante no corresponde a una factura, nota o cobro compatible con FEL.")
    if document.payment_id and document.payment.state != Payment.State.POSTED:
        raise ValidationError("Solo un cobro aplicado y no revertido puede enviarse a FEL.")
    if document.credit_note_id and document.credit_note.state != CustomerCreditNote.State.POSTED:
        raise ValidationError("La nota interna debe seguir aplicada para poder enviar su CFDI de egreso a FEL.")
    if document.provider_code != "fel-premium":
        raise ValidationError("El proveedor del CFDI no es FEL Premium.")
    if not document.request_xml:
        raise ValidationError("Genera y firma el XML antes de enviarlo a FEL.")
    try:
        validate_fel_configuration()
        validator = require_valid_payment_cfdi_xml if document.document_type == FiscalDocument.DocumentType.PAYMENT else require_valid_cfdi_xml
        validator(document.request_xml)
    except (FELConfigurationError, CFDIValidationError) as error:
        raise ValidationError(str(error)) from error

    # The same reference is used on every recovery/query path. Once committed
    # as submitted, this action can never submit the document a second time.
    reference = f"RM-{document.idempotency_key.hex.upper()}"
    document = submit_fiscal_document(document.pk, actor, reference)
    try:
        result = stamp_cfdi(document.request_xml, reference)
    except FELTransportError as error:
        FiscalEvent.objects.create(
            fiscal_document=document,
            action=FiscalEvent.Action.ERROR,
            state_before=FiscalDocument.State.SUBMITTED,
            state_after=FiscalDocument.State.SUBMITTED,
            provider_request_id=reference,
            response_code="transport_uncertain",
            response_payload={"message": str(error)[:300], "query_reference_before_retry": True},
            actor=actor,
        )
        raise
    except FELConfigurationError as error:
        # The preflight already checked settings; if they change between the
        # check and call, keep the same reference for a safe later query.
        FiscalEvent.objects.create(
            fiscal_document=document,
            action=FiscalEvent.Action.ERROR,
            state_before=FiscalDocument.State.SUBMITTED,
            state_after=FiscalDocument.State.SUBMITTED,
            provider_request_id=reference,
            response_code="configuration_changed",
            response_payload={"message": str(error)[:300]},
            actor=actor,
        )
        raise

    if not result.succeeded:
        return record_fiscal_rejection(
            document.pk, actor, result.response_code,
            {"message": result.message[:500], "operation_succeeded": False},
        )
    if not result.cfdi_uuid or not result.xml_content:
        FiscalEvent.objects.create(
            fiscal_document=document,
            action=FiscalEvent.Action.ERROR,
            state_before=FiscalDocument.State.SUBMITTED,
            state_after=FiscalDocument.State.SUBMITTED,
            provider_request_id=reference,
            response_code=result.response_code or "incomplete_result",
            response_payload={"message": "FEL respondió sin UUID o XML completos; consultar por referencia."},
            actor=actor,
        )
        return document
    return record_stamp(
        document.pk, actor, result.cfdi_uuid, result.xml_content,
        provider_request_id=reference,
        response_code=result.response_code,
        response_payload={"source": "direct_stamp", "environment": settings.FEL_ENVIRONMENT},
        pdf_base64=result.pdf_base64,
    )


@transaction.atomic
def generate_fiscal_document_xml(document_id, actor, confirm_payment_snapshot=False, confirm_credit_note_snapshot=False):
    """Create and persist a signed request XML without sending it to FEL."""
    document = FiscalDocument.objects.select_for_update().get(pk=document_id)
    if document.state != FiscalDocument.State.PREPARED:
        raise ValidationError("Solo un CFDI preparado puede generar el XML previo al timbrado.")
    if document.payment_id and document.payment.state != Payment.State.POSTED:
        raise ValidationError("Solo un cobro aplicado y no revertido puede generar un complemento de pago.")
    if document.credit_note_id and document.credit_note.state != CustomerCreditNote.State.POSTED:
        raise ValidationError("La nota interna debe seguir aplicada para generar el CFDI de egreso.")
    if document.document_type == FiscalDocument.DocumentType.PAYMENT and not confirm_payment_snapshot:
        raise ValidationError("Revisa impuestos, importes y CFDI relacionados antes de firmar el complemento de pago.")
    if document.document_type == FiscalDocument.DocumentType.CREDIT_NOTE and not confirm_credit_note_snapshot:
        raise ValidationError("Revisa el receptor, CFDI ingreso relacionado, forma de pago, conceptos e IVA antes de firmar el egreso.")
    if document.request_xml:
        return document
    try:
        if document.document_type == FiscalDocument.DocumentType.INCOME and document.invoice_id:
            signed_xml = build_signed_income_cfdi(document.request_payload)
        elif document.document_type == FiscalDocument.DocumentType.CREDIT_NOTE and document.credit_note_id:
            signed_xml = build_signed_credit_note_cfdi(document.request_payload)
        elif document.document_type == FiscalDocument.DocumentType.PAYMENT and document.payment_id:
            signed_xml = build_signed_payment_cfdi(document.request_payload)
        else:
            raise ValidationError("El tipo de comprobante aún no cuenta con generación de XML.")
    except ValidationError:
        raise
    except (ValueError, KeyError, OSError, ArithmeticError, TypeError) as error:
        raise ValidationError(str(error)) from error
    document.request_xml = signed_xml
    payload = dict(document.request_payload)
    payload.update({"xml_generated": True, "catalogs_verified": True, "xml_generation_blockers": []})
    if document.document_type == FiscalDocument.DocumentType.PAYMENT:
        payload.update({"taxes_summary_review_required": False, "taxes_summary_reviewed_by": str(actor.pk), "taxes_summary_reviewed_at": timezone.now().isoformat()})
    document.request_payload = payload
    document.save(update_fields=["request_xml", "request_payload"])
    FiscalEvent.objects.create(
        fiscal_document=document,
        action=FiscalEvent.Action.XML_GENERATE,
        state_before=FiscalDocument.State.PREPARED,
        state_after=FiscalDocument.State.PREPARED,
        actor=actor,
        response_payload={"signed": True, "sat_xsd_valid": True, "complement_xsd_valid": document.document_type == FiscalDocument.DocumentType.PAYMENT, "payment_snapshot_confirmed": document.document_type == FiscalDocument.DocumentType.PAYMENT, "credit_note_snapshot_confirmed": document.document_type == FiscalDocument.DocumentType.CREDIT_NOTE, "sent_to_fel": False},
    )
    return document


@transaction.atomic
def record_stamp(document_id, actor, cfdi_uuid, xml_content, provider_request_id="", response_code="", response_payload=None, pdf_base64=""):
    document = FiscalDocument.objects.select_for_update().get(pk=document_id)
    if document.state != FiscalDocument.State.SUBMITTED:
        raise ValidationError("Solo una solicitud enviada puede marcarse como timbrada.")
    if not cfdi_uuid or not xml_content:
        raise ValidationError("El PAC debe devolver UUID y XML timbrado.")
    if not document.request_xml:
        raise ValidationError("El comprobante enviado no conserva el XML firmado que debe cotejarse.")
    try:
        cfdi_uuid = uuid.UUID(str(cfdi_uuid))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValidationError("El PAC debe devolver un UUID fiscal válido.") from error

    # Only accept a stamped XML that is structurally valid and matches the
    # immutable request snapshot. A mismatched response stays SUBMITTED so it
    # can be investigated through the provider reference without a resend.
    from lxml import etree
    from .fiscal.validator import CFDIValidationError, require_valid_cfdi_xml

    try:
        validator = require_valid_payment_cfdi_xml if document.document_type == FiscalDocument.DocumentType.PAYMENT else require_valid_cfdi_xml
        validator(xml_content)
        parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, recover=False)
        root = etree.fromstring(xml_content.encode("utf-8") if isinstance(xml_content, str) else xml_content, parser)
    except (CFDIValidationError, etree.XMLSyntaxError, UnicodeEncodeError) as error:
        raise ValidationError("El XML devuelto por el PAC no pasa la validación estructural SAT.") from error

    fiscal_ns = CFDI_NS
    tfd_nodes = root.findall(f".//{{{TFD_NS}}}TimbreFiscalDigital")
    if len(tfd_nodes) != 1:
        raise ValidationError("El XML timbrado debe contener exactamente un Timbre Fiscal Digital.")
    timbre = tfd_nodes[0]
    try:
        request_root = etree.fromstring(
            document.request_xml.encode("utf-8") if isinstance(document.request_xml, str) else document.request_xml,
            parser,
        )
    except (etree.XMLSyntaxError, UnicodeEncodeError, TypeError) as error:
        raise ValidationError("El XML firmado enviado a FEL no se pudo volver a interpretar.") from error
    if _cfdi_business_tree(request_root) != _cfdi_business_tree(root):
        raise ValidationError("El contenido del CFDI timbrado difiere del XML firmado que se envió a FEL.")
    issuer = root.find(f"{{{fiscal_ns}}}Emisor")
    recipient = root.find(f"{{{fiscal_ns}}}Receptor")
    if timbre.get("UUID", "").upper() != str(cfdi_uuid).upper():
        raise ValidationError("El UUID del XML timbrado no coincide con el UUID devuelto por el PAC.")
    if not timbre.get("SelloCFD") or timbre.get("SelloCFD") != root.get("Sello"):
        raise ValidationError("El sello CFDI del Timbre Fiscal Digital no coincide con el XML timbrado.")
    if issuer is None or issuer.get("Rfc", "").upper() != document.issuer_rfc.upper():
        raise ValidationError("El RFC emisor del XML timbrado no coincide con la solicitud enviada.")
    if recipient is None or recipient.get("Rfc", "").upper() != document.recipient_rfc.upper():
        raise ValidationError("El RFC receptor del XML timbrado no coincide con la solicitud enviada.")
    if document.document_type == FiscalDocument.DocumentType.INCOME and document.invoice_id:
        try:
            stamped_total = Decimal(root.get("Total", ""))
        except Exception as error:
            raise ValidationError("El XML timbrado no contiene un total válido.") from error
        if root.get("Moneda") != document.currency or stamped_total != document.invoice.total:
            raise ValidationError("El total o la moneda del XML timbrado no coincide con la factura interna.")
    elif document.document_type == FiscalDocument.DocumentType.CREDIT_NOTE and document.credit_note_id:
        try:
            stamped_total = Decimal(root.get("Total", ""))
        except Exception as error:
            raise ValidationError("El XML timbrado no contiene un total válido.") from error
        related_nodes = root.findall(f"{{{fiscal_ns}}}CfdiRelacionados/{{{fiscal_ns}}}CfdiRelacionado")
        relation_container = root.find(f"{{{fiscal_ns}}}CfdiRelacionados")
        expected_uuid = str(document.request_payload.get("related_cfdi_uuid", "")).upper()
        stamped_uuids = sorted(node.get("UUID", "").upper() for node in related_nodes)
        if root.get("TipoDeComprobante") != "E" or root.get("Moneda") != document.currency or stamped_total != document.credit_note.total:
            raise ValidationError("El tipo, total o moneda del CFDI timbrado no coincide con la nota de crédito interna.")
        if relation_container is None or relation_container.get("TipoRelacion") != document.request_payload.get("relation_type") or stamped_uuids != [expected_uuid]:
            raise ValidationError("El CFDI de egreso timbrado no conserva el UUID y tipo de relación preparados.")
    elif document.document_type == FiscalDocument.DocumentType.PAYMENT and document.payment_id:
        try:
            validate_payment_cfdi_snapshot(root, document.request_payload)
        except PaymentCFDIError as error:
            raise ValidationError(str(error)) from error

    stamped_at_text = timbre.get("FechaTimbrado", "")
    try:
        stamped_at = datetime.fromisoformat(stamped_at_text.replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise ValidationError("El Timbre Fiscal Digital no contiene una fecha de timbrado válida.") from error
    if timezone.is_naive(stamped_at):
        stamped_at = timezone.make_aware(stamped_at, timezone.get_current_timezone())

    pdf_storage_key, pdf_status = _store_fel_pdf(document.pk, pdf_base64)
    before = document.state
    document.cfdi_uuid = cfdi_uuid
    document.xml_content = xml_content
    document.pdf_storage_key = pdf_storage_key
    document.provider_request_id = provider_request_id or document.provider_request_id
    document.stamped_at = stamped_at
    document.state = FiscalDocument.State.STAMPED
    try:
        document.save(update_fields=["cfdi_uuid", "xml_content", "pdf_storage_key", "provider_request_id", "stamped_at", "state"])
    except Exception:
        if pdf_storage_key:
            try:
                default_storage.delete(pdf_storage_key)
            except Exception:
                pass
        raise
    event_payload = dict(response_payload or {})
    event_payload["pdf_storage"] = pdf_status
    FiscalEvent.objects.create(
        fiscal_document=document,
        action=FiscalEvent.Action.STAMP,
        state_before=before,
        state_after=document.state,
        provider_request_id=document.provider_request_id,
        response_code=response_code,
        response_payload=event_payload,
        actor=actor,
    )
    return document


@transaction.atomic
def record_fiscal_rejection(document_id, actor, response_code="", response_payload=None):
    document = FiscalDocument.objects.select_for_update().get(pk=document_id)
    if document.state != FiscalDocument.State.SUBMITTED:
        raise ValidationError("Solo una solicitud enviada puede marcarse como rechazada.")
    before = document.state
    document.state = FiscalDocument.State.REJECTED
    document.save(update_fields=["state"])
    FiscalEvent.objects.create(
        fiscal_document=document,
        action=FiscalEvent.Action.ERROR,
        state_before=before,
        state_after=document.state,
        provider_request_id=document.provider_request_id,
        response_code=response_code,
        response_payload=response_payload or {},
        actor=actor,
    )
    return document


@transaction.atomic
def request_fiscal_cancellation(document_id, actor, reason, replacement_uuid=None):
    document = FiscalDocument.objects.select_for_update().get(pk=document_id)
    if document.state not in {FiscalDocument.State.STAMPED, FiscalDocument.State.CANCEL_REJECTED}:
        raise ValidationError("Solo un CFDI timbrado o con una cancelación rechazada puede iniciar otra solicitud.")
    if reason not in FiscalDocument.CancellationReason.values:
        raise ValidationError("Selecciona una clave de cancelación válida.")
    if reason == FiscalDocument.CancellationReason.ERROR_REPLACED and not replacement_uuid:
        raise ValidationError("El motivo 01 requiere el UUID del CFDI sustituto.")
    before = document.state
    document.cancellation_reason = reason
    document.replacement_uuid = replacement_uuid
    document.state = FiscalDocument.State.CANCEL_PENDING
    document.save(update_fields=["cancellation_reason", "replacement_uuid", "state"])
    FiscalEvent.objects.create(
        fiscal_document=document,
        action=FiscalEvent.Action.CANCEL,
        state_before=before,
        state_after=document.state,
        provider_request_id=document.provider_request_id,
        response_payload={"replacement_uuid": str(replacement_uuid) if replacement_uuid else ""},
        actor=actor,
    )
    return document


@transaction.atomic
def record_cancellation_result(document_id, status, actor, response_code="", response_payload=None):
    document = FiscalDocument.objects.select_for_update().get(pk=document_id)
    if document.state != FiscalDocument.State.CANCEL_PENDING:
        raise ValidationError("No hay una solicitud de cancelación pendiente.")
    if status not in {"cancelled", "rejected", "pending"}:
        raise ValidationError("La respuesta de cancelación no tiene un estado reconocido.")
    before = document.state
    document.state = {
        "cancelled": FiscalDocument.State.CANCELLED,
        "rejected": FiscalDocument.State.CANCEL_REJECTED,
        "pending": FiscalDocument.State.CANCEL_PENDING,
    }[status]
    document.save(update_fields=["state"])
    FiscalEvent.objects.create(
        fiscal_document=document,
        action=FiscalEvent.Action.RESPONSE,
        state_before=before,
        state_after=document.state,
        provider_request_id=document.provider_request_id,
        response_code=response_code,
        response_payload=response_payload or {},
        actor=actor,
    )
    return document


def cancel_fiscal_document(document_id, actor, reason, replacement_uuid=None, confirm_irreversible=False):
    """Request SAT cancellation once; uncertain transport remains pending."""
    import uuid as uuid_module
    from .providers.fel import (
        FELConfigurationError, FELTransportError, cancel_cfdi,
        prepare_cancellation_request,
    )

    if not confirm_irreversible:
        raise ValidationError("Confirma que deseas enviar esta cancelación irreversible al SAT.")
    document = FiscalDocument.objects.get(pk=document_id)
    if document.state not in {FiscalDocument.State.STAMPED, FiscalDocument.State.CANCEL_REJECTED}:
        raise ValidationError("Solo un CFDI timbrado o con una cancelación rechazada puede iniciar otra solicitud.")
    if document.provider_code != "fel-premium":
        raise ValidationError("El proveedor del CFDI no es FEL Premium.")
    if reason not in FiscalDocument.CancellationReason.values:
        raise ValidationError("Selecciona una clave de cancelación válida.")
    if reason == FiscalDocument.CancellationReason.ERROR_REPLACED and not replacement_uuid:
        raise ValidationError("El motivo 01 requiere el UUID del CFDI sustituto.")
    if reason != FiscalDocument.CancellationReason.ERROR_REPLACED and replacement_uuid:
        raise ValidationError("Solo el motivo 01 debe incluir UUID sustituto.")
    if replacement_uuid:
        try:
            replacement_uuid = uuid_module.UUID(str(replacement_uuid))
        except (ValueError, TypeError, AttributeError) as error:
            raise ValidationError("Captura un UUID sustituto válido.") from error
        if replacement_uuid == document.cfdi_uuid:
            raise ValidationError("El UUID sustituto debe ser distinto del comprobante que vas a cancelar.")
        replacement = FiscalDocument.objects.filter(cfdi_uuid=replacement_uuid).first()
        if not replacement:
            raise ValidationError("El CFDI sustituto debe existir en el registro fiscal de Redmagna.")
        if replacement.state != FiscalDocument.State.STAMPED:
            raise ValidationError("El CFDI sustituto debe estar timbrado y vigente antes de solicitar esta cancelación.")
        if replacement.provider_code != "fel-premium":
            raise ValidationError("El CFDI sustituto debe estar timbrado por FEL Premium.")
        if replacement.document_type != document.document_type:
            raise ValidationError("El CFDI sustituto debe ser del mismo tipo que el comprobante que vas a cancelar.")
        if replacement.issuer_rfc.strip().upper() != document.issuer_rfc.strip().upper():
            raise ValidationError("El CFDI sustituto debe tener el mismo RFC emisor.")
        if replacement.recipient_rfc.strip().upper() != document.recipient_rfc.strip().upper():
            raise ValidationError("El CFDI sustituto debe tener el mismo RFC receptor.")
        if replacement.currency != document.currency:
            raise ValidationError("El CFDI sustituto debe estar en la misma moneda.")
        if replacement.replaces_id and replacement.replaces_id != document.pk:
            raise ValidationError("El CFDI sustituto ya está relacionado con otro comprobante.")
        from lxml import etree

        try:
            replacement_root = etree.fromstring(
                replacement.xml_content.encode("utf-8"),
                parser=etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False),
            )
        except (etree.XMLSyntaxError, AttributeError) as error:
            raise ValidationError("No se pudo verificar el XML timbrado del CFDI sustituto.") from error
        cfdi_namespace = "http://www.sat.gob.mx/cfd/4"
        relation = replacement_root.find(f"{{{cfdi_namespace}}}CfdiRelacionados")
        related_uuids = [
            (node.get("UUID") or "").strip().upper()
            for node in replacement_root.findall(f"{{{cfdi_namespace}}}CfdiRelacionados/{{{cfdi_namespace}}}CfdiRelacionado")
        ]
        if relation is None or relation.get("TipoRelacion") != "04" or related_uuids != [str(document.cfdi_uuid).upper()]:
            raise ValidationError("El XML del CFDI sustituto debe incluir relación 04 únicamente al UUID del comprobante que se cancelará.")
        stamped_uuid = replacement_root.find(
            ".//{http://www.sat.gob.mx/TimbreFiscalDigital}TimbreFiscalDigital"
        )
        if stamped_uuid is None or (stamped_uuid.get("UUID") or "").strip().upper() != str(replacement_uuid).upper():
            raise ValidationError("El UUID del reemplazo no coincide con el timbre fiscal guardado en su XML.")
    try:
        fel_request = prepare_cancellation_request(document, reason, replacement_uuid)
    except FELConfigurationError as error:
        raise ValidationError(str(error)) from error

    document = request_fiscal_cancellation(document.pk, actor, reason, replacement_uuid)
    try:
        result = cancel_cfdi(fel_request)
    except FELTransportError as error:
        FiscalEvent.objects.create(
            fiscal_document=document,
            action=FiscalEvent.Action.ERROR,
            state_before=FiscalDocument.State.CANCEL_PENDING,
            state_after=FiscalDocument.State.CANCEL_PENDING,
            response_code="transport_uncertain",
            response_payload={"message": str(error)[:300], "sat_result_must_be_checked_before_retry": True},
            actor=actor,
        )
        raise
    return record_cancellation_result(
        document.pk,
        result.status,
        actor,
        response_code=result.response_code,
        response_payload={"message": result.message, "receipt_xml": result.receipt_xml, "status": result.status},
    )


@transaction.atomic
def prepare_invoice_cfdi(invoice_id, actor, cfdi_use, exportation, payment_method, payment_form, idempotency_key, concepts):
    """Create a reviewable CFDI snapshot. This does not build XML or contact a PAC."""
    from django.conf import settings

    invoice = CustomerInvoice.objects.select_for_update().select_related("customer").prefetch_related("lines").get(pk=invoice_id)
    if invoice.state not in {CustomerInvoice.State.OPEN, CustomerInvoice.State.PARTIAL, CustomerInvoice.State.PAID}:
        raise ValidationError("Solo una factura abierta, parcial o pagada puede preparar un CFDI.")
    if invoice.opening_balance_batch_id:
        raise ValidationError("La factura es un saldo operativo migrado; no se puede volver a facturar ni emitir un CFDI nuevo con ese saldo.")
    customer = invoice.customer
    issuer_rfc = getattr(settings, "CFDI_ISSUER_RFC", "").strip().upper()
    issuer_name = getattr(settings, "CFDI_ISSUER_NAME", "").strip()
    issuer_regime = getattr(settings, "CFDI_ISSUER_FISCAL_REGIME", "").strip()
    issuer_postal_code = getattr(settings, "CFDI_ISSUER_POSTAL_CODE", "").strip()
    provider_code = getattr(settings, "CFDI_PROVIDER_CODE", "fel-premium").strip()
    if not all((issuer_rfc, issuer_name, issuer_regime, issuer_postal_code)):
        raise ValidationError("Configura RFC, razón social, régimen fiscal y código postal del emisor antes de preparar el CFDI.")
    if not customer.rfc or not customer.legal_name or not customer.fiscal_regime or not customer.fiscal_postal_code:
        raise ValidationError("Completa en el cliente RFC, razón social, régimen fiscal y código postal antes de preparar el CFDI.")
    if not re.fullmatch(r"\d{3}", issuer_regime) or not re.fullmatch(r"\d{5}", issuer_postal_code):
        raise ValidationError("El régimen del emisor debe tener tres dígitos y su código postal cinco dígitos.")
    if not re.fullmatch(r"\d{3}", customer.fiscal_regime) or not re.fullmatch(r"\d{5}", customer.fiscal_postal_code):
        raise ValidationError("El régimen del receptor debe tener tres dígitos y su código postal cinco dígitos.")
    if not is_sat_catalog_value("c_RegimenFiscal", issuer_regime) or not is_sat_catalog_value("c_RegimenFiscal", customer.fiscal_regime):
        raise ValidationError("El régimen fiscal del emisor o receptor no aparece en el catálogo CFDI 4.0 local.")
    if not re.fullmatch(r"[A-Z0-9]{3}", cfdi_use):
        raise ValidationError("El uso CFDI debe ser una clave de tres caracteres.")
    if payment_method not in {"PUE", "PPD"} or not re.fullmatch(r"\d{2}", payment_form):
        raise ValidationError("Selecciona método y forma de pago con claves válidas.")
    if (payment_method == "PPD") != (payment_form == "99"):
        raise ValidationError("Esta preparación usa forma 99 solo con PPD y requiere otra forma para PUE.")
    if payment_method == "PUE" and invoice.state != CustomerInvoice.State.PAID:
        raise ValidationError("PUE requiere que la factura esté completamente pagada en el ERP.")
    lines = list(invoice.lines.select_related("catalog_product").order_by("line_number"))
    if not lines:
        raise ValidationError("Agrega conceptos antes de preparar el CFDI.")
    mapping_by_id = {str(item["invoice_line_id"]): item for item in concepts}
    if len(mapping_by_id) != len(concepts) or set(mapping_by_id) != {str(line.id) for line in lines}:
        raise ValidationError("La solicitud debe clasificar exactamente todos los conceptos de la factura.")

    concept_snapshots = []
    subtotal = Decimal("0.00")
    tax_total = Decimal("0.00")
    for line in lines:
        mapping = mapping_by_id[str(line.id)]
        if not re.fullmatch(r"\d{8}", mapping["product_service_key"]):
            raise ValidationError(f"El concepto {line.line_number} necesita una clave SAT de producto o servicio de ocho dígitos.")
        if not is_sat_catalog_value("c_ClaveProdServ", mapping["product_service_key"]):
            raise ValidationError(f"La clave de producto o servicio del concepto {line.line_number} no existe en el catálogo SAT local.")
        if not re.fullmatch(r"[A-Z0-9]{2,3}", mapping["unit_key"].upper()):
            raise ValidationError(f"El concepto {line.line_number} necesita una clave SAT de unidad.")
        if not is_sat_catalog_value("c_ClaveUnidad", mapping["unit_key"].upper()):
            raise ValidationError(f"La clave de unidad del concepto {line.line_number} no existe en el catálogo SAT local.")
        if mapping["tax_object"] == "01" and line.tax_rate != 0:
            raise ValidationError(f"El concepto {line.line_number} marcado como no objeto debe tener tasa cero.")
        if mapping["tax_object"] == "02" and line.tax_rate not in {0, 8, 16}:
            raise ValidationError(f"La tasa del concepto {line.line_number} no está soportada por esta preparación inicial.")
        if mapping["tax_object"] == "02" and line.tax_rate == 8:
            if not getattr(settings, "CFDI_ALLOW_BORDER_8_RATE", False):
                raise ValidationError("El IVA al 8% está deshabilitado. Solo actívalo después de validar con Contabilidad el estímulo fronterizo aplicable al emisor y a la operación.")
            reviewed_postal_codes = getattr(settings, "CFDI_BORDER_8_REVIEWED_POSTAL_CODES", set())
            if issuer_postal_code not in reviewed_postal_codes:
                raise ValidationError("El código postal de expedición no está en la lista revisada para el estímulo fronterizo al 8%.")
            if mapping["product_service_key"] == "01010101":
                raise ValidationError("La clave SAT genérica 01010101 no es elegible para el estímulo fronterizo de IVA al 8% en esta preparación.")
            if not line.catalog_product_id or not line.catalog_product.sat_border_8_eligible:
                raise ValidationError(f"El producto del concepto {line.line_number} no tiene revisión contable de elegibilidad fronteriza al 8%.")
            if mapping["product_service_key"] != line.catalog_product.sat_product_service_key:
                raise ValidationError(f"La clave SAT del concepto {line.line_number} difiere de la clave revisada en el catálogo para IVA al 8%.")
        line_subtotal = line.line_subtotal
        line_tax = line.tax_amount if mapping["tax_object"] == "02" else Decimal("0.00")
        gross_amount = (line.quantity * line.unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        subtotal += gross_amount
        tax_total += line_tax
        concept_snapshots.append({
            "source_line_id": str(line.id), "line_number": line.line_number,
            "catalog_product_id": str(line.catalog_product_id) if line.catalog_product_id else "",
            "catalog_product_sku": line.catalog_product.sku if line.catalog_product_id else "",
            "product_service_key": mapping["product_service_key"], "unit_key": mapping["unit_key"].upper(),
            "description": line.description, "quantity": str(line.quantity), "unit_price": str(line.unit_price),
            "amount": str(gross_amount), "discount": str(line.discount_amount), "tax_base": str(line_subtotal), "tax_object": mapping["tax_object"], "tax_factor": mapping["tax_factor"],
            "vat_rate_percent": str(line.tax_rate) if mapping["tax_object"] == "02" else "0.00",
            "vat_amount": str(line_tax),
        })
    discount_total = sum((Decimal(item["discount"]) for item in concept_snapshots), Decimal("0.00"))
    total = subtotal - discount_total + tax_total
    if total <= 0:
        raise ValidationError("El total del CFDI debe ser mayor que cero.")
    snapshot = {
        "cfdi_version": "4.0", "document_type": "I", "provider_code": provider_code, "source_invoice": invoice.number,
        "issue_date": invoice.issue_date.isoformat(), "place_of_issue_postal_code": issuer_postal_code,
        "exportation": exportation,
        "payment_method": payment_method, "payment_form": payment_form, "currency": invoice.currency,
        "issuer": {"rfc": issuer_rfc, "legal_name": issuer_name, "fiscal_regime": issuer_regime},
        "recipient": {"rfc": customer.rfc.strip().upper(), "legal_name": customer.legal_name.strip(), "fiscal_regime": customer.fiscal_regime, "fiscal_postal_code": customer.fiscal_postal_code, "cfdi_use": cfdi_use},
        "concepts": concept_snapshots, "subtotal": str(subtotal), "discount_total": str(discount_total), "vat_transferred": str(tax_total), "total": str(total),
        "catalogs_verified": False, "xml_generated": False,
    }
    existing = FiscalDocument.objects.select_for_update().filter(idempotency_key=idempotency_key).first()
    if existing:
        if existing.invoice_id != invoice.id or existing.request_payload != snapshot:
            raise ValidationError("La clave de idempotencia ya se usó con otra solicitud fiscal.")
        return existing, False
    if invoice.fiscal_documents.filter(state__in=[FiscalDocument.State.PREPARED, FiscalDocument.State.SUBMITTED, FiscalDocument.State.STAMPED, FiscalDocument.State.CANCEL_PENDING]).exists():
        raise ValidationError("La factura ya tiene un comprobante preparado, enviado o vigente.")
    document = FiscalDocument.objects.create(
        invoice=invoice, document_type=FiscalDocument.DocumentType.INCOME, provider_code=provider_code,
        idempotency_key=idempotency_key, issuer_rfc=issuer_rfc, recipient_rfc=customer.rfc.strip().upper(),
        recipient_name=customer.legal_name.strip(), recipient_fiscal_regime=customer.fiscal_regime,
        recipient_postal_code=customer.fiscal_postal_code, cfdi_use=cfdi_use,
        payment_method=payment_method, payment_form=payment_form, currency=invoice.currency,
        request_payload=snapshot,
    )
    FiscalEvent.objects.create(
        fiscal_document=document, action=FiscalEvent.Action.PREPARE,
        state_before="", state_after=FiscalDocument.State.PREPARED, actor=actor,
        response_payload={"catalogs_verified": False, "xml_generated": False},
    )
    return document, True


@transaction.atomic
def prepare_credit_note_cfdi(credit_note_id, actor, cfdi_use, payment_form, idempotency_key):
    """Prepare a CFDI 4.0 egreso tied to the stamped income CFDI and its internal credit note."""
    from django.conf import settings
    from lxml import etree
    from .fiscal.validator import CFDIValidationError, require_valid_cfdi_xml

    note = CustomerCreditNote.objects.select_for_update().select_related("invoice__customer").prefetch_related("lines__invoice_line").get(pk=credit_note_id)
    if note.state != CustomerCreditNote.State.POSTED:
        raise ValidationError("Aplica la nota interna antes de preparar su CFDI de egreso.")
    if note.issue_date != timezone.localdate():
        raise ValidationError("La fecha de la nota debe ser hoy para preparar y firmar un CFDI nuevo.")
    if not is_sat_catalog_value("c_UsoCFDI", cfdi_use):
        raise ValidationError("El uso CFDI no aparece en el catálogo CFDI 4.0 local.")
    if not is_sat_catalog_value("c_FormaPago", payment_form) or payment_form == "99":
        raise ValidationError("Selecciona una forma de pago SAT válida para el CFDI de egreso.")
    if not is_sat_catalog_value("c_TipoRelacion", "01"):
        raise ValidationError("El catálogo CFDI local no contiene la relación 01 de nota de crédito.")
    if not note.lines.all():
        raise ValidationError("La nota de crédito no tiene conceptos.")

    source_cfdi = note.invoice.fiscal_documents.filter(
        document_type=FiscalDocument.DocumentType.INCOME,
        state__in=[FiscalDocument.State.STAMPED, FiscalDocument.State.CANCEL_REJECTED],
    ).exclude(cfdi_uuid__isnull=True).order_by("-stamped_at").first()
    if not source_cfdi or not source_cfdi.xml_content:
        raise ValidationError("La factura origen necesita un CFDI de ingreso timbrado y vigente en FEL.")
    try:
        require_valid_cfdi_xml(source_cfdi.xml_content)
        parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, recover=False)
        source_root = etree.fromstring(source_cfdi.xml_content.encode("utf-8"), parser)
    except (CFDIValidationError, etree.XMLSyntaxError, UnicodeEncodeError) as error:
        raise ValidationError("El CFDI de ingreso origen no pasa la validación SAT local.") from error
    receiver = source_root.find("{http://www.sat.gob.mx/cfd/4}Receptor")
    if source_root.get("TipoDeComprobante") != "I" or receiver is None or receiver.get("Rfc", "").upper() != source_cfdi.recipient_rfc.upper():
        raise ValidationError("El comprobante origen debe ser de ingreso y coincidir con el RFC receptor guardado.")
    if note.invoice.customer.rfc and note.invoice.customer.rfc.strip().upper() != source_cfdi.recipient_rfc.upper():
        raise ValidationError("El RFC actual del cliente difiere del CFDI origen; Contabilidad debe corregir la ficha antes de continuar.")

    existing = FiscalDocument.objects.select_for_update().filter(idempotency_key=idempotency_key).first()
    source_payload = source_cfdi.request_payload
    issuer = source_payload.get("issuer", {})
    recipient = source_payload.get("recipient", {})
    if not all(issuer.get(key) for key in ("rfc", "legal_name", "fiscal_regime")) or not all(recipient.get(key) for key in ("rfc", "legal_name", "fiscal_regime", "fiscal_postal_code")):
        raise ValidationError("El snapshot CFDI original no conserva todos los datos de emisor y receptor requeridos.")
    original_concepts = {str(item.get("source_line_id")): item for item in source_payload.get("concepts", [])}
    concepts = []
    gross_subtotal = Decimal("0.00")
    discount_total = Decimal("0.00")
    tax_total = Decimal("0.00")
    for line in note.lines.all():
        source = original_concepts.get(str(line.invoice_line_id))
        if source is None:
            raise ValidationError(f"El CFDI origen no conserva la clasificación SAT del renglón {line.invoice_line.line_number}.")
        amount = (line.quantity * line.unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        discount = (amount * line.discount_percent / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        tax_base = amount - discount
        if source.get("tax_object") == "02":
            tax = (tax_base * line.tax_rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            tax = Decimal("0.00")
        concepts.append({
            "source_line_id": str(line.invoice_line_id), "line_number": line.line_number,
            "catalog_product_sku": source.get("catalog_product_sku", ""),
            "product_service_key": source["product_service_key"], "unit_key": source["unit_key"],
            "description": line.description, "quantity": str(line.quantity), "unit_price": str(line.unit_price),
            "amount": str(amount), "discount": str(discount), "tax_base": str(tax_base),
            "tax_object": source["tax_object"], "tax_factor": source.get("tax_factor", "Tasa"),
            "vat_rate_percent": str(line.tax_rate), "vat_amount": str(tax),
        })
        gross_subtotal += amount
        discount_total += discount
        tax_total += tax
    total = gross_subtotal - discount_total + tax_total
    if total <= Decimal("0.00") or total != note.total:
        raise ValidationError("El total de conceptos fiscales no coincide con la nota interna o es cero.")

    snapshot = {
        "cfdi_version": "4.0", "document_type": "E", "provider_code": getattr(settings, "CFDI_PROVIDER_CODE", "fel-premium").strip(),
        "source_invoice": note.invoice.number, "source_credit_note": note.number,
        "issue_date": note.issue_date.isoformat(), "place_of_issue_postal_code": source_payload.get("place_of_issue_postal_code", ""),
        "exportation": source_payload.get("exportation", "01"), "payment_method": "PUE", "payment_form": payment_form,
        "currency": note.invoice.currency, "relation_type": "01", "related_cfdi_uuid": str(source_cfdi.cfdi_uuid).upper(),
        "issuer": issuer, "recipient": {**recipient, "cfdi_use": cfdi_use},
        "concepts": concepts, "subtotal": str(gross_subtotal), "discount_total": str(discount_total),
        "vat_transferred": str(tax_total), "total": str(total), "catalogs_verified": True, "xml_generated": False,
    }
    if existing:
        if existing.credit_note_id != note.id or existing.request_payload != snapshot:
            raise ValidationError("La clave de idempotencia ya se usó con otra solicitud fiscal.")
        return existing, False
    active_states = [FiscalDocument.State.PREPARED, FiscalDocument.State.SUBMITTED, FiscalDocument.State.STAMPED, FiscalDocument.State.CANCEL_PENDING, FiscalDocument.State.CANCEL_REJECTED]
    if note.fiscal_documents.filter(state__in=active_states).exists():
        raise ValidationError("La nota ya tiene un CFDI de egreso preparado, enviado o vigente.")

    document = FiscalDocument.objects.create(
        credit_note=note, document_type=FiscalDocument.DocumentType.CREDIT_NOTE,
        provider_code=snapshot["provider_code"], idempotency_key=idempotency_key,
        issuer_rfc=issuer["rfc"], recipient_rfc=source_cfdi.recipient_rfc,
        recipient_name=source_cfdi.recipient_name, recipient_fiscal_regime=source_cfdi.recipient_fiscal_regime,
        recipient_postal_code=source_cfdi.recipient_postal_code, cfdi_use=cfdi_use,
        payment_method="PUE", payment_form=payment_form, currency=note.invoice.currency,
        request_payload=snapshot,
    )
    FiscalEvent.objects.create(
        fiscal_document=document, action=FiscalEvent.Action.PREPARE,
        state_before="", state_after=FiscalDocument.State.PREPARED, actor=actor,
        response_payload={"catalogs_verified": True, "source_cfdi_uuid": str(source_cfdi.cfdi_uuid), "xml_generated": False},
    )
    return document, True


@transaction.atomic
def prepare_payment_cfdi(payment_id, actor, payment_form, idempotency_key):
    """Create a reviewable Pagos 2.0 snapshot; it does not build XML or call a PAC."""
    from django.conf import settings

    payment = Payment.objects.select_for_update().select_related("customer").get(pk=payment_id)
    if payment.state != Payment.State.POSTED or not payment.posted_at:
        raise ValidationError("Solo un cobro aplicado puede preparar un complemento de recepción de pagos.")
    if payment.received_at > timezone.now():
        raise ValidationError("La fecha de recepción del cobro no puede estar en el futuro.")
    if not re.fullmatch(r"\d{2}", payment_form) or payment_form == "99":
        raise ValidationError("Selecciona una forma de pago SAT válida para el complemento.")
    if not is_sat_catalog_value("c_FormaPago", payment_form):
        raise ValidationError("La forma de pago no aparece en el catálogo CFDI 4.0 local.")
    existing = FiscalDocument.objects.select_for_update().filter(idempotency_key=idempotency_key).first()
    if existing:
        if existing.payment_id != payment.id or existing.payment_form != payment_form:
            raise ValidationError("La clave de idempotencia ya se usó con otra solicitud fiscal.")
        return existing, False

    customer = payment.customer
    provider_code = getattr(settings, "CFDI_PROVIDER_CODE", "fel-premium").strip()

    allocations = list(payment.allocations.select_for_update().select_related("invoice").order_by("invoice_id"))
    if not allocations:
        raise ValidationError("El cobro aplicado no tiene facturas relacionadas.")
    if sum((item.amount for item in allocations), Decimal("0.00")) != payment.amount:
        raise ValidationError("La suma aplicada del cobro debe coincidir con su importe.")

    related_documents = []
    issuer_snapshot = None
    recipient_snapshot = None
    for allocation in allocations:
        invoice = allocation.invoice
        if invoice.opening_balance_batch_id:
            raise ValidationError(f"La factura externa {invoice.opening_external_number} no tiene historia fiscal importada; no se puede emitir Pagos 2.0 para este cobro.")
        if invoice.credit_notes.filter(state=CustomerCreditNote.State.POSTED).exists():
            raise ValidationError(f"La factura {invoice.number} tiene notas de crédito aplicadas; Pagos 2.0 aún no puede calcular con seguridad el saldo y los impuestos relacionados después de esas notas.")
        if invoice.customer_id != customer.id or invoice.currency != payment.currency:
            raise ValidationError("Cada factura relacionada debe corresponder al cliente y moneda del cobro.")
        source_cfdi = invoice.fiscal_documents.filter(
            document_type=FiscalDocument.DocumentType.INCOME,
            state=FiscalDocument.State.STAMPED,
        ).exclude(cfdi_uuid__isnull=True).order_by("-stamped_at").first()
        if not source_cfdi:
            raise ValidationError(f"La factura {invoice.number} requiere un CFDI de ingreso timbrado antes de preparar el complemento.")
        if source_cfdi.payment_method != "PPD":
            raise ValidationError(f"La factura {invoice.number} no fue emitida con método PPD; no corresponde agregarle este complemento.")
        try:
            tax_basis = issued_invoice_tax_basis(source_cfdi.xml_content, source_cfdi.cfdi_uuid, invoice.total)
        except ValueError as error:
            raise ValidationError(f"No se pueden calcular los impuestos del CFDI {invoice.number}: {error}") from error
        source_issuer = {
            **source_cfdi.request_payload.get("issuer", {}),
            "postal_code": source_cfdi.request_payload.get("place_of_issue_postal_code", ""),
        }
        source_recipient = source_cfdi.request_payload.get("recipient", {})
        if not all(source_issuer.get(key) for key in ("rfc", "legal_name", "fiscal_regime", "postal_code")) or not all(source_recipient.get(key) for key in ("rfc", "legal_name", "fiscal_regime", "fiscal_postal_code")):
            raise ValidationError(f"El snapshot CFDI de la factura {invoice.number} no conserva los datos fiscales completos para el complemento.")
        if issuer_snapshot is None:
            issuer_snapshot, recipient_snapshot = source_issuer, source_recipient
        elif source_issuer != issuer_snapshot or source_recipient != recipient_snapshot:
            raise ValidationError("Los CFDI relacionados deben tener el mismo emisor y receptor para preparar un solo complemento.")

        prior_filter = Q(payment__received_at__lt=payment.received_at) | Q(
            payment__received_at=payment.received_at, payment_id__lt=payment.id,
        )
        prior_allocations = PaymentAllocation.objects.filter(
            invoice=invoice, payment__state=Payment.State.POSTED,
        ).exclude(payment_id=payment.id).filter(prior_filter)
        prior_paid = prior_allocations.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        prior_balance = invoice.total - prior_paid
        remaining = prior_balance - allocation.amount
        if prior_balance <= 0 or allocation.amount > prior_balance or remaining < 0:
            raise ValidationError(f"El saldo de la factura {invoice.number} no cuadra con el pago y las aplicaciones anteriores.")
        prior_payment_ids = list(prior_allocations.values_list("payment_id", flat=True).distinct())
        prior_tax_lines = []
        if prior_payment_ids:
            previous_complements = list(FiscalDocument.objects.filter(
                payment_id__in=prior_payment_ids,
                document_type=FiscalDocument.DocumentType.PAYMENT,
                state=FiscalDocument.State.STAMPED,
            ).order_by("created_at"))
            by_payment_id = {document.payment_id: document for document in previous_complements}
            if set(by_payment_id) != set(prior_payment_ids):
                raise ValidationError(f"Antes de preparar el pago de {invoice.number}, timbra los complementos de pagos anteriores.")
            for previous_document in by_payment_id.values():
                previous_related = next((item for item in previous_document.request_payload.get("related_documents", []) if item.get("source_invoice_id") == str(invoice.id)), None)
                if previous_related is None or "taxes" not in previous_related:
                    raise ValidationError(f"El complemento anterior de {invoice.number} no conserva el desglose necesario para calcular impuestos acumulados.")
                prior_tax_lines.extend(previous_related["taxes"])
        try:
            paid_taxes = allocate_payment_taxes(tax_basis, prior_tax_lines, allocation.amount, prior_balance)
        except ValueError as error:
            raise ValidationError(f"No se pueden calcular los impuestos del CFDI {invoice.number}: {error}") from error
        installment_number = len(prior_payment_ids) + 1
        related_documents.append({
            "source_invoice_id": str(invoice.id),
            "source_invoice_number": invoice.number,
            "cfdi_uuid": str(source_cfdi.cfdi_uuid),
            "currency": invoice.currency,
            "exchange_rate": "1.000000",
            "payment_method": source_cfdi.payment_method,
            "tax_object": tax_basis["tax_object"],
            "installment_number": installment_number,
            "previous_balance": str(prior_balance.quantize(Decimal("0.01"))),
            "amount_paid": str(allocation.amount.quantize(Decimal("0.01"))),
            "remaining_balance": str(remaining.quantize(Decimal("0.01"))),
            "taxes": paid_taxes,
        })

    taxes_summary = summarize_payment_taxes(related_documents)
    snapshot = {
        "cfdi_version": "4.0",
        "document_type": "P",
        "complement_version": "2.0",
        "provider_code": provider_code,
        "source_payment": payment.number,
        "payment_date": payment.received_at.isoformat(),
        "payment_form": payment_form,
        "currency": payment.currency,
        "payment_amount": str(payment.amount.quantize(Decimal("0.01"))),
        "issuer": issuer_snapshot,
        "recipient": recipient_snapshot,
        "related_documents": related_documents,
        "taxes_summary": taxes_summary,
        "taxes_summary_derived_from_stamped_cfdi": True,
        "taxes_summary_review_required": True,
        "xml_generation_blockers": ["Generar y sellar el CFDI con un CSD protegido"],
        "xml_generated": False,
        "catalogs_verified": True,
    }
    if payment.fiscal_documents.filter(state__in=[FiscalDocument.State.PREPARED, FiscalDocument.State.SUBMITTED, FiscalDocument.State.STAMPED, FiscalDocument.State.CANCEL_PENDING]).exists():
        raise ValidationError("El cobro ya tiene un complemento preparado, enviado o vigente.")
    document = FiscalDocument.objects.create(
        payment=payment,
        document_type=FiscalDocument.DocumentType.PAYMENT,
        provider_code=provider_code,
        idempotency_key=idempotency_key,
        issuer_rfc=issuer_snapshot["rfc"],
        recipient_rfc=recipient_snapshot["rfc"],
        recipient_name=recipient_snapshot["legal_name"],
        recipient_fiscal_regime=recipient_snapshot["fiscal_regime"],
        recipient_postal_code=recipient_snapshot["fiscal_postal_code"],
        cfdi_use="CP01",
        payment_form=payment_form,
        currency=payment.currency,
        request_payload=snapshot,
    )
    FiscalEvent.objects.create(
        fiscal_document=document,
        action=FiscalEvent.Action.PREPARE,
        state_before="",
        state_after=FiscalDocument.State.PREPARED,
        actor=actor,
        response_payload={"complement_version": "2.0", "tax_group_count": len(taxes_summary), "xml_generated": False, "catalogs_verified": True, "review_before_signing": True},
    )
    return document, True
