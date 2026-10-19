import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0006_opening_balance_import"),
        ("purchasing", "0007_supplier_lead_time"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="supplierpayment",
            name="state",
            field=models.CharField(
                choices=[("draft", "Borrador"), ("posted", "Aplicado"), ("reversed", "Revertido")],
                db_index=True,
                default="draft",
                max_length=8,
            ),
        ),
        migrations.AddField(
            model_name="supplierpayment",
            name="reversal_reason",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="supplierpayment",
            name="reversed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="supplierpayment",
            name="reversed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="reversed_supplier_payments",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="supplierpayment",
            name="reversal_entry",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="supplier_payment_reversals",
                to="accounting.journalentry",
            ),
        ),
        migrations.AlterModelOptions(
            name="supplierpayment",
            options={
                "ordering": ["-paid_at", "-number"],
                "permissions": [
                    ("post_supplierpayment", "Puede aplicar pagos a facturas de proveedor"),
                    ("reverse_supplierpayment", "Puede revertir pagos aplicados a proveedores"),
                ],
            },
        ),
    ]
