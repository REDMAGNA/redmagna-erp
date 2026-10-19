from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("billing", "0003_invoice_sales_order_one_to_one")]

    operations = [
        migrations.AlterModelOptions(
            name="fiscaldocument",
            options={
                "ordering": ["-created_at"],
                "permissions": [("prepare_fiscaldocument", "Puede preparar una solicitud fiscal para revisión")],
                "constraints": [models.CheckConstraint(condition=(models.Q(("invoice__isnull", False), ("payment__isnull", True)) | models.Q(("invoice__isnull", True), ("payment__isnull", False))), name="billing_fiscal_one_source")],
            },
        ),
        migrations.AlterField(
            model_name="fiscalevent",
            name="action",
            field=models.CharField(choices=[("prepare", "Preparación"), ("submit", "Envío"), ("stamp", "Timbrado"), ("query", "Consulta"), ("cancel", "Cancelación"), ("response", "Respuesta"), ("error", "Error")], max_length=12),
        ),
    ]
