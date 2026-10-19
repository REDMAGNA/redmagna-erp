from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("purchasing", "0003_supplier_payments"),
    ]

    operations = [
        migrations.AddField(
            model_name="supplierbill",
            name="due_date",
            field=models.DateField(blank=True, null=True),
        ),
    ]
