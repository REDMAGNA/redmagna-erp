import uuid

import django.db.models.deletion
import purchasing.models
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("purchasing", "0004_supplierbill_due_date"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="supplierbill",
            options={
                "ordering": ["-invoice_date", "invoice_number"],
                "permissions": [
                    ("register_supplierbill", "Puede registrar facturas de proveedor"),
                    ("attach_cfdi_supplierbill", "Puede adjuntar CFDI de proveedor"),
                ],
            },
        ),
        migrations.CreateModel(
            name="SupplierBillCFDI",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("cfdi_uuid", models.UUIDField(unique=True)),
                ("xml_file", models.FileField(max_length=300, upload_to=purchasing.models.supplier_bill_cfdi_upload_to)),
                ("sha256", models.CharField(max_length=64)),
                ("issuer_rfc", models.CharField(max_length=13)),
                ("receiver_rfc", models.CharField(max_length=13)),
                ("invoice_number", models.CharField(blank=True, max_length=80)),
                ("invoice_date", models.DateField()),
                ("subtotal", models.DecimalField(decimal_places=2, max_digits=16)),
                ("tax_total", models.DecimalField(decimal_places=2, max_digits=16)),
                ("total", models.DecimalField(decimal_places=2, max_digits=16)),
                ("xsd_validated_at", models.DateTimeField(db_index=True, default=timezone.now)),
                ("supplier_bill", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="cfdi_record", to="purchasing.supplierbill")),
                ("uploaded_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="uploaded_supplier_bills_cfdi", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-xsd_validated_at"]},
        ),
    ]
