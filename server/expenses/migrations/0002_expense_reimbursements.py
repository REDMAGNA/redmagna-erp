import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0006_opening_balance_import"),
        ("expenses", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="expensepostingconfiguration",
            name="reimbursement_journal",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="expense_reimbursement_configurations", to="accounting.journal"),
        ),
        migrations.CreateModel(
            name="ExpenseReimbursement",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("number", models.CharField(blank=True, max_length=24, unique=True)),
                ("idempotency_key", models.UUIDField(unique=True)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14)),
                ("payment_date", models.DateField()),
                ("method", models.CharField(choices=[("bank_transfer", "Transferencia"), ("cash", "Caja"), ("check", "Cheque")], max_length=16)),
                ("reference", models.CharField(blank=True, max_length=120)),
                ("state", models.CharField(choices=[("recorded", "Registrado"), ("reversed", "Revertido")], db_index=True, default="recorded", max_length=10)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("reversed_at", models.DateTimeField(blank=True, null=True)),
                ("reversal_reason", models.CharField(blank=True, max_length=500)),
                ("journal_entry", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="expense_reimbursement", to="accounting.journalentry")),
                ("reversal_journal_entry", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="expense_reimbursement_reversal", to="accounting.journalentry")),
                ("registered_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="registered_expense_reimbursements", to=settings.AUTH_USER_MODEL)),
                ("reversed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="reversed_expense_reimbursements", to=settings.AUTH_USER_MODEL)),
                ("report", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="reimbursements", to="expenses.expensereport")),
            ],
            options={
                "ordering": ["created_at", "number"],
                "permissions": [("register_expensereimbursement", "Puede registrar reembolsos de gastos"), ("reverse_expensereimbursement", "Puede revertir reembolsos de gastos")],
            },
        ),
        migrations.AddConstraint(
            model_name="expensereimbursement",
            constraint=models.CheckConstraint(condition=models.Q(amount__gt=0), name="expense_reimbursement_amount_positive"),
        ),
    ]
