import uuid
from decimal import Decimal
from pathlib import PurePosixPath

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, models, transaction
from django.utils import timezone

from accounting.models import Account, Journal, JournalEntry


class ExpenseCategory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=24, unique=True)
    name = models.CharField(max_length=120)
    expense_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="expense_categories")
    receipt_required = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]
        permissions = [("archive_expensecategory", "Puede archivar categorías de gasto")]

    def clean(self):
        self.code = self.code.strip().upper()
        if self.expense_account_id and (not self.expense_account.is_active or self.expense_account.category != Account.Category.EXPENSE):
            raise ValidationError({"expense_account": "Selecciona una cuenta de gasto activa."})
        if self.pk and Expense.objects.filter(category_id=self.pk, report__status__in=["submitted", "approved", "journal_draft"]).exists():
            previous = ExpenseCategory.objects.get(pk=self.pk)
            if previous.expense_account_id != self.expense_account_id:
                raise ValidationError({"expense_account": "No cambies la cuenta de una categoría con reportes en proceso o contabilizados."})

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        self.clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las categorías de gasto no se eliminan; desactívalas para conservar el historial.")

    def __str__(self):
        return f"{self.code} · {self.name}"


class ExpenseReport(models.Model):
    class State(models.TextChoices):
        DRAFT = "draft", "Borrador"
        SUBMITTED = "submitted", "En revisión"
        APPROVED = "approved", "Aprobado"
        REJECTED = "rejected", "Rechazado"
        JOURNAL_DRAFT = "journal_draft", "Póliza borrador"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=24, unique=True, blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="expense_reports")
    state = models.CharField(max_length=16, choices=State.choices, default=State.DRAFT, db_index=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="reviewed_expense_reports")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=500, blank=True)
    journal_entry = models.OneToOneField(JournalEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="expense_report")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = [
            ("view_all_expensereports", "Puede consultar todos los reportes de gastos"),
            ("submit_expensereport", "Puede enviar reportes de gastos"),
            ("approve_expensereport", "Puede aprobar o rechazar reportes de gastos"),
            ("post_expensereport", "Puede preparar pólizas para reportes aprobados"),
        ]

    @property
    def total(self):
        return self.expenses.aggregate(total=models.Sum("amount"))["total"] or Decimal("0.00")

    @property
    def reimbursable_total(self):
        return self.expenses.filter(paid_by=Expense.PaidBy.EMPLOYEE).aggregate(total=models.Sum("amount"))["total"] or Decimal("0.00")

    @property
    def reimbursed_amount(self):
        return self.reimbursements.filter(state=ExpenseReimbursement.State.RECORDED).aggregate(total=models.Sum("amount"))["total"] or Decimal("0.00")

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self._state.adding and not self.number:
                year = timezone.localdate().year
                prefix = f"RM-GAS-{year}-"
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [prefix])
                last = ExpenseReport.objects.filter(number__startswith=prefix).order_by("-number").values_list("number", flat=True).first()
                sequence = int(last.rsplit("-", 1)[1]) + 1 if last else 1
                self.number = f"{prefix}{sequence:05d}"
            elif not self._state.adding:
                previous = ExpenseReport.objects.select_for_update().get(pk=self.pk)
                if previous.state == self.State.JOURNAL_DRAFT and any(
                    getattr(previous, field) != getattr(self, field)
                    for field in ("owner_id", "state", "submitted_at", "reviewed_by_id", "reviewed_at", "rejection_reason", "journal_entry_id")
                ):
                    raise ValidationError("Un reporte con póliza creada es inmutable.")
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los reportes de gastos no se eliminan; conserva su historial.")


def expense_receipt_upload_to(instance, filename):
    suffix = PurePosixPath(filename.replace("\\", "/").split("/")[-1]).suffix.lower()
    return f"expenses/{instance.expense_id}/{uuid.uuid4().hex}{suffix}"


def inspect_expense_receipt(filename, uploaded_file):
    suffix = PurePosixPath(filename.replace("\\", "/").split("/")[-1]).suffix.lower()
    allowed = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".pdf": "application/pdf"}
    if suffix not in allowed:
        raise ValidationError({"file": "Adjunta una foto JPG, PNG o WEBP, o un documento PDF."})
    if uploaded_file.size < 1 or uploaded_file.size > 10 * 1024 * 1024:
        raise ValidationError({"file": "El archivo debe pesar entre 1 byte y 10 MB."})
    stream = getattr(uploaded_file, "file", uploaded_file)
    position = stream.tell() if hasattr(stream, "tell") else 0
    header = stream.read(16)
    if hasattr(stream, "seek"):
        stream.seek(position)
    valid = (
        (suffix in {".jpg", ".jpeg"} and header.startswith(b"\xff\xd8\xff"))
        or (suffix == ".png" and header.startswith(b"\x89PNG\r\n\x1a\n"))
        or (suffix == ".webp" and header.startswith(b"RIFF") and header[8:12] == b"WEBP")
        or (suffix == ".pdf" and header.startswith(b"%PDF-"))
    )
    if not valid:
        raise ValidationError({"file": "El contenido no coincide con el formato permitido."})
    return allowed[suffix]


class Expense(models.Model):
    class PaidBy(models.TextChoices):
        EMPLOYEE = "employee", "Persona solicitante"
        COMPANY = "company", "Empresa"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.ForeignKey(ExpenseReport, null=True, blank=True, on_delete=models.PROTECT, related_name="expenses")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="expenses")
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name="expenses")
    expense_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="recorded_expenses")
    description = models.CharField(max_length=240)
    merchant = models.CharField(max_length=160, blank=True)
    expense_date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3, default="MXN")
    paid_by = models.CharField(max_length=12, choices=PaidBy.choices, default=PaidBy.EMPLOYEE)
    reference = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-expense_date", "-created_at"]
        permissions = [("view_all_expenses", "Puede consultar todos los gastos")]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="expenses_amount_positive"),
            models.CheckConstraint(condition=models.Q(currency="MXN"), name="expenses_currency_mxn"),
        ]

    def clean(self):
        if self.currency != "MXN":
            raise ValidationError({"currency": "La primera versión registra gastos únicamente en MXN."})
        if self.amount <= 0:
            raise ValidationError({"amount": "El total debe ser mayor que cero."})
        if self.category_id and not self.category.is_active and self._state.adding:
            raise ValidationError({"category": "Selecciona una categoría activa."})
        if self.category_id:
            self.expense_account_id = self.category.expense_account_id
        if self.report_id and self.report.state not in [ExpenseReport.State.DRAFT, ExpenseReport.State.REJECTED]:
            raise ValidationError({"report": "Solo se pueden modificar gastos de reportes en borrador o rechazados."})
        if not self._state.adding:
            previous = Expense.objects.get(pk=self.pk)
            if previous.report_id and previous.report_id != self.report_id:
                raise ValidationError("No se puede mover un gasto entre reportes; devuelve el reporte a borrador primero.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.report_id or self.receipts.exists():
            raise ValidationError("No se elimina un gasto enviado o con comprobantes; conserva su historial.")
        return super().delete(*args, **kwargs)


class ExpenseReceipt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    expense = models.ForeignKey(Expense, on_delete=models.PROTECT, related_name="receipts")
    file = models.FileField(upload_to=expense_receipt_upload_to, max_length=300)
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=40)
    file_size = models.PositiveBigIntegerField()
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="uploaded_expense_receipts")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at"]

    def clean(self):
        if self.file:
            self.content_type = inspect_expense_receipt(self.original_name or self.file.name, self.file)
            self.file_size = self.file.size
        if self.expense_id and self.expense.report_id and self.expense.report.state not in [ExpenseReport.State.DRAFT, ExpenseReport.State.REJECTED]:
            raise ValidationError({"file": "No se pueden agregar comprobantes mientras el reporte está en revisión o aprobado."})

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("El comprobante guardado es inmutable; carga una nueva versión antes de enviar.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los comprobantes de gastos no se eliminan.")


class ExpenseReportEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.ForeignKey(ExpenseReport, on_delete=models.PROTECT, related_name="events")
    action = models.CharField(max_length=32)
    state_before = models.CharField(max_length=16, blank=True)
    state_after = models.CharField(max_length=16, blank=True)
    detail = models.CharField(max_length=500, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="expense_report_events")
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["occurred_at", "id"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Los eventos de gastos son inmutables.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los eventos de gastos no se eliminan.")


class ExpensePostingConfiguration(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journal = models.ForeignKey(Journal, on_delete=models.PROTECT, related_name="expense_posting_configurations")
    reimbursement_journal = models.ForeignKey(Journal, null=True, blank=True, on_delete=models.PROTECT, related_name="expense_reimbursement_configurations")
    employee_payable_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="expense_employee_payables")
    company_funds_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="expense_company_funds")
    is_active = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [models.UniqueConstraint(fields=["is_active"], condition=models.Q(is_active=True), name="expenses_single_active_posting_config")]

    def clean(self):
        if self.journal_id and (not self.journal.is_active or self.journal.kind not in [Journal.Kind.PURCHASES, Journal.Kind.GENERAL]):
            raise ValidationError({"journal": "Selecciona un diario activo de compras o general."})
        if self.employee_payable_account_id and (not self.employee_payable_account.is_active or self.employee_payable_account.category != Account.Category.LIABILITY):
            raise ValidationError({"employee_payable_account": "Selecciona una cuenta de pasivo activa para reembolsos pendientes."})
        if self.company_funds_account_id and (not self.company_funds_account.is_active or self.company_funds_account.category != Account.Category.ASSET):
            raise ValidationError({"company_funds_account": "Selecciona una cuenta de activo activa para gastos pagados por la empresa."})
        if self.reimbursement_journal_id and (not self.reimbursement_journal.is_active or self.reimbursement_journal.kind not in [Journal.Kind.BANK, Journal.Kind.CASH]):
            raise ValidationError({"reimbursement_journal": "Selecciona un diario activo de banco o caja para registrar reembolsos."})
        if self.is_active and not self.reimbursement_journal_id:
            raise ValidationError({"reimbursement_journal": "Configura un diario de banco o caja para poder registrar reembolsos."})
        if self.reimbursement_journal_id and self.reimbursement_journal.kind == Journal.Kind.BANK and self.company_funds_account_id and not self.company_funds_account.allow_reconciliation:
            raise ValidationError({"company_funds_account": "La cuenta de fondos debe permitir conciliación si el diario de reembolsos es bancario."})

    def save(self, *args, **kwargs):
        self.full_clean()
        with transaction.atomic():
            if self.is_active:
                ExpensePostingConfiguration.objects.exclude(pk=self.pk).filter(is_active=True).update(is_active=False)
            return super().save(*args, **kwargs)


class ExpenseReimbursement(models.Model):
    class State(models.TextChoices):
        RECORDED = "recorded", "Registrado"
        REVERSED = "reversed", "Revertido"

    class Method(models.TextChoices):
        BANK_TRANSFER = "bank_transfer", "Transferencia"
        CASH = "cash", "Caja"
        CHECK = "check", "Cheque"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=24, unique=True, blank=True)
    report = models.ForeignKey(ExpenseReport, on_delete=models.PROTECT, related_name="reimbursements")
    idempotency_key = models.UUIDField(unique=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    payment_date = models.DateField()
    method = models.CharField(max_length=16, choices=Method.choices)
    reference = models.CharField(max_length=120, blank=True)
    journal_entry = models.OneToOneField(JournalEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="expense_reimbursement")
    state = models.CharField(max_length=10, choices=State.choices, default=State.RECORDED, db_index=True)
    registered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="registered_expense_reimbursements")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    reversed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="reversed_expense_reimbursements")
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversal_reason = models.CharField(max_length=500, blank=True)
    reversal_journal_entry = models.OneToOneField(JournalEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="expense_reimbursement_reversal")

    class Meta:
        ordering = ["created_at", "number"]
        permissions = [
            ("register_expensereimbursement", "Puede registrar reembolsos de gastos"),
            ("reverse_expensereimbursement", "Puede revertir reembolsos de gastos"),
        ]
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name="expense_reimbursement_amount_positive")]

    def clean(self):
        if self.amount <= 0:
            raise ValidationError({"amount": "El reembolso debe ser mayor que cero."})
        if self.method in [self.Method.BANK_TRANSFER, self.Method.CHECK] and not self.reference.strip():
            raise ValidationError({"reference": "La transferencia o cheque requiere referencia bancaria."})
        if self.reversal_journal_entry_id and self.journal_entry_id and self.reversal_journal_entry.reversal_of_id != self.journal_entry_id:
            raise ValidationError({"reversal_journal_entry": "La póliza inversa debe corresponder al reembolso."})

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self._state.adding:
                self.full_clean()
                if not self.number:
                    year = self.payment_date.year
                    prefix = f"RM-REI-{year}-"
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [prefix])
                    last = ExpenseReimbursement.objects.filter(number__startswith=prefix).order_by("-number").values_list("number", flat=True).first()
                    sequence = int(last.rsplit("-", 1)[1]) + 1 if last else 1
                    self.number = f"{prefix}{sequence:05d}"
                return super().save(*args, **kwargs)
            previous = ExpenseReimbursement.objects.select_for_update().get(pk=self.pk)
            immutable = ("number", "report_id", "idempotency_key", "amount", "payment_date", "method", "reference", "journal_entry_id", "registered_by_id", "created_at")
            if any(getattr(previous, field) != getattr(self, field) for field in immutable):
                raise ValidationError("Los datos de un reembolso registrado son inmutables.")
            if (previous.state, self.state) != (self.State.RECORDED, self.State.REVERSED):
                raise ValidationError("El reembolso solo puede cambiar al estado revertido mediante el flujo autorizado.")
            if not self.reversed_by_id or not self.reversed_at or len(self.reversal_reason.strip()) < 10 or not self.reversal_journal_entry_id:
                raise ValidationError("La reversa requiere responsable, fecha, motivo y póliza inversa.")
            self.full_clean()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los reembolsos no se eliminan; usa una reversa auditada.")
