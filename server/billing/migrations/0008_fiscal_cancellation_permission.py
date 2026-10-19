from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("billing", "0007_fiscaldocument_request_xml")]

    operations = [
        migrations.AlterModelOptions(
            name="fiscaldocument",
            options={
                "ordering": ["-created_at"],
                "permissions": [
                    ("prepare_fiscaldocument", "Puede preparar una solicitud fiscal para revisión"),
                    ("generate_fiscaldocument_xml", "Puede generar el XML firmado de un CFDI preparado"),
                    ("send_fiscaldocument", "Puede enviar un CFDI firmado al PAC configurado"),
                    ("query_fiscaldocument", "Puede consultar un CFDI enviado en FEL"),
                    ("cancel_fiscaldocument", "Puede solicitar la cancelación de un CFDI timbrado ante FEL"),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=(models.Q(("invoice__isnull", False), ("payment__isnull", True)) | models.Q(("invoice__isnull", True), ("payment__isnull", False))),
                        name="billing_fiscal_one_source",
                    ),
                ],
            },
        ),
    ]
