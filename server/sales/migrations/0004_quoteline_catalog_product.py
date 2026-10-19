import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0001_initial"),
        ("sales", "0003_worklog"),
    ]

    operations = [
        migrations.AddField(
            model_name="quoteline",
            name="catalog_product",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="quote_lines", to="inventory.product"),
        ),
    ]
