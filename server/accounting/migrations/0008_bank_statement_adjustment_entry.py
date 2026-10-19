import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounting", "0007_customer_credit_note_posting")]

    operations = [
        migrations.AddField(
            model_name="bankstatementline",
            name="prepared_entry",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="bank_statement_adjustment_line",
                to="accounting.journalentry",
            ),
        ),
    ]
