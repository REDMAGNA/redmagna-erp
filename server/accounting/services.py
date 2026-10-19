import re
import unicodedata

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from .models import AccountingPeriod, AccountingPeriodEvent, Account, BankStatement, BankStatementLine, Journal, JournalEntry, JournalLine, PostingConfigurationEvent


def posting_configuration_snapshot(configuration):
    def reference(value):
        if value is None:
            return None
        return {"code": value.code, "name": value.name}

    return {
        "event_type": configuration.event_type,
        "journal": reference(configuration.journal),
        "receivable_account": reference(configuration.receivable_account),
        "revenue_account": reference(configuration.revenue_account),
        "tax_account": reference(configuration.tax_account),
        "funds_account": reference(configuration.funds_account),
        "payable_account": reference(configuration.payable_account),
        "purchase_account": reference(configuration.purchase_account),
        "supplier_tax_account": reference(configuration.supplier_tax_account),
        "is_active": configuration.is_active,
    }


def record_posting_configuration_change(configuration, before, actor):
    after = posting_configuration_snapshot(configuration)
    if before != after:
        PostingConfigurationEvent.objects.create(
            configuration=configuration,
            before=before,
            after=after,
            actor=actor,
        )


def ensure_period_open(entry_date):
    period = AccountingPeriod.objects.select_for_update().filter(period_start__year=entry_date.year, period_start__month=entry_date.month).first()
    if period and period.state == AccountingPeriod.State.CLOSED:
        raise ValidationError(f"El periodo {period.label} está cerrado; solicita su reapertura autorizada.")


@transaction.atomic
def close_accounting_period(period_id, actor, reason=""):
    period = AccountingPeriod.objects.select_for_update().get(pk=period_id)
    if period.state == AccountingPeriod.State.CLOSED:
        return period
    drafts = JournalEntry.objects.filter(state=JournalEntry.State.DRAFT, entry_date__gte=period.period_start, entry_date__lte=period.period_end).count()
    if drafts:
        raise ValidationError({"period": f"No se puede cerrar: hay {drafts} póliza(s) en borrador dentro del periodo."})
    now = timezone.now()
    AccountingPeriod.objects.filter(pk=period.pk).update(state=AccountingPeriod.State.CLOSED, closed_by=actor, closed_at=now, reopened_by=None, reopened_at=None)
    period.state, period.closed_by, period.closed_at = AccountingPeriod.State.CLOSED, actor, now
    AccountingPeriodEvent.objects.create(period=period, action=AccountingPeriodEvent.Action.CLOSED, reason=reason[:500], actor=actor)
    return period


@transaction.atomic
def reopen_accounting_period(period_id, actor, reason):
    period = AccountingPeriod.objects.select_for_update().get(pk=period_id)
    if period.state != AccountingPeriod.State.CLOSED:
        raise ValidationError("Solo se puede reabrir un periodo cerrado.")
    if len((reason or "").strip()) < 10:
        raise ValidationError({"reason": "Explica el motivo de la reapertura (mínimo 10 caracteres)."})
    now = timezone.now()
    AccountingPeriod.objects.filter(pk=period.pk).update(state=AccountingPeriod.State.OPEN, reopened_by=actor, reopened_at=now)
    period.state, period.reopened_by, period.reopened_at = AccountingPeriod.State.OPEN, actor, now
    AccountingPeriodEvent.objects.create(period=period, action=AccountingPeriodEvent.Action.REOPENED, reason=reason.strip()[:500], actor=actor)
    return period


@transaction.atomic
def post_entry(entry_id, actor):
    entry = JournalEntry.objects.select_for_update().select_related("journal").get(pk=entry_id)
    if entry.state != JournalEntry.State.DRAFT:
        raise ValidationError("Solo se pueden contabilizar pólizas en borrador.")
    ensure_period_open(entry.entry_date)
    if not entry.journal.is_active and not entry.reversal_of_id:
        raise ValidationError("No se puede contabilizar en un diario inactivo.")

    lines = list(entry.lines.select_for_update().select_related("account").order_by("line_number"))
    if len(lines) < 2:
        raise ValidationError("Una póliza debe tener al menos dos líneas.")
    if any(not line.account.is_active for line in lines) and not entry.reversal_of_id:
        raise ValidationError("La póliza usa una cuenta inactiva.")
    for line in lines:
        line.clean()

    debits = sum((line.debit for line in lines))
    credits = sum((line.credit for line in lines))
    if debits <= 0 or debits != credits:
        raise ValidationError("La suma de cargos y abonos debe ser igual y mayor que cero.")

    entry.state = JournalEntry.State.POSTED
    entry.posted_by = actor
    entry.posted_at = timezone.now()
    entry.save(update_fields=["state", "posted_by", "posted_at"])
    return entry


@transaction.atomic
def import_opening_balances(actor, journal_id, entry_date, memo, lines):
    journal = Journal.objects.select_for_update().filter(pk=journal_id, is_active=True, kind=Journal.Kind.GENERAL).first()
    if journal is None:
        raise ValidationError({"journal": "Selecciona un diario general activo."})
    if JournalEntry.objects.filter(origin_type="opening_balance_import").exists():
        raise ValidationError("Ya existe una póliza de saldos iniciales. Revísala antes de intentar otra importación.")
    codes = [line["account_code"] for line in lines]
    accounts = {account.code: account for account in Account.objects.select_for_update().filter(code__in=codes).order_by("code").prefetch_related("children")}
    if len(accounts) != len(set(codes)):
        raise ValidationError("El catálogo de cuentas cambió durante la importación; vuelve a cargar los saldos.")
    for code, account in accounts.items():
        if not account.is_active or account.children.filter(is_active=True).exists():
            raise ValidationError({"lines": f"La cuenta {code} ya no está activa o tiene subcuentas activas."})

    try:
        with transaction.atomic():
            entry = JournalEntry.objects.create(
                journal=journal,
                entry_date=entry_date,
                memo=(memo or "Saldos iniciales").strip()[:240],
                origin_type="opening_balance_import",
                created_by=actor,
            )
    except IntegrityError:
        raise ValidationError("Ya existe una póliza de saldos iniciales. Revísala antes de intentar otra importación.") from None
    JournalLine.objects.bulk_create([
        JournalLine(
            entry=entry,
            line_number=index,
            account=accounts[line["account_code"]],
            description=(line.get("description") or "Saldo inicial")[:240],
            debit=line["debit"],
            credit=line["credit"],
        )
        for index, line in enumerate(lines, start=1)
    ])
    return entry


@transaction.atomic
def reverse_entry(entry_id, actor, reversal_date=None, authorized_expense_reimbursement=False, authorized_customer_payment=False, authorized_customer_credit_note=False):
    original = JournalEntry.objects.select_for_update().select_related("journal").get(pk=entry_id)
    if original.state != JournalEntry.State.POSTED:
        raise ValidationError("Solo se pueden revertir pólizas contabilizadas.")
    if JournalEntry.objects.filter(reversal_of=original).exists():
        raise ValidationError("Esta póliza ya tiene una reversa.")
    if original.origin_type == "customer_payment" and not authorized_customer_payment:
        raise ValidationError("Revierte el cobro desde su registro para reabrir el saldo del cliente y conservar su bitácora.")
    if original.origin_type == "billing_customer_credit_note" and not authorized_customer_credit_note:
        raise ValidationError("Revierte la nota desde su registro para reabrir el saldo del cliente y conservar su bitácora.")
    from expenses.models import ExpenseReimbursement, ExpenseReport
    if ExpenseReimbursement.objects.filter(journal_entry=original).exists() and not authorized_expense_reimbursement:
        raise ValidationError("Revierte el reembolso desde su registro para conservar el saldo pendiente y la bitácora.")
    source_report = ExpenseReport.objects.filter(journal_entry=original).first()
    if source_report and source_report.reimbursements.filter(state=ExpenseReimbursement.State.RECORDED).exists():
        raise ValidationError("Revierte primero los reembolsos activos del reporte antes de revertir su póliza de gasto.")

    reversal = JournalEntry.objects.create(
        journal=original.journal,
        entry_date=reversal_date or timezone.localdate(),
        memo=f"Reversa de {original.number}",
        origin_type="journal_reversal",
        origin_id=original.id,
        reversal_of=original,
        created_by=actor,
    )
    for line in original.lines.select_related("account").order_by("line_number"):
        JournalLine.objects.create(
            entry=reversal,
            line_number=line.line_number,
            account=line.account,
            description=f"Reversa · {line.description}"[:240],
            debit=line.credit,
            credit=line.debit,
        )
    return post_entry(reversal.id, actor)


@transaction.atomic
def create_bank_statement(account_id, actor, period_start, period_end, opening_balance, closing_balance, lines):
    account = Account.objects.select_for_update().filter(pk=account_id).first()
    if account is None:
        raise ValidationError({"account": "No se encontró la cuenta bancaria."})
    if not account.is_active or not account.allow_reconciliation or account.category != Account.Category.ASSET:
        raise ValidationError({"account": "Selecciona una cuenta activa de activo con conciliación habilitada."})
    if period_start > period_end:
        raise ValidationError({"period_end": "El final del periodo no puede ser anterior al inicio."})
    if BankStatement.objects.filter(account=account, period_start__lte=period_end, period_end__gte=period_start).exists():
        raise ValidationError({"period_start": "El periodo se cruza con otro estado de cuenta de esta cuenta bancaria. Importa rangos consecutivos sin traslaparse."})

    normalized_lines = []
    movement_total = Decimal("0.00")
    for index, item in enumerate(lines, start=1):
        transaction_date = item["transaction_date"]
        amount = Decimal(item["amount"]).quantize(Decimal("0.01"))
        if not period_start <= transaction_date <= period_end:
            raise ValidationError({"lines": f"La fecha de la línea {index} está fuera del periodo del estado de cuenta."})
        if amount == Decimal("0.00"):
            raise ValidationError({"lines": f"La línea {index} debe tener un importe distinto de cero."})
        normalized_lines.append((index, transaction_date, item.get("reference", ""), item.get("description", ""), amount))
        movement_total += amount
    opening_balance = Decimal(opening_balance).quantize(Decimal("0.01"))
    closing_balance = Decimal(closing_balance).quantize(Decimal("0.01"))
    if opening_balance + movement_total != closing_balance:
        raise ValidationError({"closing_balance": "El saldo inicial más los movimientos debe coincidir exactamente con el saldo final."})

    statement = BankStatement.objects.create(
        account=account,
        period_start=period_start,
        period_end=period_end,
        opening_balance=opening_balance,
        closing_balance=closing_balance,
        created_by=actor,
    )
    BankStatementLine.objects.bulk_create([
        BankStatementLine(
            statement=statement,
            line_number=index,
            transaction_date=transaction_date,
            reference=reference,
            description=description,
            amount=amount,
        )
        for index, transaction_date, reference, description, amount in normalized_lines
    ])
    return statement


@transaction.atomic
def prepare_bank_statement_adjustment(statement_id, line_id, journal_id, counterpart_account_id, memo, actor):
    """Create a balanced draft for an unmatched bank movement, using the account chosen by Accounting."""
    statement = BankStatement.objects.select_for_update().select_related("account").get(pk=statement_id)
    if statement.state != BankStatement.State.OPEN:
        raise ValidationError("Solo se preparan ajustes para una conciliación bancaria abierta.")
    line = BankStatementLine.objects.select_for_update().get(pk=line_id, statement=statement)
    if line.journal_line_id:
        raise ValidationError("Este movimiento ya está conciliado con una póliza.")
    if line.prepared_entry_id:
        return line.prepared_entry, False

    journal = Journal.objects.select_for_update().filter(
        pk=journal_id, is_active=True, kind__in=[Journal.Kind.GENERAL, Journal.Kind.BANK],
    ).first()
    if journal is None:
        raise ValidationError({"journal": "Selecciona un diario general o bancario activo."})
    bank_account = Account.objects.select_for_update().filter(
        pk=statement.account_id, is_active=True, allow_reconciliation=True,
        category=Account.Category.ASSET,
    ).first()
    counterpart = Account.objects.select_for_update().filter(pk=counterpart_account_id, is_active=True).first()
    if bank_account is None or bank_account.children.filter(is_active=True).exists():
        raise ValidationError("La cuenta bancaria de la conciliación debe estar activa y ser una cuenta de movimiento.")
    if counterpart is None or counterpart.pk == bank_account.pk or counterpart.children.filter(is_active=True).exists():
        raise ValidationError({"counterpart_account": "Selecciona una cuenta activa de movimiento distinta de la cuenta bancaria."})
    memo = str(memo or "").strip()
    if len(memo) < 5:
        raise ValidationError({"memo": "Describe el movimiento bancario con al menos 5 caracteres."})

    amount = abs(line.amount)
    entry = JournalEntry.objects.create(
        journal=journal,
        entry_date=line.transaction_date,
        memo=memo[:240],
        origin_type="bank_statement_adjustment",
        origin_id=line.pk,
        created_by=actor,
    )
    if line.amount > 0:
        bank_debit, bank_credit = amount, Decimal("0.00")
        other_debit, other_credit = Decimal("0.00"), amount
    else:
        bank_debit, bank_credit = Decimal("0.00"), amount
        other_debit, other_credit = amount, Decimal("0.00")
    JournalLine.objects.create(
        entry=entry, line_number=1, account=bank_account,
        description=f"Movimiento bancario {line.reference}"[:240], debit=bank_debit, credit=bank_credit,
    )
    JournalLine.objects.create(
        entry=entry, line_number=2, account=counterpart,
        description=memo[:240], debit=other_debit, credit=other_credit,
    )
    line.prepared_entry = entry
    line.save(update_fields=["prepared_entry"])
    return entry, True


def bank_statement_candidates(line):
    candidates = list(
        JournalLine.objects.filter(account_id=line.statement.account_id, entry__state=JournalEntry.State.POSTED)
        .annotate(signed_amount=F("debit") - F("credit"))
        .filter(signed_amount=line.amount, bank_statement_match__isnull=True)
        .select_related("entry", "entry__journal", "account")
        .order_by("entry__entry_date", "entry__number", "line_number")
    )
    bank_reference = _normalize_match_text(line.reference)
    bank_tokens = _match_tokens(line.reference, line.description)
    for candidate in candidates:
        candidate_text = _normalize_match_text(" ".join([
            candidate.entry.number,
            candidate.entry.memo,
            candidate.description,
        ]))
        candidate_tokens = _match_tokens(candidate.entry.number, candidate.entry.memo, candidate.description)
        reasons = []
        score = 0

        if bank_reference:
            if bank_reference == _normalize_match_text(candidate.entry.number):
                score += 60
                reasons.append("Referencia exacta")
            elif len(bank_reference) >= 4 and bank_reference in candidate_text:
                score += 40
                reasons.append("Referencia localizada en la póliza")

        overlap = bank_tokens & candidate_tokens
        if overlap:
            score += min(len(overlap), 3) * 8
            reasons.append("Texto coincidente: " + ", ".join(sorted(overlap)[:3]))

        day_delta = abs((candidate.entry.entry_date - line.transaction_date).days)
        if day_delta == 0:
            score += 32
            reasons.append("Misma fecha")
        elif day_delta <= 3:
            score += 24
            reasons.append(f"Fecha con {day_delta} día(s) de diferencia")
        elif day_delta <= 7:
            score += 16
            reasons.append(f"Fecha con {day_delta} día(s) de diferencia")
        elif day_delta <= 31:
            score += 8
            reasons.append(f"Fecha con {day_delta} día(s) de diferencia")

        candidate.match_score = score
        candidate.match_reasons = reasons
        candidate.match_day_delta = day_delta

    candidates.sort(key=lambda item: (-item.match_score, item.match_day_delta, item.entry.entry_date, item.entry.number, item.line_number))
    return candidates[:200]


@transaction.atomic
def auto_match_bank_statement_references(statement_id, actor):
    statement = BankStatement.objects.select_for_update().get(pk=statement_id)
    if statement.state != BankStatement.State.OPEN:
        raise ValidationError("Solo se pueden vincular referencias en un estado de cuenta abierto.")
    pending = list(statement.lines.select_for_update().filter(journal_line__isnull=True).order_by("line_number"))
    reference_counts = {}
    for line in statement.lines.all():
        reference = _normalize_match_text(line.reference)
        if reference:
            reference_counts[reference] = reference_counts.get(reference, 0) + 1

    proposals = []
    for line in pending:
        reference = _normalize_match_text(line.reference)
        if not reference or reference_counts.get(reference) != 1:
            continue
        candidates = [
            candidate for candidate in bank_statement_candidates(line)
            if "Referencia exacta" in candidate.match_reasons and candidate.match_day_delta <= 3
        ]
        if len(candidates) == 1:
            proposals.append((line, candidates[0]))

    candidate_counts = {}
    for _, candidate in proposals:
        candidate_counts[candidate.pk] = candidate_counts.get(candidate.pk, 0) + 1
    matched = 0
    for line, candidate in proposals:
        if candidate_counts[candidate.pk] == 1:
            match_bank_statement_line(statement.pk, line.pk, candidate.pk, actor)
            matched += 1
    return {"matched": matched, "unmatched": statement.lines.filter(journal_line__isnull=True).count()}


def _normalize_match_text(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(character for character in value if not unicodedata.combining(character))
    return re.sub(r"[^A-Z0-9]+", "", value.upper())


def _match_tokens(*values):
    tokens = set()
    for value in values:
        normalized = unicodedata.normalize("NFKD", str(value or "")).upper()
        normalized = "".join(character for character in normalized if not unicodedata.combining(character))
        tokens.update(token for token in re.findall(r"[A-Z0-9]+", normalized) if len(token) >= 4)
    return tokens


@transaction.atomic
def match_bank_statement_line(statement_id, line_id, journal_line_id, actor):
    statement = BankStatement.objects.select_for_update().get(pk=statement_id)
    if statement.state != BankStatement.State.OPEN:
        raise ValidationError("Solo se pueden conciliar movimientos de un estado de cuenta abierto.")
    line = BankStatementLine.objects.select_for_update().select_related("statement").get(pk=line_id, statement=statement)
    if line.journal_line_id:
        if line.journal_line_id == journal_line_id:
            return line
        raise ValidationError({"line_id": "Este movimiento ya está conciliado con otra línea contable."})
    journal_line = JournalLine.objects.select_for_update().select_related("entry", "account").filter(pk=journal_line_id).first()
    if journal_line is None:
        raise ValidationError({"journal_line": "No se encontró la línea contable seleccionada."})
    if journal_line.entry.state != JournalEntry.State.POSTED:
        raise ValidationError({"journal_line": "Solo se concilia contra líneas de pólizas contabilizadas."})
    if journal_line.account_id != statement.account_id:
        raise ValidationError({"journal_line": "La línea debe usar la cuenta bancaria del estado de cuenta."})
    if journal_line.debit - journal_line.credit != line.amount:
        raise ValidationError({"journal_line": "El importe y la dirección del movimiento no coinciden exactamente."})
    if BankStatementLine.objects.filter(journal_line=journal_line).exclude(pk=line.pk).exists():
        raise ValidationError({"journal_line": "La línea contable ya está conciliada con otro movimiento bancario."})
    line.journal_line = journal_line
    line.matched_by = actor
    line.matched_at = timezone.now()
    line.save(update_fields=["journal_line", "matched_by", "matched_at"])
    return line


@transaction.atomic
def unmatch_bank_statement_line(statement_id, line_id):
    statement = BankStatement.objects.select_for_update().get(pk=statement_id)
    if statement.state != BankStatement.State.OPEN:
        raise ValidationError("No se pueden modificar movimientos de una conciliación cerrada.")
    line = BankStatementLine.objects.select_for_update().get(pk=line_id, statement=statement)
    if line.journal_line_id is None:
        return line
    line.journal_line = None
    line.matched_by = None
    line.matched_at = None
    line.save(update_fields=["journal_line", "matched_by", "matched_at"])
    return line


@transaction.atomic
def reconcile_bank_statement(statement_id, actor):
    statement = BankStatement.objects.select_for_update().get(pk=statement_id)
    if statement.state == BankStatement.State.RECONCILED:
        return statement
    if statement.balance_difference != Decimal("0.00"):
        raise ValidationError({"closing_balance": "El saldo calculado no coincide con el estado de cuenta."})
    unmatched = statement.lines.filter(journal_line__isnull=True).count()
    if unmatched:
        raise ValidationError({"lines": f"Concilia los {unmatched} movimientos pendientes antes de cerrar."})
    statement.state = BankStatement.State.RECONCILED
    statement.reconciled_by = actor
    statement.reconciled_at = timezone.now()
    statement.save(update_fields=["state", "reconciled_by", "reconciled_at"])
    return statement
