import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0004_installed_stock_units"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReorderRule",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("minimum_quantity", models.DecimalField(decimal_places=3, max_digits=14)),
                ("target_quantity", models.DecimalField(decimal_places=3, max_digits=14)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("location", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="reorder_rules", to="inventory.stocklocation")),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="reorder_rules", to="inventory.product")),
            ],
            options={"ordering": ["product__sku", "location__code"]},
        ),
        migrations.AddConstraint(
            model_name="reorderrule",
            constraint=models.UniqueConstraint(fields=("product", "location"), name="inventory_reorder_product_location_uniq"),
        ),
        migrations.AddConstraint(
            model_name="reorderrule",
            constraint=models.CheckConstraint(condition=models.Q(("minimum_quantity__gte", 0)), name="inventory_reorder_min_nonnegative"),
        ),
        migrations.AddConstraint(
            model_name="reorderrule",
            constraint=models.CheckConstraint(condition=models.Q(("target_quantity__gt", models.F("minimum_quantity"))), name="inventory_reorder_target_gt_min"),
        ),
    ]
