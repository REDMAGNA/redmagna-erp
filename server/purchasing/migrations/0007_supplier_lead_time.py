from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("purchasing", "0006_purchaseorderline_expected_location"),
    ]

    operations = [
        migrations.AddField(
            model_name="supplier",
            name="lead_time_days",
            field=models.PositiveSmallIntegerField(blank=True, null=True, validators=[MinValueValidator(0), MaxValueValidator(365)]),
        ),
        migrations.AddConstraint(
            model_name="supplier",
            constraint=models.CheckConstraint(condition=models.Q(("lead_time_days__isnull", True), ("lead_time_days__lte", 365), _connector="OR"), name="purch_supplier_lead_days_valid"),
        ),
    ]
