from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounting", "0006_opening_balance_import")]

    operations = [
        migrations.AlterField(
            model_name="postingconfiguration",
            name="event_type",
            field=models.CharField(choices=[("customer_invoice", "Factura de cliente"), ("customer_credit_note", "Nota de crédito de cliente"), ("customer_payment", "Cobro de cliente"), ("supplier_bill", "Factura de proveedor"), ("supplier_payment", "Pago a proveedor")], max_length=24, unique=True),
        ),
    ]
