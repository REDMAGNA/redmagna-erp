import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounting", "0002_postingconfiguration")]

    operations = [
        migrations.AlterField(
            model_name="postingconfiguration",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("customer_invoice", "Factura de cliente"),
                    ("customer_payment", "Cobro de cliente"),
                    ("supplier_bill", "Factura de proveedor"),
                    ("supplier_payment", "Pago a proveedor"),
                ],
                max_length=24,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="postingconfiguration",
            name="receivable_account",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="receivable_posting_configurations",
                to="accounting.account",
            ),
        ),
        migrations.AddField(
            model_name="postingconfiguration",
            name="payable_account",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="payable_posting_configurations",
                to="accounting.account",
            ),
        ),
        migrations.AddField(
            model_name="postingconfiguration",
            name="purchase_account",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="purchase_posting_configurations",
                to="accounting.account",
            ),
        ),
        migrations.AddField(
            model_name="postingconfiguration",
            name="supplier_tax_account",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="supplier_tax_posting_configurations",
                to="accounting.account",
            ),
        ),
    ]
