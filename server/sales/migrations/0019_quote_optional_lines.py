from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0018_quote_templates"),
    ]

    operations = [
        migrations.AddField(
            model_name="quoteline",
            name="is_optional",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="quoteline",
            name="approved_quantity",
            field=models.DecimalField(blank=True, decimal_places=3, max_digits=12, null=True),
        ),
    ]
