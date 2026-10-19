import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("purchasing", "0005_supplier_bill_cfdi"),
    ]

    operations = [
        migrations.AddField(
            model_name="purchaseorderline",
            name="expected_location",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="expected_purchase_order_lines", to="inventory.stocklocation"),
        ),
    ]
