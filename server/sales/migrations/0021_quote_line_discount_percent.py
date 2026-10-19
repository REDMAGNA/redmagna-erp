from decimal import Decimal

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0020_work_order_material_requirements"),
    ]

    operations = [
        migrations.AddField(
            model_name="quoteline",
            name="discount_percent",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=5,
                validators=[django.core.validators.MinValueValidator(Decimal("0.00")), django.core.validators.MaxValueValidator(Decimal("100.00"))],
            ),
        ),
        migrations.AddConstraint(
            model_name="quoteline",
            constraint=models.CheckConstraint(condition=models.Q(("discount_percent__gte", 0), ("discount_percent__lte", 100)), name="sales_quote_discount_percent_range"),
        ),
    ]
