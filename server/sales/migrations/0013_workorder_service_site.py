from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0012_workorder_customer_acceptance"),
    ]

    operations = [
        migrations.AddField(
            model_name="workorder",
            name="service_address",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="workorder",
            name="service_contact_name",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="workorder",
            name="service_contact_phone",
            field=models.CharField(blank=True, max_length=40),
        ),
    ]
