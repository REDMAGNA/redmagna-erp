import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0003_supplier_postingconfiguration"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="BankStatement",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("period_start", models.DateField()),
                ("period_end", models.DateField()),
                ("opening_balance", models.DecimalField(decimal_places=2, max_digits=16)),
                ("closing_balance", models.DecimalField(decimal_places=2, max_digits=16)),
                ("state", models.CharField(choices=[("open", "Pendiente de conciliación"), ("reconciled", "Conciliado")], db_index=True, default="open", max_length=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("reconciled_at", models.DateTimeField(blank=True, null=True)),
                ("account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="bank_statements", to="accounting.account")),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_bank_statements", to=settings.AUTH_USER_MODEL)),
                ("reconciled_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="reconciled_bank_statements", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-period_end", "account__code"],
                "permissions": [("reconcile_bankstatement", "Puede cerrar una conciliación bancaria")],
            },
        ),
        migrations.CreateModel(
            name="BankStatementLine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("line_number", models.PositiveIntegerField()),
                ("transaction_date", models.DateField()),
                ("reference", models.CharField(blank=True, max_length=120)),
                ("description", models.CharField(blank=True, max_length=240)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=16)),
                ("matched_at", models.DateTimeField(blank=True, null=True)),
                ("journal_line", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="bank_statement_match", to="accounting.journalline")),
                ("matched_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="matched_bank_statement_lines", to=settings.AUTH_USER_MODEL)),
                ("statement", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="lines", to="accounting.bankstatement")),
            ],
            options={"ordering": ["transaction_date", "line_number"]},
        ),
        migrations.AddConstraint(
            model_name="bankstatement",
            constraint=models.CheckConstraint(condition=models.Q(period_end__gte=models.F("period_start")), name="accounting_statement_period_order"),
        ),
        migrations.AddConstraint(
            model_name="bankstatement",
            constraint=models.UniqueConstraint(fields=("account", "period_start", "period_end"), name="accounting_statement_period_uniq"),
        ),
        migrations.AddConstraint(
            model_name="bankstatementline",
            constraint=models.UniqueConstraint(fields=("statement", "line_number"), name="accounting_statement_line_number_uniq"),
        ),
        migrations.AddConstraint(
            model_name="bankstatementline",
            constraint=models.CheckConstraint(condition=~models.Q(amount=0), name="accounting_statement_line_nonzero"),
        ),
    ]
