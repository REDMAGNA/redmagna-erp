from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sales", "0023_public_lead_submissions")]

    operations = [
        migrations.AddField(model_name="opportunity", name="utm_source", field=models.CharField(blank=True, max_length=120)),
        migrations.AddField(model_name="opportunity", name="utm_medium", field=models.CharField(blank=True, max_length=120)),
        migrations.AddField(model_name="opportunity", name="utm_campaign", field=models.CharField(blank=True, max_length=120)),
    ]
