from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sales", "0025_public_lead_notifications")]

    operations = [
        migrations.AddField(
            model_name="publicleadnotification",
            name="manual_retry_count",
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]
