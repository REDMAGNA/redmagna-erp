import uuid
from decimal import Decimal
from calendar import monthrange

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone


class Account(models.Model):
    class Category(models.TextChoices):
        ASSET = "asset", "Activo"
        LIABILITY = "liability", "Pasivo"
        EQUITY = "equity", "Capital"
        INCOME = "income", "Ingreso"
        EXPENSE = "expense", "Gasto"

    class BalanceSide(models.TextChoices):
        DEBIT = "debit", "Deudora"
        CREDIT = "credit", "Acreedora"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=180)
    category = models.CharField(max_length=12, choices=Category.choices)
    normal_balance = models.CharField(max_length=6, choices=BalanceSide.choices)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="children")
    allow_reconciliation = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code"]

    def clean(self):
        if self.parent_id == self.id:
            raise ValidationError({"parent": "Una cuenta no puede ser padre de sí misma."})
        if self.pk and not self.is_active and self.children.filter(is_active=True).exists():
            raise ValidationError({"is_active": "Reclasifica o desactiva primero las subcuentas activas."})
        if self.parent_id and not self.parent.is_active:
            raise ValidationError({"parent": "Selecciona una cuenta padre activa."})
        current = self.parent
        seen = set()
        while current:
            if self.pk and current.pk == self.pk:
                raise ValidationError({"parent": "La jerarquía no puede crear una dependencia circular."})
            if current.pk in seen:
                raise ValidationError({"parent": "La jerarquía existente contiene un ciclo; corrígelo antes de continuar."})
            seen.add(current.pk)
            current = current.parent
        if self.pk and not self.is_active and PostingConfiguration.objects.filter(is_active=True).filter(
            Q(receivable_account_id=self.pk) | Q(revenue_account_id=self.pk) | Q(tax_account_id=self.pk)
            | Q(funds_account_id=self.pk) | Q(payable_account_id=self.pk) | Q(purchase_account_id=self.pk)
            | Q(supplier_tax_account_id=self.pk)
        ).exists():
            raise ValidationError({"is_active": "Desactiva primero las reglas automáticas que usan esta cuenta."})

    def save(self, *args, **kwargs):
        if not self._state.adding and JournalLine.objects.filter(account_id=self.pk).exists():
            previous = Account.objects.get(pk=self.pk)
            protected = ["code", "name", "category", "normal_balance", "parent_id"]
            if any(getattr(previous, field) != getattr(self, field) for field in protected):
                raise ValidationError("No cambies la estructura de una cuenta que ya tiene movimientos; desactívala y crea otra.")
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} · {self.name}"


class Journal(models.Model):
    class Kind(models.TextChoices):
        SALES = "sales", "Ventas"
        PURCHASES = "purchases", "Compras"
        BANK = "bank", "Banco"
        CASH = "cash", "Caja"
        GENERAL = "general", "General"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=12, unique=True)
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def clean(self):
        if self.pk and not self.is_active and PostingConfiguration.objects.filter(journal_id=self.pk, is_active=True).exists():
            raise ValidationError({"is_active": "Desactiva primero las reglas automáticas que usan este diario."})

    def save(self, *args, **kwargs):
        if not self._state.adding and JournalEntry.objects.filter(journal_id=self.pk).exists():
            previous = Journal.objects.get(pk=self.pk)
            if any(getattr(previous, field) != getattr(self, field) for field in ["code", "name", "kind"]):
                raise ValidationError("No cambies el código o tipo de un diario que ya tiene pólizas; desactívalo y crea otro.")
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} · {self.name}"


class AccountingPeriod(models.Model):
    class State(models.TextChoices):
        OPEN = "open", "Abierto"
        CLOSED = "closed", "Cerrado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    period_start = models.DateField(unique=True)
    period_end = models.DateField()
    state = models.CharField(max_length=8, choices=State.choices, default=State.OPEN, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_accounting_periods")
    created_at = models.DateTimeField(auto_now_add=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="closed_accounting_periods")
    closed_at = models.DateTimeField(null=True, blank=True)
    reopened_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="reopened_accounting_periods")
    reopened_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-period_start"]
        permissions = [
            ("close_accountingperiod", "Puede cerrar periodos contables"),
            ("reopen_accountingperiod", "Puede reabrir periodos contables"),
        ]
        constraints = [models.CheckConstraint(condition=models.Q(period_end__gte=models.F("period_start")), name="accounting_period_date_order")]

    def clean(self):
        if self.period_start and self.period_end:
            last_day = monthrange(self.period_start.year, self.period_start.month)[1]
            expected_end = self.period_start.replace(day=last_day)
            if self.period_start.day != 1 or self.period_end != expected_end:
                raise ValidationError("El periodo debe cubrir un mes calendario completo.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = AccountingPeriod.objects.get(pk=self.pk)
            if (previous.period_start, previous.period_end) != (self.period_start, self.period_end):
                raise ValidationError("Las fechas de un periodo contable no se pueden cambiar.")
            if previous.state != self.state:
                raise ValidationError("Usa el flujo autorizado para cerrar o reabrir el periodo.")
        self.clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los periodos contables se conservan para el historial.")

    @property
    def label(self):
        return self.period_start.strftime("%Y-%m")


class AccountingPeriodEvent(models.Model):
    class Action(models.TextChoices):
        CLOSED = "closed", "Cerrado"
        REOPENED = "reopened", "Reabierto"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    period = models.ForeignKey(AccountingPeriod, on_delete=models.PROTECT, related_name="events")
    action = models.CharField(max_length=10, choices=Action.choices)
    reason = models.CharField(max_length=500, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="accounting_period_events")
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Los eventos del cierre contable son inmutables.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los eventos del cierre contable no se pueden borrar.")


class JournalEntry(models.Model):
    class State(models.TextChoices):
        DRAFT = "draft", "Borrador"
        POSTED = "posted", "Contabilizada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journal = models.ForeignKey(Journal, on_delete=models.PROTECT, related_name="entries")
    number = models.CharField(max_length=40, unique=True, blank=True)
    entry_date = models.DateField(default=timezone.localdate, db_index=True)
    memo = models.CharField(max_length=240)
    origin_type = models.CharField(max_length=40, blank=True)
    origin_id = models.UUIDField(null=True, blank=True)
    reversal_of = models.OneToOneField("self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversal")
    state = models.CharField(max_length=8, choices=State.choices, default=State.DRAFT, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_journal_entries")
    created_at = models.DateTimeField(auto_now_add=True)
    posted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="posted_journal_entries")
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-entry_date", "-number"]
        permissions = [
            ("post_journalentry", "Puede contabilizar pólizas"),
            ("reverse_journalentry", "Puede revertir pólizas contabilizadas"),
        ]
        constraints = [models.UniqueConstraint(fields=["origin_type"], condition=Q(origin_type="opening_balance_import"), name="accounting_single_opening_import")]

    @transaction.atomic
    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = JournalEntry.objects.select_for_update().get(pk=self.pk)
            if previous.number and (previous.journal_id != self.journal_id or previous.entry_date.year != self.entry_date.year):
                raise ValidationError("No se puede cambiar el diario o ejercicio de una póliza numerada.")
            if previous.origin_type == "opening_balance_import" and self.origin_type != previous.origin_type:
                raise ValidationError("El origen de una póliza de saldos iniciales no se puede modificar.")
            if previous.origin_type == "bank_statement_adjustment" and (
                self.origin_type != previous.origin_type
                or self.origin_id != previous.origin_id
                or self.entry_date != previous.entry_date
            ):
                raise ValidationError("El origen y la fecha de una póliza de ajuste bancario ligada al extracto son inmutables.")
            if previous.state == self.State.POSTED:
                protected = ["journal_id", "number", "entry_date", "memo", "origin_type", "origin_id", "reversal_of_id", "state", "created_by_id", "posted_by_id", "posted_at"]
                if any(getattr(previous, field) != getattr(self, field) for field in protected):
                    raise ValidationError("Una póliza contabilizada es inmutable; crea una reversa.")
        period = AccountingPeriod.objects.select_for_update().filter(
            period_start__year=self.entry_date.year,
            period_start__month=self.entry_date.month,
        ).first() if self.entry_date else None
        if period and period.state == AccountingPeriod.State.CLOSED:
            raise ValidationError("No se pueden crear ni fechar pólizas en un periodo cerrado.")
        statement_line = BankStatementLine.objects.select_related("statement").filter(prepared_entry_id=self.pk).first() if self.pk else None
        if statement_line and (self.origin_type != "bank_statement_adjustment" or self.origin_id != statement_line.pk or self.entry_date != statement_line.transaction_date):
            raise ValidationError("La póliza debe conservar el origen y la fecha del movimiento bancario vinculado.")
        if statement_line:
            bank_lines = self.lines.filter(account_id=statement_line.statement.account_id)
            if bank_lines.count() != 1 or bank_lines.get().debit - bank_lines.get().credit != statement_line.amount:
                raise ValidationError("La línea de banco de la póliza debe conservar la cuenta, importe y dirección del extracto.")
        if not self.number:
            with transaction.atomic():
                journal = Journal.objects.select_for_update().get(pk=self.journal_id)
                if not journal.is_active and not self.reversal_of_id:
                    raise ValidationError({"journal": "No se pueden crear pólizas en un diario inactivo."})
                prefix = f"{journal.code}-{self.entry_date.year}-"
                last_number = JournalEntry.objects.filter(number__startswith=prefix).order_by("-number").values_list("number", flat=True).first()
                sequence = int(last_number.rsplit("-", 1)[1]) + 1 if last_number else 1
                self.number = f"{prefix}{sequence:06d}"
                return super().save(*args, **kwargs)
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las pólizas no se eliminan; se revierten para conservar el historial.")

    @property
    def debit_total(self):
        return sum((line.debit for line in self.lines.all()), Decimal("0.00"))

    @property
    def credit_total(self):
        return sum((line.credit for line in self.lines.all()), Decimal("0.00"))

    def __str__(self):
        return self.number or str(self.id)


class JournalLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name="lines")
    line_number = models.PositiveSmallIntegerField()
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="journal_lines")
    description = models.CharField(max_length=240, blank=True)
    debit = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"))
    credit = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["line_number"]
        constraints = [
            models.UniqueConstraint(fields=["entry", "line_number"], name="accounting_entry_line_number_uniq"),
            models.CheckConstraint(
                condition=(
                    Q(debit__gte=0)
                    & Q(credit__gte=0)
                    & (Q(debit=0) | Q(credit=0))
                    & ~(Q(debit=0) & Q(credit=0))
                ),
                name="accounting_line_one_positive_side",
            ),
        ]

    def clean(self):
        if self.debit < 0 or self.credit < 0:
            raise ValidationError("Cargos y abonos no pueden ser negativos.")
        if (self.debit > 0) == (self.credit > 0):
            raise ValidationError("Cada línea debe tener un cargo o un abono, no ambos ni ninguno.")
        is_reversal = bool(self.entry_id and JournalEntry.objects.only("reversal_of_id").get(pk=self.entry_id).reversal_of_id)
        if self.account_id and not self.account.is_active and not is_reversal:
            raise ValidationError({"account": "No se pueden usar cuentas inactivas en una nueva línea."})
        if self.entry_id:
            statement_line = BankStatementLine.objects.select_related("statement").filter(prepared_entry_id=self.entry_id).first()
            if statement_line and self.account_id == statement_line.statement.account_id:
                if self.debit - self.credit != statement_line.amount:
                    raise ValidationError("La línea bancaria debe conservar el importe y dirección del extracto.")
                existing_bank_lines = JournalLine.objects.filter(entry_id=self.entry_id, account_id=statement_line.statement.account_id).exclude(pk=self.pk)
                if existing_bank_lines.exists():
                    raise ValidationError("La póliza de ajuste solo puede tener una línea para la cuenta del extracto.")

    def save(self, *args, **kwargs):
        with transaction.atomic():
            previous = None
            if not self._state.adding:
                previous = JournalLine.objects.select_for_update().get(pk=self.pk)
            if self.entry_id:
                entry = JournalEntry.objects.select_for_update().only("state").get(pk=self.entry_id)
                if entry.state != JournalEntry.State.DRAFT:
                    raise ValidationError("No se pueden cambiar líneas de una póliza contabilizada.")
                statement_line = BankStatementLine.objects.select_related("statement").filter(prepared_entry_id=self.entry_id).first()
                if statement_line and previous:
                    if previous.account_id == statement_line.statement.account_id and (
                        self.account_id != statement_line.statement.account_id
                        or self.debit - self.credit != statement_line.amount
                    ):
                        raise ValidationError("La línea bancaria del ajuste debe conservar la cuenta, importe y dirección del extracto.")
            if previous and previous.entry_id != self.entry_id:
                prior_link = BankStatementLine.objects.select_related("statement").filter(prepared_entry_id=previous.entry_id).first()
                if prior_link and previous.account_id == prior_link.statement.account_id:
                    raise ValidationError("No se puede mover la línea de banco fuera de la póliza vinculada al extracto.")
            self.clean()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            entry = JournalEntry.objects.select_for_update().get(pk=self.entry_id)
            if entry.state != JournalEntry.State.DRAFT:
                raise ValidationError("No se pueden borrar líneas de una póliza contabilizada.")
            statement_line = BankStatementLine.objects.select_related("statement").filter(prepared_entry_id=self.entry_id).first()
            if statement_line and self.account_id == statement_line.statement.account_id:
                raise ValidationError("La línea bancaria del ajuste está ligada al extracto y no se puede quitar.")
            return super().delete(*args, **kwargs)


class BankStatement(models.Model):
    class State(models.TextChoices):
        OPEN = "open", "Pendiente de conciliación"
        RECONCILED = "reconciled", "Conciliado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="bank_statements")
    period_start = models.DateField()
    period_end = models.DateField()
    opening_balance = models.DecimalField(max_digits=16, decimal_places=2)
    closing_balance = models.DecimalField(max_digits=16, decimal_places=2)
    state = models.CharField(max_length=12, choices=State.choices, default=State.OPEN, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_bank_statements")
    created_at = models.DateTimeField(auto_now_add=True)
    reconciled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="reconciled_bank_statements")
    reconciled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-period_end", "account__code"]
        permissions = [("reconcile_bankstatement", "Puede cerrar una conciliación bancaria")]
        constraints = [
            models.CheckConstraint(condition=models.Q(period_end__gte=models.F("period_start")), name="accounting_statement_period_order"),
            models.UniqueConstraint(fields=["account", "period_start", "period_end"], name="accounting_statement_period_uniq"),
        ]

    def clean(self):
        if self.period_start and self.period_end and self.period_start > self.period_end:
            raise ValidationError({"period_end": "El final del periodo no puede ser anterior al inicio."})
        if self.account_id and (not self.account.is_active or not self.account.allow_reconciliation or self.account.category != Account.Category.ASSET):
            raise ValidationError({"account": "Selecciona una cuenta activa de activo con conciliación habilitada."})

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = BankStatement.objects.get(pk=self.pk)
            if previous.state == self.State.RECONCILED and any(
                getattr(previous, field) != getattr(self, field)
                for field in ("account_id", "period_start", "period_end", "opening_balance", "closing_balance", "state", "created_by_id", "reconciled_by_id", "reconciled_at")
            ):
                raise ValidationError("Una conciliación cerrada es inmutable; corrígela mediante el proceso contable autorizado.")
        self.clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las conciliaciones bancarias no se eliminan; conserva el historial.")

    @property
    def movement_total(self):
        return self.lines.aggregate(total=models.Sum("amount"))["total"] or Decimal("0.00")

    @property
    def calculated_closing_balance(self):
        return self.opening_balance + self.movement_total

    @property
    def balance_difference(self):
        return self.calculated_closing_balance - self.closing_balance


class BankStatementLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    statement = models.ForeignKey(BankStatement, on_delete=models.PROTECT, related_name="lines")
    line_number = models.PositiveIntegerField()
    transaction_date = models.DateField()
    reference = models.CharField(max_length=120, blank=True)
    description = models.CharField(max_length=240, blank=True)
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    journal_line = models.OneToOneField(JournalLine, null=True, blank=True, on_delete=models.PROTECT, related_name="bank_statement_match")
    prepared_entry = models.OneToOneField(JournalEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="bank_statement_adjustment_line")
    matched_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="matched_bank_statement_lines")
    matched_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["transaction_date", "line_number"]
        constraints = [
            models.UniqueConstraint(fields=["statement", "line_number"], name="accounting_statement_line_number_uniq"),
            models.CheckConstraint(condition=~models.Q(amount=Decimal("0.00")), name="accounting_statement_line_nonzero"),
        ]

    def clean(self):
        if not self.amount:
            raise ValidationError({"amount": "El movimiento bancario debe tener un importe distinto de cero."})
        if self.statement_id and self.transaction_date and not self.statement.period_start <= self.transaction_date <= self.statement.period_end:
            raise ValidationError({"transaction_date": "La fecha del movimiento debe pertenecer al periodo del estado de cuenta."})
        if self.journal_line_id:
            journal_line = self.journal_line
            if journal_line.entry.state != JournalEntry.State.POSTED:
                raise ValidationError({"journal_line": "Solo se concilia contra líneas de pólizas contabilizadas."})
            if journal_line.account_id != self.statement.account_id:
                raise ValidationError({"journal_line": "La línea debe usar la misma cuenta bancaria del estado de cuenta."})
            if journal_line.debit - journal_line.credit != self.amount:
                raise ValidationError({"journal_line": "El importe y la dirección del movimiento no coinciden exactamente."})
        if self.prepared_entry_id:
            entry = self.prepared_entry
            bank_lines = entry.lines.filter(account_id=self.statement.account_id)
            if (entry.origin_type != "bank_statement_adjustment" or entry.origin_id != self.pk
                    or entry.entry_date != self.transaction_date or bank_lines.count() != 1):
                raise ValidationError("La póliza borrador vinculada debe conservar el origen y una sola línea para esta cuenta bancaria.")
            bank_line = bank_lines.get()
            if bank_line.debit - bank_line.credit != self.amount:
                raise ValidationError("La póliza borrador vinculada no coincide con el importe o dirección del movimiento.")

    def save(self, *args, **kwargs):
        with transaction.atomic():
            statement = BankStatement.objects.select_for_update().get(pk=self.statement_id)
            if statement.state != BankStatement.State.OPEN:
                raise ValidationError("No se pueden cambiar movimientos de una conciliación cerrada.")
            if not self._state.adding and BankStatementLine.objects.filter(pk=self.pk).filter(
                Q(journal_line__isnull=False) | Q(prepared_entry__isnull=False)
            ).exists():
                previous = BankStatementLine.objects.get(pk=self.pk)
                if any(getattr(previous, field) != getattr(self, field) for field in ("statement_id", "line_number", "transaction_date", "reference", "description", "amount")):
                    raise ValidationError("No se pueden editar datos importados después de conciliar el movimiento.")
            self.clean()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        statement = BankStatement.objects.select_for_update().get(pk=self.statement_id)
        if statement.state != BankStatement.State.OPEN:
            raise ValidationError("No se pueden borrar movimientos de una conciliación cerrada.")
        if self.journal_line_id or self.prepared_entry_id:
            raise ValidationError("No se puede borrar un movimiento con vínculo contable; conserva el historial.")
        return super().delete(*args, **kwargs)


class PostingConfiguration(models.Model):
    class EventType(models.TextChoices):
        CUSTOMER_INVOICE = "customer_invoice", "Factura de cliente"
        CUSTOMER_CREDIT_NOTE = "customer_credit_note", "Nota de crédito de cliente"
        CUSTOMER_PAYMENT = "customer_payment", "Cobro de cliente"
        SUPPLIER_BILL = "supplier_bill", "Factura de proveedor"
        SUPPLIER_PAYMENT = "supplier_payment", "Pago a proveedor"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type = models.CharField(max_length=24, choices=EventType.choices, unique=True)
    journal = models.ForeignKey(Journal, on_delete=models.PROTECT, related_name="posting_configurations")
    receivable_account = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="receivable_posting_configurations")
    revenue_account = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="revenue_posting_configurations")
    tax_account = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="tax_posting_configurations")
    funds_account = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="funds_posting_configurations")
    payable_account = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="payable_posting_configurations")
    purchase_account = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="purchase_posting_configurations")
    supplier_tax_account = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="supplier_tax_posting_configurations")
    is_active = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["event_type"]
        verbose_name = "Configuración de generación de pólizas"
        verbose_name_plural = "Configuraciones de generación de pólizas"

    def clean(self):
        if self.journal_id and not self.journal.is_active:
            raise ValidationError({"journal": "Selecciona un diario activo."})
        account_fields = ["receivable_account", "revenue_account", "tax_account", "funds_account", "payable_account", "purchase_account", "supplier_tax_account"]
        for field in account_fields:
            account_id = getattr(self, f"{field}_id")
            if account_id and not getattr(self, field).is_active:
                raise ValidationError({field: "Selecciona una cuenta activa."})
        if self.event_type in [self.EventType.CUSTOMER_INVOICE, self.EventType.CUSTOMER_CREDIT_NOTE]:
            if not self.receivable_account_id or self.payable_account_id or self.purchase_account_id or self.supplier_tax_account_id:
                raise ValidationError("La configuración de venta debe usar cuenta por cobrar y no cuentas de compras/proveedores.")
            if not self.revenue_account_id:
                raise ValidationError({"revenue_account": "Configura la cuenta de ingresos para ventas y notas de crédito."})
            if self.is_active and not self.tax_account_id:
                raise ValidationError({"tax_account": "Configura la cuenta de IVA trasladado antes de activar esta regla."})
            if self.funds_account_id:
                raise ValidationError({"funds_account": "Las facturas y notas de crédito no usan cuenta de banco/caja."})
            if self.journal_id and self.journal.kind != Journal.Kind.SALES:
                raise ValidationError({"journal": "Usa un diario de ventas para facturas de clientes."})
            if self.receivable_account_id and self.receivable_account.category != Account.Category.ASSET:
                raise ValidationError({"receivable_account": "La cuenta por cobrar debe ser de activo."})
            if self.revenue_account_id and self.revenue_account.category != Account.Category.INCOME:
                raise ValidationError({"revenue_account": "La cuenta de ventas debe ser de ingresos."})
            if self.tax_account_id and self.tax_account.category != Account.Category.LIABILITY:
                raise ValidationError({"tax_account": "La cuenta de impuestos trasladados debe ser de pasivo."})
        elif self.event_type == self.EventType.CUSTOMER_PAYMENT:
            if not self.receivable_account_id or self.payable_account_id or self.purchase_account_id or self.supplier_tax_account_id:
                raise ValidationError("La configuración de cobros debe usar cuenta por cobrar y no cuentas de compras/proveedores.")
            if not self.funds_account_id:
                raise ValidationError({"funds_account": "Configura la cuenta de banco/caja para cobros."})
            if self.revenue_account_id or self.tax_account_id:
                raise ValidationError("Los cobros no usan cuentas de ingresos o impuestos.")
            if self.journal_id and self.journal.kind not in [Journal.Kind.BANK, Journal.Kind.CASH]:
                raise ValidationError({"journal": "Usa un diario de banco o caja para cobros."})
            if self.receivable_account_id and self.receivable_account.category != Account.Category.ASSET:
                raise ValidationError({"receivable_account": "La cuenta por cobrar debe ser de activo."})
            if self.funds_account_id and self.funds_account.category != Account.Category.ASSET:
                raise ValidationError({"funds_account": "La cuenta de banco/caja debe ser de activo."})
        elif self.event_type == self.EventType.SUPPLIER_BILL:
            if not self.payable_account_id or not self.purchase_account_id or self.receivable_account_id or self.revenue_account_id or self.tax_account_id or self.funds_account_id:
                raise ValidationError("Configura cuenta por pagar y cuenta de compras; no uses cuentas de clientes, ventas o fondos.")
            if self.is_active and not self.supplier_tax_account_id:
                raise ValidationError({"supplier_tax_account": "Configura la cuenta para impuestos de proveedor antes de activar esta regla."})
            if self.journal_id and self.journal.kind != Journal.Kind.PURCHASES:
                raise ValidationError({"journal": "Usa un diario de compras para facturas de proveedor."})
            if self.payable_account.category != Account.Category.LIABILITY:
                raise ValidationError({"payable_account": "La cuenta por pagar debe ser de pasivo."})
            if self.purchase_account.category not in [Account.Category.ASSET, Account.Category.EXPENSE]:
                raise ValidationError({"purchase_account": "La cuenta de compra debe ser de activo o gasto."})
            if self.supplier_tax_account_id and self.supplier_tax_account.category not in [Account.Category.ASSET, Account.Category.EXPENSE]:
                raise ValidationError({"supplier_tax_account": "La cuenta del impuesto declarado debe ser de activo o gasto."})
        elif self.event_type == self.EventType.SUPPLIER_PAYMENT:
            if not self.payable_account_id or not self.funds_account_id or self.receivable_account_id or self.revenue_account_id or self.tax_account_id or self.purchase_account_id or self.supplier_tax_account_id:
                raise ValidationError("Configura cuenta por pagar y banco/caja; no uses cuentas de clientes, ventas o compras.")
            if self.journal_id and self.journal.kind not in [Journal.Kind.BANK, Journal.Kind.CASH]:
                raise ValidationError({"journal": "Usa un diario de banco o caja para pagos a proveedores."})
            if self.payable_account.category != Account.Category.LIABILITY:
                raise ValidationError({"payable_account": "La cuenta por pagar debe ser de pasivo."})
            if self.funds_account.category != Account.Category.ASSET:
                raise ValidationError({"funds_account": "La cuenta de banco/caja debe ser de activo."})

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.get_event_type_display()


class PostingConfigurationEvent(models.Model):
    """Append-only snapshots of changes to automatic journal mappings."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    configuration = models.ForeignKey(PostingConfiguration, on_delete=models.PROTECT, related_name="change_history")
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="posting_configuration_events")
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]
        verbose_name = "Cambio de configuración de póliza"
        verbose_name_plural = "Cambios de configuración de pólizas"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("El historial de configuración contable es inmutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("El historial de configuración contable no se elimina.")


class OpeningBalanceBatch(models.Model):
    class State(models.TextChoices):
        DRAFT = "draft", "Pendiente de revisión"
        POSTED = "posted", "Publicada"
        REJECTED = "rejected", "Rechazada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cutoff_date = models.DateField()
    csv_sha256 = models.CharField(max_length=64, db_index=True)
    receivables_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="receivable_opening_batches")
    payables_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="payable_opening_batches")
    receivables_total = models.DecimalField(max_digits=16, decimal_places=2)
    payables_total = models.DecimalField(max_digits=16, decimal_places=2)
    item_count = models.PositiveIntegerField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="prepared_opening_balance_batches")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    state = models.CharField(max_length=10, choices=State.choices, default=State.DRAFT, db_index=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="reviewed_opening_balance_batches")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = [
            ("prepare_openingbalancebatch", "Puede preparar lotes de saldos auxiliares"),
            ("review_openingbalancebatch", "Puede revisar y publicar lotes de saldos auxiliares"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["csv_sha256", "cutoff_date", "receivables_account", "payables_account"],
                condition=models.Q(state__in=["draft", "posted"]),
                name="accounting_opening_batch_idempotent_uniq",
            ),
        ]

    def clean(self):
        if self.receivables_account_id and (self.receivables_account.category != Account.Category.ASSET or self.receivables_account.normal_balance != Account.BalanceSide.DEBIT):
            raise ValidationError({"receivables_account": "La cuenta de CxC debe ser activo de naturaleza deudora."})
        if self.payables_account_id and (self.payables_account.category != Account.Category.LIABILITY or self.payables_account.normal_balance != Account.BalanceSide.CREDIT):
            raise ValidationError({"payables_account": "La cuenta de CxP debe ser pasivo de naturaleza acreedora."})
        if self.receivables_account_id == self.payables_account_id:
            raise ValidationError("CxC y CxP deben usar cuentas de control distintas.")
        if len(self.csv_sha256) != 64 or any(character not in "0123456789abcdef" for character in self.csv_sha256.lower()):
            raise ValidationError({"csv_sha256": "La huella del archivo debe ser SHA-256 hexadecimal."})
        if self.receivables_total < 0 or self.payables_total < 0 or self.item_count < 1:
            raise ValidationError("El lote debe conservar totales no negativos y al menos una partida.")
        if self.state == self.State.DRAFT and (self.reviewed_by_id or self.reviewed_at or self.review_note):
            raise ValidationError("Un lote pendiente de revisión no puede registrar una decisión de revisión.")
        if self.state in [self.State.POSTED, self.State.REJECTED]:
            if not self.reviewed_by_id or not self.reviewed_at or self.reviewed_by_id == self.created_by_id:
                raise ValidationError("La decisión requiere una persona revisora distinta de quien preparó el lote.")
            if self.state == self.State.REJECTED and len(self.review_note.strip()) < 10:
                raise ValidationError({"review_note": "Explica el rechazo en al menos 10 caracteres."})
        if self.pk and self.state == self.State.POSTED:
            if self.items.count() != self.item_count or self.items.filter(is_reserved=False).exists():
                raise ValidationError("Todas las partidas del lote deben permanecer reservadas antes de publicarlo.")
            if self.items.filter(direction="cxc", customer_invoice__isnull=True).exists() or self.items.filter(direction="cxp", supplier_bill__isnull=True).exists():
                raise ValidationError("Cada partida debe vincularse con su factura interna antes de publicar el lote.")
        if self.pk and self.state == self.State.REJECTED and self.items.filter(is_reserved=True).exists():
            raise ValidationError("Libera las referencias externas reservadas antes de rechazar el lote.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = OpeningBalanceBatch.objects.select_for_update().get(pk=self.pk)
            if previous.state != self.State.DRAFT:
                raise ValidationError("Un lote revisado es inmutable.")
            protected = ["cutoff_date", "csv_sha256", "receivables_account_id", "payables_account_id", "receivables_total", "payables_total", "item_count", "created_by_id", "created_at"]
            if any(getattr(previous, field) != getattr(self, field) for field in protected):
                raise ValidationError("No se pueden cambiar los datos de origen del lote; prepara una nueva vista previa.")
            if self.state not in [self.State.DRAFT, self.State.POSTED, self.State.REJECTED]:
                raise ValidationError("Estado de revisión no válido.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los lotes de apertura se conservan; usa su flujo de rechazo para mantener la bitácora.")


class OpeningBalanceItem(models.Model):
    class Direction(models.TextChoices):
        RECEIVABLE = "cxc", "Cuenta por cobrar"
        PAYABLE = "cxp", "Cuenta por pagar"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(OpeningBalanceBatch, on_delete=models.PROTECT, related_name="items")
    direction = models.CharField(max_length=3, choices=Direction.choices, db_index=True)
    counterparty_rfc = models.CharField(max_length=13)
    source_system = models.CharField(max_length=120)
    external_number = models.CharField(max_length=120)
    issue_date = models.DateField()
    due_date = models.DateField()
    currency = models.CharField(max_length=3, default="MXN")
    original_total = models.DecimalField(max_digits=16, decimal_places=2)
    paid_before_cutoff = models.DecimalField(max_digits=16, decimal_places=2)
    open_balance = models.DecimalField(max_digits=16, decimal_places=2)
    is_reserved = models.BooleanField(default=True, db_index=True)
    customer_invoice = models.OneToOneField("billing.CustomerInvoice", null=True, blank=True, on_delete=models.PROTECT, related_name="opening_balance_item")
    supplier_bill = models.OneToOneField("purchasing.SupplierBill", null=True, blank=True, on_delete=models.PROTECT, related_name="opening_balance_item")

    class Meta:
        ordering = ["direction", "counterparty_rfc", "external_number"]
        constraints = [
            models.UniqueConstraint(Lower("direction"), Lower("counterparty_rfc"), Lower("source_system"), Lower("external_number"), condition=models.Q(is_reserved=True), name="accounting_opening_external_item_uniq"),
            models.CheckConstraint(condition=models.Q(currency="MXN"), name="accounting_opening_item_mxn"),
            models.CheckConstraint(condition=models.Q(original_total__gt=0) & models.Q(paid_before_cutoff__gte=0) & models.Q(open_balance__gt=0) & models.Q(original_total=models.F("paid_before_cutoff") + models.F("open_balance")), name="accounting_opening_item_amounts_valid"),
            models.CheckConstraint(condition=(models.Q(direction="cxc", supplier_bill__isnull=True) | models.Q(direction="cxp", customer_invoice__isnull=True)), name="accounting_opening_item_target_direction"),
        ]

    def clean(self):
        if self.batch_id and self.issue_date and self.issue_date > self.batch.cutoff_date:
            raise ValidationError({"issue_date": "La fecha de emisión no puede ser posterior al corte."})
        if self.issue_date and self.due_date and self.due_date < self.issue_date:
            raise ValidationError({"due_date": "El vencimiento no puede ser anterior a la emisión."})
        if self.direction == self.Direction.RECEIVABLE and self.customer_invoice_id and self.supplier_bill_id:
            raise ValidationError("Una partida CxC solo se puede vincular con una factura de cliente.")
        if self.direction == self.Direction.PAYABLE and self.supplier_bill_id and self.customer_invoice_id:
            raise ValidationError("Una partida CxP solo se puede vincular con una factura de proveedor.")
        if self.direction == self.Direction.RECEIVABLE and self.supplier_bill_id:
            raise ValidationError("Una partida CxC solo se puede vincular con una factura de cliente.")
        if self.direction == self.Direction.PAYABLE and self.customer_invoice_id:
            raise ValidationError("Una partida CxP solo se puede vincular con una factura de proveedor.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = OpeningBalanceItem.objects.select_for_update().get(pk=self.pk)
            if previous.customer_invoice_id or previous.supplier_bill_id or previous.batch.state != OpeningBalanceBatch.State.DRAFT:
                raise ValidationError("Una partida de apertura vinculada o revisada es inmutable.")
            protected = ["batch_id", "direction", "counterparty_rfc", "source_system", "external_number", "issue_date", "due_date", "currency", "original_total", "paid_before_cutoff", "open_balance"]
            if any(getattr(previous, field) != getattr(self, field) for field in protected):
                raise ValidationError("Los datos de origen de una partida no se pueden cambiar.")
            target_added = not previous.customer_invoice_id and not previous.supplier_bill_id and bool(self.customer_invoice_id or self.supplier_bill_id)
            reservation_released = previous.is_reserved and not self.is_reserved and not self.customer_invoice_id and not self.supplier_bill_id
            if not target_added and not reservation_released:
                raise ValidationError("Solo se permite vincular una factura al publicar o liberar una referencia al rechazar el lote.")
        if self.batch_id and self.batch.state != OpeningBalanceBatch.State.DRAFT:
            raise ValidationError("Solo se pueden agregar partidas a un lote pendiente de revisión.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las partidas de apertura se conservan como historial contable.")
