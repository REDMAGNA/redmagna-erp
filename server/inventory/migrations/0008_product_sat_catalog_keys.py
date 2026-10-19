from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("inventory", "0007_serial_unit_reservations")]

    operations = [
        migrations.AddField(
            model_name="product",
            name="sat_product_service_key",
            field=models.CharField(blank=True, default="", max_length=8),
        ),
        migrations.AddField(
            model_name="product",
            name="sat_unit_key",
            field=models.CharField(blank=True, default="", max_length=3),
        ),
    ]
