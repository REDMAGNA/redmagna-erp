import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0002_stock_transfers"),
        ("sales", "0012_workorder_customer_acceptance"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="tracking_policy",
            field=models.CharField(choices=[("quantity", "Por cantidad"), ("serial", "Por número de serie")], default="quantity", max_length=12),
        ),
        migrations.CreateModel(
            name="StockUnit",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("serial_number", models.CharField(max_length=120)),
                ("state", models.CharField(choices=[("in_stock", "En almacén"), ("assigned", "Entregado a una orden"), ("retired", "Retirado del inventario")], db_index=True, default="in_stock", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("location", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="serial_units", to="inventory.stocklocation")),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="serial_units", to="inventory.product")),
                ("work_order", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="serial_units", to="sales.workorder")),
            ],
            options={"ordering": ["product__sku", "serial_number"]},
        ),
        migrations.AddConstraint(
            model_name="stockunit",
            constraint=models.UniqueConstraint(fields=("product", "serial_number"), name="inventory_product_serial_uniq"),
        ),
        migrations.AddIndex(
            model_name="stockunit",
            index=models.Index(fields=["state", "location"], name="inventory_serial_state_loc_idx"),
        ),
        migrations.CreateModel(
            name="StockUnitEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("state_before", models.CharField(blank=True, max_length=16)),
                ("state_after", models.CharField(max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="redmagna_stock_unit_events", to=settings.AUTH_USER_MODEL)),
                ("from_location", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="serial_events_from", to="inventory.stocklocation")),
                ("movement", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="serial_events", to="inventory.stockmovement")),
                ("to_location", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="serial_events_to", to="inventory.stocklocation")),
                ("unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="events", to="inventory.stockunit")),
                ("work_order", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="serial_events", to="sales.workorder")),
            ],
            options={"ordering": ["-created_at", "id"]},
        ),
        migrations.AddConstraint(
            model_name="stockunitevent",
            constraint=models.UniqueConstraint(fields=("unit", "movement"), name="inventory_serial_event_unit_movement_uniq"),
        ),
    ]
