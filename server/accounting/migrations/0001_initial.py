import decimal
import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
from django.utils import timezone


class Migration(migrations.Migration):
    initial = True

    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="Account",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("code", models.CharField(max_length=32, unique=True)),
                ("name", models.CharField(max_length=180)),
                ("category", models.CharField(choices=[("asset", "Activo"), ("liability", "Pasivo"), ("equity", "Capital"), ("income", "Ingreso"), ("expense", "Gasto")], max_length=12)),
                ("normal_balance", models.CharField(choices=[("debit", "Deudora"), ("credit", "Acreedora")], max_length=6)),
                ("allow_reconciliation", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("parent", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="children", to="accounting.account")),
            ],
            options={"ordering": ["code"]},
        ),
        migrations.CreateModel(
            name="Journal",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("code", models.CharField(max_length=12, unique=True)),
                ("name", models.CharField(max_length=100)),
                ("kind", models.CharField(choices=[("sales", "Ventas"), ("purchases", "Compras"), ("bank", "Banco"), ("cash", "Caja"), ("general", "General")], max_length=12)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={"ordering": ["code"]},
        ),
        migrations.CreateModel(
            name="JournalEntry",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("number", models.CharField(blank=True, max_length=40, unique=True)),
                ("entry_date", models.DateField(db_index=True, default=timezone.localdate)),
                ("memo", models.CharField(max_length=240)),
                ("origin_type", models.CharField(blank=True, max_length=40)),
                ("origin_id", models.UUIDField(blank=True, null=True)),
                ("state", models.CharField(choices=[("draft", "Borrador"), ("posted", "Contabilizada")], db_index=True, default="draft", max_length=8)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("posted_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_journal_entries", to=settings.AUTH_USER_MODEL)),
                ("journal", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="entries", to="accounting.journal")),
                ("posted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="posted_journal_entries", to=settings.AUTH_USER_MODEL)),
                ("reversal_of", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="reversal", to="accounting.journalentry")),
            ],
            options={
                "ordering": ["-entry_date", "-number"],
                "permissions": [
                    ("post_journalentry", "Puede contabilizar pólizas"),
                    ("reverse_journalentry", "Puede revertir pólizas contabilizadas"),
                ],
            },
        ),
        migrations.CreateModel(
            name="JournalLine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("line_number", models.PositiveSmallIntegerField()),
                ("description", models.CharField(blank=True, max_length=240)),
                ("debit", models.DecimalField(decimal_places=2, default=decimal.Decimal("0.00"), max_digits=16)),
                ("credit", models.DecimalField(decimal_places=2, default=decimal.Decimal("0.00"), max_digits=16)),
                ("account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="journal_lines", to="accounting.account")),
                ("entry", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="accounting.journalentry")),
            ],
            options={"ordering": ["line_number"]},
        ),
        migrations.AddConstraint(
            model_name="journalline",
            constraint=models.UniqueConstraint(fields=("entry", "line_number"), name="accounting_entry_line_number_uniq"),
        ),
        migrations.AddConstraint(
            model_name="journalline",
            constraint=models.CheckConstraint(
                condition=(Q(debit__gte=0) & Q(credit__gte=0) & (Q(debit=0) | Q(credit=0)) & ~(Q(debit=0) & Q(credit=0))),
                name="accounting_line_one_positive_side",
            ),
        ),
    ]
