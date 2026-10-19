from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("billing", "0016_customer_invoice_reminder")]

    operations = [
        migrations.AlterModelOptions(
            name="fiscaldocument",
            options={
                "ordering": ["-created_at"],
                "permissions": [
                    ("prepare_fiscaldocument", "Puede preparar una solicitud fiscal para revisión"),
                    ("generate_fiscaldocument_xml", "Puede generar el XML firmado de un CFDI preparado"),
                    ("send_fiscaldocument", "Puede enviar un CFDI firmado al PAC configurado"),
                    ("send_customer_copy_fiscaldocument", "Puede enviar una copia del CFDI timbrado al cliente"),
                    ("query_fiscaldocument", "Puede consultar un CFDI enviado en FEL"),
                    ("cancel_fiscaldocument", "Puede solicitar la cancelación de un CFDI timbrado ante FEL"),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=(
                            models.Q(("credit_note__isnull", True), ("invoice__isnull", False), ("payment__isnull", True))
                            | models.Q(("credit_note__isnull", True), ("invoice__isnull", True), ("payment__isnull", False))
                            | models.Q(("credit_note__isnull", False), ("invoice__isnull", True), ("payment__isnull", True))
                        ),
                        name="billing_fiscal_one_source",
                    ),
                ],
            },
        ),
    ]
