import decimal
import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("inventory", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Supplier",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=200, verbose_name="nombre comercial")),
                ("legal_name", models.CharField(blank=True, max_length=250, verbose_name="razón social")),
                ("rfc", models.CharField(blank=True, db_index=True, max_length=13)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("phone", models.CharField(blank=True, max_length=40)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="PurchaseOrder",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("number", models.CharField(blank=True, max_length=24, unique=True)),
                ("order_date", models.DateField(default=django.utils.timezone.localdate)),
                ("expected_date", models.DateField(blank=True, null=True)),
                ("status", models.CharField(choices=[("draft", "Borrador"), ("ordered", "Solicitada"), ("partial", "Recibida parcialmente"), ("received", "Recibida"), ("cancelled", "Cancelada")], db_index=True, default="draft", max_length=12)),
                ("notes", models.TextField(blank=True)),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("confirmed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="confirmed_purchase_orders", to=settings.AUTH_USER_MODEL)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_purchase_orders", to=settings.AUTH_USER_MODEL)),
                ("supplier", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_orders", to="purchasing.supplier")),
            ],
            options={
                "ordering": ["-created_at"],
                "permissions": [("confirm_purchaseorder", "Puede confirmar órdenes de compra"), ("receive_purchaseorder", "Puede registrar recepciones de compra"), ("cancel_purchaseorder", "Puede cancelar órdenes de compra")],
            },
        ),
        migrations.CreateModel(
            name="PurchaseOrderLine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("line_number", models.PositiveSmallIntegerField()),
                ("description", models.CharField(blank=True, max_length=300)),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=14)),
                ("received_quantity", models.DecimalField(decimal_places=3, default=decimal.Decimal("0.000"), max_digits=14)),
                ("unit_cost", models.DecimalField(decimal_places=2, max_digits=14)),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_order_lines", to="inventory.product")),
                ("purchase_order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="purchasing.purchaseorder")),
            ],
            options={"ordering": ["line_number"]},
        ),
        migrations.CreateModel(
            name="PurchaseReceipt",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("idempotency_key", models.UUIDField(unique=True)),
                ("receipt_date", models.DateTimeField(default=django.utils.timezone.now)),
                ("note", models.CharField(blank=True, max_length=240)),
                ("request_payload", models.JSONField(default=dict)),
                ("purchase_order", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="receipts", to="purchasing.purchaseorder")),
                ("received_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_receipts", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-receipt_date"]},
        ),
        migrations.CreateModel(
            name="PurchaseOrderEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("action", models.CharField(max_length=24)),
                ("state_before", models.CharField(blank=True, max_length=12)),
                ("state_after", models.CharField(blank=True, max_length=12)),
                ("occurred_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_order_events", to=settings.AUTH_USER_MODEL)),
                ("purchase_order", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="events", to="purchasing.purchaseorder")),
            ],
            options={"ordering": ["occurred_at"]},
        ),
        migrations.CreateModel(
            name="PurchaseReceiptLine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=14)),
                ("purchase_order_line", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="receipt_lines", to="purchasing.purchaseorderline")),
                ("receipt", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="lines", to="purchasing.purchasereceipt")),
                ("stock_movement", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_receipt_line", to="inventory.stockmovement")),
            ],
            options={"ordering": ["purchase_order_line__line_number"]},
        ),
        migrations.AddConstraint(
            model_name="purchaseorderline",
            constraint=models.UniqueConstraint(fields=("purchase_order", "line_number"), name="purch_order_line_no_uniq"),
        ),
        migrations.AddConstraint(
            model_name="purchaseorderline",
            constraint=models.CheckConstraint(condition=models.Q(("quantity__gt", 0)), name="po_line_qty_positive"),
        ),
        migrations.AddConstraint(
            model_name="purchaseorderline",
            constraint=models.CheckConstraint(condition=models.Q(("unit_cost__gte", 0)), name="po_line_cost_nonnegative"),
        ),
        migrations.AddConstraint(
            model_name="purchaseorderline",
            constraint=models.CheckConstraint(condition=models.Q(("received_quantity__gte", 0), ("received_quantity__lte", models.F("quantity"))), name="po_recv_lte_ordered"),
        ),
    ]
