from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("inventory", "0008_product_sat_catalog_keys")]

    operations = [
        migrations.AddField(
            model_name="product",
            name="sat_tax_object",
            field=models.CharField(
                choices=[("01", "No objeto"), ("02", "Sí objeto")],
                default="02",
                max_length=2,
            ),
        ),
        migrations.AddField(
            model_name="product",
            name="sat_tax_factor",
            field=models.CharField(
                choices=[("Tasa", "Tasa"), ("Exento", "Exento")],
                default="Tasa",
                max_length=8,
            ),
        ),
    ]
