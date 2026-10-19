from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("inventory", "0010_product_sat_border_8_review")]

    operations = [
        migrations.AddField(
            model_name="product",
            name="barcode",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.AddField(
            model_name="stocklocation",
            name="barcode",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.AddConstraint(
            model_name="product",
            constraint=models.UniqueConstraint(condition=~models.Q(barcode=""), fields=("barcode",), name="inventory_product_barcode_uniq"),
        ),
        migrations.AddConstraint(
            model_name="stocklocation",
            constraint=models.UniqueConstraint(condition=~models.Q(barcode=""), fields=("barcode",), name="inventory_location_barcode_uniq"),
        ),
    ]
