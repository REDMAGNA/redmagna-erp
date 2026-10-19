import uuid
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL), ("accounting", "0006_opening_balance_import")]
    operations = [
        migrations.CreateModel(name="ExpenseCategory", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ("code", models.CharField(max_length=24, unique=True)), ("name", models.CharField(max_length=120)),
            ("receipt_required", models.BooleanField(default=True)), ("is_active", models.BooleanField(default=True)),
            ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
            ("expense_account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="expense_categories", to="accounting.account")),
        ], options={"ordering": ["code"], "permissions": [("archive_expensecategory", "Puede archivar categorías de gasto")]}),
        migrations.CreateModel(name="ExpensePostingConfiguration", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ("is_active", models.BooleanField(default=False)), ("updated_at", models.DateTimeField(auto_now=True)),
            ("company_funds_account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="expense_company_funds", to="accounting.account")),
            ("employee_payable_account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="expense_employee_payables", to="accounting.account")),
            ("journal", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="expense_posting_configurations", to="accounting.journal")),
        ], options={"ordering": ["-updated_at"]}),
        migrations.CreateModel(name="ExpenseReport", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ("number", models.CharField(blank=True, max_length=24, unique=True)),
            ("state", models.CharField(choices=[("draft", "Borrador"), ("submitted", "En revisión"), ("approved", "Aprobado"), ("rejected", "Rechazado"), ("journal_draft", "Póliza borrador")], db_index=True, default="draft", max_length=16)),
            ("submitted_at", models.DateTimeField(blank=True, null=True)), ("reviewed_at", models.DateTimeField(blank=True, null=True)),
            ("rejection_reason", models.CharField(blank=True, max_length=500)), ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)), ("updated_at", models.DateTimeField(auto_now=True)),
            ("journal_entry", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="expense_report", to="accounting.journalentry")),
            ("owner", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="expense_reports", to=settings.AUTH_USER_MODEL)),
            ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="reviewed_expense_reports", to=settings.AUTH_USER_MODEL)),
        ], options={"ordering": ["-created_at"], "permissions": [("view_all_expensereports", "Puede consultar todos los reportes de gastos"), ("submit_expensereport", "Puede enviar reportes de gastos"), ("approve_expensereport", "Puede aprobar o rechazar reportes de gastos"), ("post_expensereport", "Puede preparar pólizas para reportes aprobados")]}),
        migrations.CreateModel(name="Expense", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)), ("description", models.CharField(max_length=240)), ("merchant", models.CharField(blank=True, max_length=160)),
            ("expense_date", models.DateField()), ("amount", models.DecimalField(decimal_places=2, max_digits=14)), ("currency", models.CharField(default="MXN", max_length=3)),
            ("paid_by", models.CharField(choices=[("employee", "Persona solicitante"), ("company", "Empresa")], default="employee", max_length=12)), ("reference", models.CharField(blank=True, max_length=120)),
            ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)), ("updated_at", models.DateTimeField(auto_now=True)),
            ("category", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="expenses", to="expenses.expensecategory")),
            ("expense_account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="recorded_expenses", to="accounting.account")),
            ("owner", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="expenses", to=settings.AUTH_USER_MODEL)),
            ("report", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="expenses", to="expenses.expensereport")),
        ], options={"ordering": ["-expense_date", "-created_at"], "permissions": [("view_all_expenses", "Puede consultar todos los gastos")]}),
        migrations.AddConstraint(model_name="expense", constraint=models.CheckConstraint(condition=models.Q(amount__gt=0), name="expenses_amount_positive")),
        migrations.AddConstraint(model_name="expense", constraint=models.CheckConstraint(condition=models.Q(currency="MXN"), name="expenses_currency_mxn")),
        migrations.CreateModel(name="ExpenseReceipt", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)), ("file", models.FileField(max_length=300, upload_to="expenses.models.expense_receipt_upload_to")),
            ("original_name", models.CharField(max_length=255)), ("content_type", models.CharField(max_length=40)), ("file_size", models.PositiveBigIntegerField()), ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
            ("expense", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="receipts", to="expenses.expense")),
            ("uploaded_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="uploaded_expense_receipts", to=settings.AUTH_USER_MODEL)),
        ], options={"ordering": ["created_at"]}),
        migrations.CreateModel(name="ExpenseReportEvent", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)), ("action", models.CharField(max_length=32)), ("state_before", models.CharField(blank=True, max_length=16)),
            ("state_after", models.CharField(blank=True, max_length=16)), ("detail", models.CharField(blank=True, max_length=500)), ("occurred_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
            ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="expense_report_events", to=settings.AUTH_USER_MODEL)),
            ("report", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="events", to="expenses.expensereport")),
        ], options={"ordering": ["occurred_at", "id"]}),
        migrations.AddConstraint(model_name="expensepostingconfiguration", constraint=models.UniqueConstraint(condition=models.Q(is_active=True), fields=("is_active",), name="expenses_single_active_posting_config")),
    ]
