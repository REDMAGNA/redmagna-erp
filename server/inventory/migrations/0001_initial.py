import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def create_main_location(apps, schema_editor):
    StockLocation = apps.get_model("inventory", "StockLocation")
    StockLocation.objects.get_or_create(code="MAIN", defaults={"name": "Almacén principal", "is_active": True})


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("sales", "0003_worklog"),
    ]

    operations = [
        migrations.CreateModel(
            name="Product",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("sku", models.CharField(max_length=64, unique=True)),
                ("name", models.CharField(max_length=200)),
                ("description", models.CharField(blank=True, max_length=500)),
                ("kind", models.CharField(choices=[("stockable", "Producto con existencias"), ("service", "Servicio")], default="stockable", max_length=12)),
                ("unit", models.CharField(default="pza", max_length=16)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["sku"]},
        ),
        migrations.CreateModel(
            name="StockLocation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("code", models.CharField(max_length=24, unique=True)),
                ("name", models.CharField(max_length=120)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={"ordering": ["code"]},
        ),
        migrations.CreateModel(
            name="StockBalance",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("quantity", models.DecimalField(decimal_places=3, default=0, max_digits=14)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("location", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="stock_balances", to="inventory.stocklocation")),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="stock_balances", to="inventory.product")),
            ],
            options={"ordering": ["product__sku", "location__code"]},
        ),
        migrations.CreateModel(
            name="StockMovement",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("kind", models.CharField(choices=[("receipt", "Entrada"), ("issue", "Salida a trabajo"), ("return", "Devolución de trabajo"), ("adjustment_in", "Ajuste positivo"), ("adjustment_out", "Ajuste negativo")], db_index=True, max_length=16)),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=14)),
                ("reference", models.CharField(blank=True, max_length=120)),
                ("note", models.CharField(blank=True, max_length=240)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="redmagna_stock_movements", to=settings.AUTH_USER_MODEL)),
                ("location", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="stock_movements", to="inventory.stocklocation")),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="stock_movements", to="inventory.product")),
                ("work_order", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="stock_movements", to="sales.workorder")),
            ],
            options={
                "ordering": ["-created_at"],
                "permissions": [
                    ("receive_stock", "Puede registrar entradas de inventario"),
                    ("issue_stock", "Puede entregar materiales a órdenes de trabajo"),
                    ("adjust_stock", "Puede realizar ajustes de inventario"),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="stockbalance",
            constraint=models.UniqueConstraint(fields=("product", "location"), name="inventory_balance_product_location_uniq"),
        ),
        migrations.AddConstraint(
            model_name="stockbalance",
            constraint=models.CheckConstraint(condition=models.Q(quantity__gte=0), name="inventory_balance_nonnegative"),
        ),
        migrations.AddConstraint(
            model_name="stockmovement",
            constraint=models.CheckConstraint(condition=models.Q(quantity__gt=0), name="inventory_movement_positive"),
        ),
        migrations.RunPython(create_main_location, migrations.RunPython.noop),
    ]
