import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sales", "0015_workorder_site_snapshot")]

    operations = [
        migrations.AddField(
            model_name="quote",
            name="customer_site",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="quotes", to="sales.customersite"),
        ),
        migrations.AddField(model_name="quote", name="service_site_name", field=models.CharField(blank=True, max_length=160)),
        migrations.AddField(model_name="quote", name="service_address", field=models.CharField(blank=True, max_length=500)),
        migrations.AddField(model_name="quote", name="service_contact_name", field=models.CharField(blank=True, max_length=160)),
        migrations.AddField(model_name="quote", name="service_contact_phone", field=models.CharField(blank=True, max_length=40)),
        migrations.AddField(model_name="quote", name="service_contact_email", field=models.EmailField(blank=True, max_length=254)),
    ]
