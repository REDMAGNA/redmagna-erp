from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounting", "0005_accountingperiod")]

    operations = [
        migrations.AddConstraint(
            model_name="journalentry",
            constraint=models.UniqueConstraint(
                fields=("origin_type",),
                condition=models.Q(origin_type="opening_balance_import"),
                name="accounting_single_opening_import",
            ),
        ),
    ]
