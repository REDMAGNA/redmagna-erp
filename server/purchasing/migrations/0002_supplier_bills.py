import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("purchasing", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SupplierBill",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("invoice_number", models.CharField(max_length=80)),
                ("invoice_date", models.DateField()),
                ("subtotal", models.DecimalField(decimal_places=2, max_digits=16)),
                ("tax_total", models.DecimalField(decimal_places=2, max_digits=16)),
                ("total", models.DecimalField(decimal_places=2, max_digits=16)),
                ("registered_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("purchase_order", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="supplier_bills", to="purchasing.purchaseorder")),
                ("registered_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="registered_supplier_bills", to=settings.AUTH_USER_MODEL)),
                ("supplier", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="bills", to="purchasing.supplier")),
            ],
            options={
                "ordering": ["-invoice_date", "invoice_number"],
                "permissions": [("register_supplierbill", "Puede registrar facturas de proveedor")],
            },
        ),
        migrations.CreateModel(
            name="SupplierBillLine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=14)),
                ("unit_cost", models.DecimalField(decimal_places=2, max_digits=14)),
                ("subtotal", models.DecimalField(decimal_places=2, max_digits=16)),
                ("tax_amount", models.DecimalField(decimal_places=2, max_digits=16)),
                ("bill", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="lines", to="purchasing.supplierbill")),
                ("purchase_order_line", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="supplier_bill_lines", to="purchasing.purchaseorderline")),
            ],
            options={"ordering": ["purchase_order_line__line_number"]},
        ),
        migrations.AddConstraint(
            model_name="supplierbill",
            constraint=models.UniqueConstraint(fields=("supplier", "invoice_number"), name="supplier_bill_invoice_uniq"),
        ),
        migrations.AddConstraint(
            model_name="supplierbillline",
            constraint=models.UniqueConstraint(fields=("bill", "purchase_order_line"), name="supplier_bill_po_line_uniq"),
        ),
        migrations.AddConstraint(
            model_name="supplierbillline",
            constraint=models.CheckConstraint(condition=models.Q(("quantity__gt", 0)), name="supplier_bill_qty_positive"),
        ),
        migrations.AddConstraint(
            model_name="supplierbillline",
            constraint=models.CheckConstraint(condition=models.Q(("unit_cost__gte", 0), ("subtotal__gte", 0), ("tax_amount__gte", 0)), name="supplier_bill_amounts_nonnegative"),
        ),
    ]
