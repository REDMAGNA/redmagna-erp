import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0004_prepare_fiscal_document"),
        ("inventory", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="invoiceline",
            name="catalog_product",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="invoice_lines", to="inventory.product"),
        ),
    ]
