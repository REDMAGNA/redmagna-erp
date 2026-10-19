import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sales", "0004_quoteline_catalog_product")]

    operations = [
        migrations.AddField(
            model_name="quote",
            name="revision_of",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="revisions", to="sales.quote"),
        ),
        migrations.AddField(
            model_name="quote",
            name="revision_number",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name="quote",
            name="status",
            field=models.CharField(choices=[("draft", "Borrador"), ("sent", "Enviada"), ("approved", "Aprobada"), ("cancelled", "Cancelada"), ("expired", "Vencida"), ("superseded", "Reemplazada")], db_index=True, default="draft", max_length=12),
        ),
        migrations.AlterModelOptions(
            name="quote",
            options={
                "ordering": ["-created_at"],
                "permissions": [
                    ("send_quote", "Puede enviar cotizaciones"),
                    ("approve_quote", "Puede aprobar cotizaciones"),
                    ("cancel_quote", "Puede cancelar cotizaciones"),
                    ("revise_quote", "Puede crear una revisión de cotización enviada"),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="quote",
            constraint=models.UniqueConstraint(condition=models.Q(("revision_of__isnull", False)), fields=("revision_of", "revision_number"), name="sales_quote_revision_number_uniq"),
        ),
    ]
