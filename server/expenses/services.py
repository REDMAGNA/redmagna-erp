import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone

from accounting.models import Journal, JournalEntry, JournalLine
from accounting.services import ensure_period_open, reverse_entry
from .models import Expense, ExpensePostingConfiguration, ExpenseReimbursement, ExpenseReport, ExpenseReportEvent


def record_event(report, action, actor, before="", after="", detail=""):
    return ExpenseReportEvent.objects.create(report=report, action=action, actor=actor, state_before=before, state_after=after, detail=detail)


@transaction.atomic
def submit_report(report_id, actor):
    report = ExpenseReport.objects.select_for_update().get(pk=report_id)
    if report.owner_id != actor.pk and not actor.has_perm("expenses.view_all_expensereports"):
        raise ValidationError("No puedes enviar el reporte de otra persona.")
    if report.state not in [ExpenseReport.State.DRAFT, ExpenseReport.State.REJECTED]:
        raise ValidationError("Solo se pueden enviar reportes en borrador o rechazados.")
    expenses = list(report.expenses.prefetch_related("receipts", "category"))
    if not expenses:
        raise ValidationError("Agrega al menos un gasto antes de enviar.")
    for expense in expenses:
        if expense.category.receipt_required and not expense.receipts.exists():
            raise ValidationError(f"Falta el comprobante requerido para: {expense.description}.")
    old = report.state
    report.state = ExpenseReport.State.SUBMITTED
    report.submitted_at = timezone.now()
    report.reviewed_by = None
    report.reviewed_at = None
    report.rejection_reason = ""
    report.save(update_fields=["state", "submitted_at", "reviewed_by", "reviewed_at", "rejection_reason", "updated_at"])
    record_event(report, "submitted", actor, old, report.state)
    return report


@transaction.atomic
def review_report(report_id, actor, approve, reason=""):
    report = ExpenseReport.objects.select_for_update().get(pk=report_id)
    if report.state != ExpenseReport.State.SUBMITTED:
        raise ValidationError("Solo se pueden revisar reportes enviados.")
    if report.owner_id == actor.pk:
        raise ValidationError("La persona solicitante no puede aprobar su propio reporte.")
    if not approve and not reason.strip():
        raise ValidationError({"reason": "Indica por qué se rechaza el reporte."})
    old = report.state
    report.state = ExpenseReport.State.APPROVED if approve else ExpenseReport.State.REJECTED
    report.reviewed_by = actor
    report.reviewed_at = timezone.now()
    report.rejection_reason = "" if approve else reason.strip()
    report.save(update_fields=["state", "reviewed_by", "reviewed_at", "rejection_reason", "updated_at"])
    record_event(report, "approved" if approve else "rejected", actor, old, report.state, report.rejection_reason)
    return report


@transaction.atomic
def prepare_journal(report_id, actor):
    report = ExpenseReport.objects.select_for_update().select_related("owner").get(pk=report_id)
    if report.state != ExpenseReport.State.APPROVED:
        raise ValidationError("Solo se preparan pólizas para reportes aprobados.")
    configuration = ExpensePostingConfiguration.objects.filter(is_active=True).select_related("journal", "employee_payable_account", "company_funds_account").first()
    if not configuration:
        raise ValidationError("Contabilidad debe activar la configuración de pólizas de gastos.")
    expenses = list(report.expenses.select_related("expense_account"))
    if not expenses:
        raise ValidationError("El reporte no tiene gastos.")
    date = max(expense.expense_date for expense in expenses)
    entry = JournalEntry.objects.create(
        journal=configuration.journal, entry_date=date,
        memo=f"Gastos {report.number}", origin_type="expense_report", origin_id=report.id, created_by=actor,
    )
    for number, expense in enumerate(expenses, 1):
        account = configuration.employee_payable_account if expense.paid_by == Expense.PaidBy.EMPLOYEE else configuration.company_funds_account
        JournalLine.objects.create(entry=entry, line_number=number * 2 - 1, account=expense.expense_account, description=expense.description, debit=expense.amount)
        JournalLine.objects.create(entry=entry, line_number=number * 2, account=account, description=expense.description, credit=expense.amount)
    old = report.state
    report.state = ExpenseReport.State.JOURNAL_DRAFT
    report.journal_entry = entry
    report.save(update_fields=["state", "journal_entry", "updated_at"])
    record_event(report, "journal_draft_created", actor, old, report.state, entry.number)
    return report


@transaction.atomic
def register_reimbursement(report_id, actor, idempotency_key, amount, payment_date, method, reference="", confirm_payment_made=False):
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s)::bigint)", [f"expense-reimbursement:{idempotency_key}"])
    report = ExpenseReport.objects.select_for_update().select_related("journal_entry").get(pk=report_id)
    existing = ExpenseReimbursement.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        same = existing.report_id == report.pk and existing.amount == amount and existing.payment_date == payment_date and existing.method == method and existing.reference == reference
        if same:
            return existing
        raise ValidationError("La clave de reintento ya se utilizó con otros datos.")
    if not confirm_payment_made:
        raise ValidationError({"confirm_payment_made": "Confirma que la transferencia, cheque o entrega de efectivo ya ocurrió."})
    if report.state != ExpenseReport.State.JOURNAL_DRAFT or not report.journal_entry_id or report.journal_entry.state != JournalEntry.State.POSTED:
        raise ValidationError("Contabilidad debe contabilizar primero la póliza del reporte.")
    if JournalEntry.objects.filter(reversal_of=report.journal_entry).exists():
        raise ValidationError("La póliza original del reporte ya está revertida.")
    if payment_date > timezone.localdate():
        raise ValidationError({"payment_date": "La fecha de pago no puede estar en el futuro."})
    configuration = ExpensePostingConfiguration.objects.filter(is_active=True).select_related(
        "reimbursement_journal", "employee_payable_account", "company_funds_account",
    ).first()
    if not configuration or not configuration.reimbursement_journal_id:
        raise ValidationError("Contabilidad debe configurar un diario de banco o caja para reembolsos.")
    required_kind = Journal.Kind.CASH if method == ExpenseReimbursement.Method.CASH else Journal.Kind.BANK
    if configuration.reimbursement_journal.kind != required_kind:
        raise ValidationError("El método de pago no corresponde al tipo de diario configurado.")
    reimbursable = sum(report.expenses.filter(paid_by=Expense.PaidBy.EMPLOYEE).values_list("amount", flat=True), start=Decimal("0.00"))
    payable_lines = report.journal_entry.lines.filter(account=configuration.employee_payable_account)
    payable_credit = sum(payable_lines.values_list("credit", flat=True), start=Decimal("0.00"))
    payable_debit = sum(payable_lines.values_list("debit", flat=True), start=Decimal("0.00"))
    if payable_credit != reimbursable or payable_debit:
        raise ValidationError("La póliza contabilizada no conserva exactamente el pasivo calculado para reembolsar.")
    already_recorded = sum(
        ExpenseReimbursement.objects.filter(report=report, state=ExpenseReimbursement.State.RECORDED).values_list("amount", flat=True),
        start=Decimal("0.00"),
    )
    outstanding = reimbursable - already_recorded
    if amount <= 0 or amount > outstanding:
        raise ValidationError({"amount": f"El importe debe ser mayor que cero y no exceder el saldo pendiente de {outstanding:.2f} MXN."})
    if payment_date < report.journal_entry.entry_date:
        raise ValidationError({"payment_date": "El reembolso no puede preceder a la póliza contabilizada del reporte."})
    ensure_period_open(payment_date)
    reimbursement_id = uuid.uuid4()
    entry = JournalEntry.objects.create(
        journal=configuration.reimbursement_journal,
        entry_date=payment_date,
        memo=f"Reembolso {report.number} · {reference}"[:240],
        origin_type="expense_reimbursement",
        origin_id=reimbursement_id,
        created_by=actor,
    )
    JournalLine.objects.create(
        entry=entry, line_number=1, account=configuration.employee_payable_account,
        description=f"Reembolso {report.number}"[:240], debit=amount,
    )
    JournalLine.objects.create(
        entry=entry, line_number=2, account=configuration.company_funds_account,
        description=f"Pago {method} · {reference}"[:240], credit=amount,
    )
    reimbursement = ExpenseReimbursement.objects.create(
        id=reimbursement_id, report=report, idempotency_key=idempotency_key, amount=amount,
        payment_date=payment_date, method=method, reference=reference, journal_entry=entry,
        registered_by=actor,
    )
    record_event(report, "reimbursement_recorded", actor, report.state, report.state, f"{reimbursement.number} · {amount:.2f} MXN · {entry.number}")
    return reimbursement


@transaction.atomic
def reverse_reimbursement(report_id, reimbursement_id, actor, reason, confirm_payment_returned=False):
    reimbursement = ExpenseReimbursement.objects.select_for_update().select_related(
        "report", "journal_entry",
    ).get(pk=reimbursement_id, report_id=report_id)
    if reimbursement.state == ExpenseReimbursement.State.REVERSED:
        return reimbursement
    if not confirm_payment_returned:
        raise ValidationError({"confirm_payment_returned": "Confirma que el pago fue devuelto, cancelado o registrado por error."})
    if len((reason or "").strip()) < 10:
        raise ValidationError({"reason": "Describe el motivo de la reversa (mínimo 10 caracteres)."})
    if reimbursement.journal_entry.state != JournalEntry.State.POSTED:
        raise ValidationError("Contabilidad debe contabilizar la póliza del pago antes de revertirlo.")
    reversal = reverse_entry(reimbursement.journal_entry_id, actor, authorized_expense_reimbursement=True)
    reimbursement.state = ExpenseReimbursement.State.REVERSED
    reimbursement.reversed_by = actor
    reimbursement.reversed_at = timezone.now()
    reimbursement.reversal_reason = reason.strip()
    reimbursement.reversal_journal_entry = reversal
    reimbursement.save(update_fields=["state", "reversed_by", "reversed_at", "reversal_reason", "reversal_journal_entry"])
    record_event(reimbursement.report, "reimbursement_reversed", actor, "recorded", "reversed", f"{reimbursement.number} · {reason.strip()[:300]}")
    return reimbursement
