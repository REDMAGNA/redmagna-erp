from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0012_customer_credit_notes"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="customercreditnote",
            name="reversed_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="reversed_customer_credit_notes", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(model_name="customercreditnote", name="reversed_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="customercreditnote", name="reversal_reason", field=models.CharField(blank=True, max_length=500)),
        migrations.AlterField(
            model_name="customercreditnote",
            name="state",
            field=models.CharField(choices=[("draft", "Borrador"), ("posted", "Aplicada"), ("reversed", "Revertida")], db_index=True, default="draft", max_length=8),
        ),
        migrations.AlterModelOptions(
            name="customercreditnote",
            options={"ordering": ["-issue_date", "-number"], "permissions": [("post_customercreditnote", "Puede aplicar notas de crédito internas a facturas"), ("reverse_customercreditnote", "Puede revertir notas de crédito internas con motivo")]},
        ),
    ]
