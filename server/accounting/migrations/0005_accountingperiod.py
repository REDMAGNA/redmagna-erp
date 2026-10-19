import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0004_bank_statements"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AccountingPeriod",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("period_start", models.DateField(unique=True)),
                ("period_end", models.DateField()),
                ("state", models.CharField(choices=[("open", "Abierto"), ("closed", "Cerrado")], db_index=True, default="open", max_length=8)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("reopened_at", models.DateTimeField(blank=True, null=True)),
                ("closed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="closed_accounting_periods", to=settings.AUTH_USER_MODEL)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_accounting_periods", to=settings.AUTH_USER_MODEL)),
                ("reopened_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="reopened_accounting_periods", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-period_start"],
                "permissions": [("close_accountingperiod", "Puede cerrar periodos contables"), ("reopen_accountingperiod", "Puede reabrir periodos contables")],
            },
        ),
        migrations.CreateModel(
            name="AccountingPeriodEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("action", models.CharField(choices=[("closed", "Cerrado"), ("reopened", "Reabierto")], max_length=10)),
                ("reason", models.CharField(blank=True, max_length=500)),
                ("occurred_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="accounting_period_events", to=settings.AUTH_USER_MODEL)),
                ("period", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="events", to="accounting.accountingperiod")),
            ],
            options={"ordering": ["-occurred_at"]},
        ),
        migrations.AddConstraint(
            model_name="accountingperiod",
            constraint=models.CheckConstraint(condition=models.Q(period_end__gte=models.F("period_start")), name="accounting_period_date_order"),
        ),
    ]
