import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0012_stockmovement_idempotency"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="InventoryCount",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("reason", models.CharField(max_length=240)),
                ("state", models.CharField(choices=[("draft", "En captura"), ("submitted", "Pendiente de revisión"), ("applied", "Aplicado")], db_index=True, default="draft", max_length=12)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("applied_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_inventory_counts", to=settings.AUTH_USER_MODEL)),
                ("location", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="inventory_counts", to="inventory.stocklocation")),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="reviewed_inventory_counts", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"], "permissions": [("review_inventorycount", "Puede revisar y aplicar conteos físicos")]},
        ),
        migrations.CreateModel(
            name="InventoryCountLine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("expected_quantity", models.DecimalField(decimal_places=3, max_digits=14)),
                ("balance_updated_at", models.DateTimeField(blank=True, null=True)),
                ("counted_quantity", models.DecimalField(blank=True, decimal_places=3, max_digits=14, null=True)),
                ("counted_at", models.DateTimeField(blank=True, null=True)),
                ("idempotency_key", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("count", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="lines", to="inventory.inventorycount")),
                ("counted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="inventory_count_entries", to=settings.AUTH_USER_MODEL)),
                ("movement", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="inventory_count_lines", to="inventory.stockmovement")),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="inventory_count_lines", to="inventory.product")),
            ],
            options={"ordering": ["product__sku"]},
        ),
        migrations.AddConstraint(model_name="inventorycountline", constraint=models.UniqueConstraint(fields=("count", "product"), name="inventory_count_product_uniq")),
        migrations.AddConstraint(model_name="inventorycountline", constraint=models.CheckConstraint(condition=models.Q(("expected_quantity__gte", 0)), name="inventory_count_expected_nonnegative")),
        migrations.AddConstraint(model_name="inventorycountline", constraint=models.CheckConstraint(condition=models.Q(("counted_quantity__isnull", True), ("counted_quantity__gte", 0), _connector="OR"), name="inventory_count_actual_nonnegative")),
    ]
