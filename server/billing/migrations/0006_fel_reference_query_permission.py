from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("billing", "0005_invoiceline_catalog_product")]

    operations = [
        migrations.AlterModelOptions(
            name="fiscaldocument",
            options={
                "ordering": ["-created_at"],
                "permissions": [
                    ("prepare_fiscaldocument", "Puede preparar una solicitud fiscal para revisión"),
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
    ]
