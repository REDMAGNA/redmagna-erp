from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sales", "0014_customer_sites")]

    operations = [
        migrations.AddField(
            model_name="workorder",
            name="service_site_name",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="workorder",
            name="service_contact_email",
            field=models.EmailField(blank=True, max_length=254),
        ),
    ]
