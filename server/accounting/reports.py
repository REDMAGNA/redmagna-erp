from decimal import Decimal
from datetime import date

from django.db.models import Sum
from django.utils import timezone

from .models import Account, JournalEntry, JournalLine


ZERO = Decimal("0.00")


def subledger_control_reconciliation(receivable_account, payable_account, as_of=None):
    """Compare customer/vendor open items with their posted general-ledger control accounts."""
    from django.core.exceptions import ValidationError
    from billing.reports import receivables_aging
    from purchasing.reports import payables_aging

    as_of = as_of or timezone.localdate()
    expected = (
        ("receivables", receivable_account, Account.Category.ASSET, Account.BalanceSide.DEBIT, receivables_aging),
        ("payables", payable_account, Account.Category.LIABILITY, Account.BalanceSide.CREDIT, payables_aging),
    )
    result = {"as_of": as_of.isoformat(), "currency": "MXN", "reconciliations": []}
    posted = JournalLine.objects.filter(entry__state=JournalEntry.State.POSTED, entry__entry_date__lte=as_of)
    for key, account, category, normal_balance, aging_report in expected:
        if account.category != category or account.normal_balance != normal_balance:
            raise ValidationError({f"{key}_account": "La cuenta debe tener la clasificación y naturaleza contable esperadas para el auxiliar."})
        totals = posted.filter(account=account).aggregate(debit=Sum("debit"), credit=Sum("credit"))
        net = (totals["debit"] or ZERO) - (totals["credit"] or ZERO)
        control_balance = net if normal_balance == Account.BalanceSide.DEBIT else -net
        subledger = Decimal(aging_report(as_of)["total_balance"])
        difference = subledger - control_balance
        result["reconciliations"].append({
            "key": key,
            "account_id": str(account.pk),
            "account_code": account.code,
            "account_name": account.name,
            "account_normal_balance": normal_balance,
            "control_balance": control_balance.quantize(Decimal("0.01")),
            "subledger_balance": subledger.quantize(Decimal("0.01")),
            "difference": difference.quantize(Decimal("0.01")),
            "reconciled": difference == ZERO,
        })
    return result


def _balances(queryset):
    return {
        row["account_id"]: {
            "debit": row["debit"] or ZERO,
            "credit": row["credit"] or ZERO,
        }
        for row in queryset.values("account_id").annotate(debit=Sum("debit"), credit=Sum("credit"))
    }


def trial_balance(date_from=None, date_to=None):
    posted_lines = JournalLine.objects.filter(entry__state=JournalEntry.State.POSTED)
    if date_to:
        posted_lines = posted_lines.filter(entry__entry_date__lte=date_to)

    opening_totals = {}
    movement_lines = posted_lines
    if date_from:
        opening_totals = _balances(posted_lines.filter(entry__entry_date__lt=date_from))
        movement_lines = posted_lines.filter(entry__entry_date__gte=date_from)
    period_totals = _balances(movement_lines)

    account_ids = set(opening_totals) | set(period_totals)
    accounts = []
    total_opening_debit = total_opening_credit = ZERO
    total_period_debit = total_period_credit = ZERO
    total_closing_debit = total_closing_credit = ZERO
    for account in Account.objects.filter(id__in=account_ids).order_by("code"):
        opening = opening_totals.get(account.id, {"debit": ZERO, "credit": ZERO})
        period = period_totals.get(account.id, {"debit": ZERO, "credit": ZERO})
        opening_net = opening["debit"] - opening["credit"]
        closing_net = opening_net + period["debit"] - period["credit"]
        opening_debit, opening_credit = max(opening_net, ZERO), max(-opening_net, ZERO)
        closing_debit, closing_credit = max(closing_net, ZERO), max(-closing_net, ZERO)
        accounts.append({
            "account_id": str(account.id),
            "code": account.code,
            "name": account.name,
            "category": account.category,
            "opening_debit": opening_debit,
            "opening_credit": opening_credit,
            "period_debit": period["debit"],
            "period_credit": period["credit"],
            "closing_debit": closing_debit,
            "closing_credit": closing_credit,
        })
        total_opening_debit += opening_debit
        total_opening_credit += opening_credit
        total_period_debit += period["debit"]
        total_period_credit += period["credit"]
        total_closing_debit += closing_debit
        total_closing_credit += closing_credit

    return {
        "date_from": date_from.isoformat() if date_from else "",
        "date_to": date_to.isoformat() if date_to else "",
        "accounts": accounts,
        "totals": {
            "opening_debit": total_opening_debit,
            "opening_credit": total_opening_credit,
            "period_debit": total_period_debit,
            "period_credit": total_period_credit,
            "closing_debit": total_closing_debit,
            "closing_credit": total_closing_credit,
        },
    }


def general_ledger(account, date_from=None, date_to=None):
    """Return posted movements for one account with an auditable running balance."""
    posted_lines = JournalLine.objects.filter(
        account_id=account.id,
        entry__state=JournalEntry.State.POSTED,
    )
    if date_to:
        posted_lines = posted_lines.filter(entry__entry_date__lte=date_to)
    opening_totals = {"debit": ZERO, "credit": ZERO}
    period_lines = posted_lines
    if date_from:
        opening_totals = _balances(posted_lines.filter(entry__entry_date__lt=date_from)).get(
            account.id, {"debit": ZERO, "credit": ZERO},
        )
        period_lines = posted_lines.filter(entry__entry_date__gte=date_from)

    transactions = []
    running_net = opening_totals["debit"] - opening_totals["credit"]
    period_debit = period_credit = ZERO
    lines = period_lines.select_related("entry__journal", "entry__reversal_of").order_by(
        "entry__entry_date", "entry__number", "line_number",
    )
    for line in lines:
        running_net += line.debit - line.credit
        period_debit += line.debit
        period_credit += line.credit
        transactions.append({
            "line_id": str(line.id),
            "entry_id": str(line.entry_id),
            "entry_number": line.entry.number,
            "entry_date": line.entry.entry_date.isoformat(),
            "journal_code": line.entry.journal.code,
            "journal_name": line.entry.journal.name,
            "memo": line.entry.memo,
            "description": line.description,
            "origin_type": line.entry.origin_type,
            "origin_id": str(line.entry.origin_id) if line.entry.origin_id else "",
            "reversal_of": line.entry.reversal_of.number if line.entry.reversal_of_id else "",
            "debit": line.debit,
            "credit": line.credit,
            "balance_debit": max(running_net, ZERO),
            "balance_credit": max(-running_net, ZERO),
        })

    closing_net = running_net
    return {
        "account": {
            "id": str(account.id),
            "code": account.code,
            "name": account.name,
            "category": account.category,
            "normal_balance": account.normal_balance,
        },
        "date_from": date_from.isoformat() if date_from else "",
        "date_to": date_to.isoformat() if date_to else "",
        "opening_debit": max(opening_totals["debit"] - opening_totals["credit"], ZERO),
        "opening_credit": max(opening_totals["credit"] - opening_totals["debit"], ZERO),
        "transactions": transactions,
        "period_debit": period_debit,
        "period_credit": period_credit,
        "closing_debit": max(closing_net, ZERO),
        "closing_credit": max(-closing_net, ZERO),
    }


def financial_statements(date_from=None, date_to=None):
    if date_to is None:
        date_to = date.today()
    if date_from is None:
        date_from = date(date_to.year, 1, 1)

    posted = JournalLine.objects.filter(entry__state=JournalEntry.State.POSTED)
    through_date = posted.filter(entry__entry_date__lte=date_to)
    period = through_date.filter(entry__entry_date__gte=date_from)
    balance_totals = _balances(through_date.filter(account__category__in=[Account.Category.ASSET, Account.Category.LIABILITY, Account.Category.EQUITY]))
    period_totals = _balances(period.filter(account__category__in=[Account.Category.INCOME, Account.Category.EXPENSE]))
    accumulated_result_totals = _balances(through_date.filter(account__category__in=[Account.Category.INCOME, Account.Category.EXPENSE]))

    report_account_ids = set(balance_totals) | set(period_totals) | set(accumulated_result_totals)
    accounts = {account.id: account for account in Account.objects.filter(id__in=report_account_ids)}
    income_rows, expense_rows = [], []
    asset_rows, liability_rows, equity_rows = [], [], []
    total_income = total_expenses = total_assets = total_liabilities = total_equity = unclosed_result = ZERO

    for account_id, amounts in period_totals.items():
        account = accounts[account_id]
        if account.category == Account.Category.INCOME:
            value = amounts["credit"] - amounts["debit"]
            income_rows.append({"account_id": str(account.id), "code": account.code, "name": account.name, "amount": value})
            total_income += value
        else:
            value = amounts["debit"] - amounts["credit"]
            expense_rows.append({"account_id": str(account.id), "code": account.code, "name": account.name, "amount": value})
            total_expenses += value

    for account_id, amounts in accumulated_result_totals.items():
        account = accounts[account_id]
        if account.category == Account.Category.INCOME:
            unclosed_result += amounts["credit"] - amounts["debit"]
        else:
            unclosed_result -= amounts["debit"] - amounts["credit"]

    for account_id, amounts in balance_totals.items():
        account = accounts[account_id]
        if account.category == Account.Category.ASSET:
            value = amounts["debit"] - amounts["credit"]
            asset_rows.append({"account_id": str(account.id), "code": account.code, "name": account.name, "amount": value})
            total_assets += value
        elif account.category == Account.Category.LIABILITY:
            value = amounts["credit"] - amounts["debit"]
            liability_rows.append({"account_id": str(account.id), "code": account.code, "name": account.name, "amount": value})
            total_liabilities += value
        else:
            value = amounts["credit"] - amounts["debit"]
            equity_rows.append({"account_id": str(account.id), "code": account.code, "name": account.name, "amount": value})
            total_equity += value

    for rows in [income_rows, expense_rows, asset_rows, liability_rows, equity_rows]:
        rows.sort(key=lambda row: row["code"])

    liabilities_and_equity = total_liabilities + total_equity + unclosed_result
    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "income_statement": {
            "income_accounts": income_rows,
            "expense_accounts": expense_rows,
            "total_income": total_income,
            "total_expenses": total_expenses,
            "net_income": total_income - total_expenses,
        },
        "balance_sheet": {
            "assets": asset_rows,
            "liabilities": liability_rows,
            "equity": equity_rows,
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "total_equity": total_equity,
            "unclosed_result": unclosed_result,
            "liabilities_and_equity": liabilities_and_equity,
            "difference": total_assets - liabilities_and_equity,
        },
    }
