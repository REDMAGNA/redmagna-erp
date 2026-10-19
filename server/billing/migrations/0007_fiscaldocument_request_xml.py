from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("billing", "0006_fel_reference_query_permission")]

    operations = [
        migrations.AddField(
            model_name="fiscaldocument",
            name="request_xml",
            field=models.TextField(blank=True),
        ),
        migrations.AlterModelOptions(
            name="fiscaldocument",
            options={
                "ordering": ["-created_at"],
                "permissions": [
                    ("prepare_fiscaldocument", "Puede preparar una solicitud fiscal para revisión"),
                    ("generate_fiscaldocument_xml", "Puede generar el XML firmado de un CFDI preparado"),
                    ("send_fiscaldocument", "Puede enviar un CFDI firmado al PAC configurado"),
                    ("query_fiscaldocument", "Puede consultar un CFDI enviado en FEL"),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=(models.Q(("invoice__isnull", False), ("payment__isnull", True)) | models.Q(("invoice__isnull", True), ("payment__isnull", False))),
                        name="billing_fiscal_one_source",
                    ),
                ],
            },
        ),
        migrations.AlterField(
            model_name="fiscalevent",
            name="action",
            field=models.CharField(
                choices=[
                    ("prepare", "Preparación"),
                    ("xml", "Generación de XML"),
                    ("submit", "Envío"),
                    ("stamp", "Timbrado"),
                    ("query", "Consulta"),
                    ("cancel", "Cancelación"),
                    ("response", "Respuesta"),
                    ("error", "Error"),
                ],
                max_length=12,
            ),
        ),
    ]
