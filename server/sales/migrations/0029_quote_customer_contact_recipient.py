from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("sales", "0028_customer_contacts")]

    operations = [
        migrations.AddField(
            model_name="quote",
            name="customer_contact",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="quotes",
                to="sales.customercontact",
            ),
        ),
        migrations.AddField(
            model_name="quote",
            name="recipient_name_snapshot",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="quote",
            name="recipient_email_snapshot",
            field=models.EmailField(blank=True, max_length=254),
        ),
    ]
