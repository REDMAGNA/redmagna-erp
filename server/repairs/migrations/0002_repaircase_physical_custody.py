import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("repairs", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="repaircase",
            name="custody_status",
            field=models.CharField(
                choices=[
                    ("not_received", "No recibido físicamente"),
                    ("in_custody", "En custodia de Redmagna"),
                    ("returned", "Devuelto al cliente"),
                ],
                db_index=True,
                default="not_received",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="repaircase",
            name="intake_condition",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="repaircase",
            name="custody_received_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="repaircase",
            name="custody_received_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="received_repair_cases",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="repaircase",
            name="return_condition",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="repaircase",
            name="custody_returned_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="repaircase",
            name="custody_returned_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="returned_repair_cases",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
