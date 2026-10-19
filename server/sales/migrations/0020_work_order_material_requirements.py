import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0006_stock_reservations"),
        ("sales", "0019_quote_optional_lines"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkOrderMaterialRequirement",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("required_quantity", models.DecimalField(decimal_places=3, max_digits=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="work_order_material_requirements", to="inventory.product")),
                ("source_quote_line", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="work_order_material_requirement", to="sales.quoteline")),
                ("work_order", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="material_requirements", to="sales.workorder")),
            ],
            options={"ordering": ["product__sku", "created_at"]},
        ),
        migrations.AddConstraint(
            model_name="workordermaterialrequirement",
            constraint=models.CheckConstraint(condition=models.Q(("required_quantity__gt", 0)), name="sales_wo_material_req_positive"),
        ),
    ]
