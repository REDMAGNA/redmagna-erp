import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0005_reorder_rule"),
        ("sales", "0019_quote_optional_lines"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StockReservation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=14)),
                ("remaining_quantity", models.DecimalField(decimal_places=3, max_digits=14)),
                ("state", models.CharField(choices=[("active", "Activa"), ("fulfilled", "Surtida"), ("released", "Liberada")], db_index=True, default="active", max_length=12)),
                ("idempotency_key", models.UUIDField(unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="redmagna_stock_reservations", to=settings.AUTH_USER_MODEL)),
                ("location", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="stock_reservations", to="inventory.stocklocation")),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="stock_reservations", to="inventory.product")),
                ("work_order", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="stock_reservations", to="sales.workorder")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="stockreservation",
            constraint=models.CheckConstraint(condition=models.Q(("quantity__gt", 0)), name="inventory_reservation_quantity_positive"),
        ),
        migrations.AddConstraint(
            model_name="stockreservation",
            constraint=models.CheckConstraint(condition=models.Q(("remaining_quantity__gte", 0), ("remaining_quantity__lte", models.F("quantity"))), name="inventory_reservation_remaining_valid"),
        ),
        migrations.AddConstraint(
            model_name="stockreservation",
            constraint=models.UniqueConstraint(condition=models.Q(("state", "active")), fields=("work_order", "product", "location"), name="inventory_active_reservation_unique"),
        ),
        migrations.AddField(
            model_name="stockmovement",
            name="reservation",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="movements", to="inventory.stockreservation"),
        ),
        migrations.CreateModel(
            name="StockReservationEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("action", models.CharField(choices=[("reserved", "Reservada"), ("issued", "Entregada"), ("released", "Liberada")], max_length=12)),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=14)),
                ("remaining_after", models.DecimalField(decimal_places=3, max_digits=14)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="redmagna_stock_reservation_events", to=settings.AUTH_USER_MODEL)),
                ("movement", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="reservation_events", to="inventory.stockmovement")),
                ("reservation", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="events", to="inventory.stockreservation")),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
        migrations.AddConstraint(
            model_name="stockreservationevent",
            constraint=models.CheckConstraint(condition=models.Q(("quantity__gt", 0)), name="inventory_res_event_quantity_positive"),
        ),
    ]
