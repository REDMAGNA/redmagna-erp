from decimal import Decimal

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0009_partial_sales_order_invoices"),
    ]

    operations = [
        migrations.AddField(
            model_name="invoiceline",
            name="discount_percent",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=5,
                validators=[django.core.validators.MinValueValidator(Decimal("0.00")), django.core.validators.MaxValueValidator(Decimal("100.00"))],
            ),
        ),
        migrations.AddConstraint(
            model_name="invoiceline",
            constraint=models.CheckConstraint(condition=models.Q(("discount_percent__gte", 0), ("discount_percent__lte", 100)), name="billing_invoice_discount_percent_range"),
        ),
    ]
