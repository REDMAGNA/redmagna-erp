import decimal
import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("purchasing", "0002_supplier_bills"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SupplierPayment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("number", models.CharField(blank=True, max_length=24, unique=True)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=16)),
                ("currency", models.CharField(default="MXN", max_length=3)),
                ("method", models.CharField(choices=[("transfer", "Transferencia"), ("cash", "Efectivo"), ("card", "Tarjeta"), ("check", "Cheque"), ("other", "Otro")], max_length=12)),
                ("paid_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("reference", models.CharField(blank=True, max_length=120)),
                ("memo", models.CharField(blank=True, max_length=240)),
                ("state", models.CharField(choices=[("draft", "Borrador"), ("posted", "Aplicado")], db_index=True, default="draft", max_length=8)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("posted_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_supplier_payments", to=settings.AUTH_USER_MODEL)),
                ("posted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="posted_supplier_payments", to=settings.AUTH_USER_MODEL)),
                ("supplier", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payments", to="purchasing.supplier")),
            ],
            options={
                "ordering": ["-paid_at", "-number"],
                "permissions": [("post_supplierpayment", "Puede aplicar pagos a facturas de proveedor")],
            },
        ),
        migrations.CreateModel(
            name="SupplierPaymentApplication",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=16)),
                ("bill", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payment_applications", to="purchasing.supplierbill")),
                ("payment", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="applications", to="purchasing.supplierpayment")),
            ],
        ),
        migrations.AddConstraint(
            model_name="supplierpayment",
            constraint=models.CheckConstraint(condition=models.Q(("currency", "MXN")), name="purch_supplier_payment_mxn"),
        ),
        migrations.AddConstraint(
            model_name="supplierpaymentapplication",
            constraint=models.UniqueConstraint(fields=("payment", "bill"), name="supplier_payment_bill_uniq"),
        ),
        migrations.AddConstraint(
            model_name="supplierpaymentapplication",
            constraint=models.CheckConstraint(condition=models.Q(("amount__gt", 0)), name="supplier_payment_amount_positive"),
        ),
    ]
