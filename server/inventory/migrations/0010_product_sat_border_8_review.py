from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("inventory", "0009_product_tax_defaults")]

    operations = [
        migrations.AddField(
            model_name="product",
            name="sat_border_8_eligible",
            field=models.BooleanField(
                default=False,
                help_text="Solo marca si Contabilidad verificó que esta ClaveProdServ tiene la marca SAT para el estímulo fronterizo al 8%.",
            ),
        ),
    ]
