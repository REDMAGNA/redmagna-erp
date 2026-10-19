from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("inventory", "0011_inventory_product_location_barcodes")]

    operations = [
        migrations.AddField(
            model_name="stockmovement",
            name="idempotency_key",
            field=models.UUIDField(blank=True, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="stockmovement",
            name="request_fingerprint",
            field=models.CharField(blank=True, default="", editable=False, max_length=64),
        ),
    ]
