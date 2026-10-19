import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0011_customer_payment_reversal"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="customerinvoice",
            name="state",
            field=models.CharField(choices=[("draft", "Borrador"), ("open", "Abierta"), ("partial", "Pago parcial"), ("paid", "Pagada"), ("credited", "Liquidada por nota de crédito"), ("cancelled", "Cancelada")], db_index=True, default="draft", max_length=12),
        ),
        migrations.CreateModel(
            name="CustomerCreditNote",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("number", models.CharField(blank=True, max_length=24, unique=True)),
                ("issue_date", models.DateField(default=django.utils.timezone.localdate)),
                ("reason", models.CharField(max_length=500)),
                ("state", models.CharField(choices=[("draft", "Borrador"), ("posted", "Aplicada")], db_index=True, default="draft", max_length=8)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("posted_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_customer_credit_notes", to=settings.AUTH_USER_MODEL)),
                ("invoice", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="credit_notes", to="billing.customerinvoice")),
                ("posted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="posted_customer_credit_notes", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-issue_date", "-number"], "permissions": [("post_customercreditnote", "Puede aplicar notas de crédito internas a facturas")]},
        ),
        migrations.CreateModel(
            name="CustomerCreditNoteLine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("line_number", models.PositiveSmallIntegerField()),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=12)),
                ("credit_note", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="billing.customercreditnote")),
                ("invoice_line", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="credit_note_lines", to="billing.invoiceline")),
            ],
            options={"ordering": ["line_number"]},
        ),
        migrations.AddConstraint(
            model_name="customercreditnoteline",
            constraint=models.UniqueConstraint(fields=("credit_note", "line_number"), name="billing_credit_note_line_number_uniq"),
        ),
        migrations.AddConstraint(
            model_name="customercreditnoteline",
            constraint=models.CheckConstraint(condition=models.Q(("quantity__gt", 0)), name="billing_credit_note_line_quantity_positive"),
        ),
    ]
