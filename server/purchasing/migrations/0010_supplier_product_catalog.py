import uuid
from decimal import Decimal

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0007_serial_unit_reservations"),
        ("purchasing", "0009_purchase_sourcing"),
    ]

    operations = [
        migrations.CreateModel(
            name="SupplierProduct",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("supplier_reference", models.CharField(blank=True, max_length=120)),
                ("unit_cost", models.DecimalField(decimal_places=2, max_digits=14, validators=[django.core.validators.MinValueValidator(Decimal("0.00"))])),
                ("minimum_order_quantity", models.DecimalField(blank=True, decimal_places=3, max_digits=14, null=True, validators=[django.core.validators.MinValueValidator(Decimal("0.001"))])),
                ("lead_time_days", models.PositiveSmallIntegerField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(365)])),
                ("last_verified_on", models.DateField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="supplier_terms", to="inventory.product")),
                ("supplier", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="product_terms", to="purchasing.supplier")),
            ],
            options={"ordering": ["supplier__name", "product__sku"]},
        ),
        migrations.AddConstraint(model_name="supplierproduct", constraint=models.UniqueConstraint(fields=("supplier", "product"), name="purch_supplier_product_uniq")),
        migrations.AddConstraint(model_name="supplierproduct", constraint=models.CheckConstraint(condition=models.Q(("unit_cost__gte", 0)), name="purch_supplier_product_cost_valid")),
        migrations.AddConstraint(model_name="supplierproduct", constraint=models.CheckConstraint(condition=models.Q(("lead_time_days__isnull", True), ("lead_time_days__lte", 365), _connector="OR"), name="purch_supplier_product_lead_valid")),
        migrations.AddConstraint(model_name="supplierproduct", constraint=models.CheckConstraint(condition=models.Q(("minimum_order_quantity__isnull", True), ("minimum_order_quantity__gt", 0), _connector="OR"), name="purch_supplier_product_moq_valid")),
    ]
