import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.core.validators


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("sales", "0029_quote_customer_contact_recipient"),
    ]

    operations = [
        migrations.CreateModel(
            name="QuoteCostSheet",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("target_margin_percent", models.DecimalField(blank=True, decimal_places=2, help_text="Margen bruto objetivo opcional. No modifica los precios de la cotización.", max_digits=5, null=True, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(99.99)])),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="created_quote_cost_sheets", to=settings.AUTH_USER_MODEL)),
                ("quote", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="cost_sheet", to="sales.quote")),
                ("updated_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="updated_quote_cost_sheets", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["quote__number"]},
        ),
        migrations.CreateModel(
            name="QuoteCostItem",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("category", models.CharField(choices=[("equipment", "Equipo"), ("material", "Material"), ("labor", "Mano de obra"), ("travel", "Traslado"), ("subcontract", "Subcontratación"), ("other", "Otro costo")], max_length=16)),
                ("description", models.CharField(max_length=240)),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=12, validators=[django.core.validators.MinValueValidator(0.001)])),
                ("unit_cost", models.DecimalField(decimal_places=2, max_digits=14, validators=[django.core.validators.MinValueValidator(0)])),
                ("is_optional", models.BooleanField(default=False)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                ("cost_sheet", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="sales.quotecostsheet")),
            ],
            options={"ordering": ["sort_order", "id"]},
        ),
        migrations.AddConstraint(
            model_name="quotecostsheet",
            constraint=models.CheckConstraint(condition=models.Q(target_margin_percent__isnull=True) | models.Q(target_margin_percent__gte=0, target_margin_percent__lt=100), name="sales_costsheet_margin_below_100"),
        ),
        migrations.AddConstraint(
            model_name="quotecostitem",
            constraint=models.CheckConstraint(condition=models.Q(("quantity__gt", 0)), name="sales_costitem_quantity_positive"),
        ),
        migrations.AddConstraint(
            model_name="quotecostitem",
            constraint=models.CheckConstraint(condition=models.Q(("unit_cost__gte", 0)), name="sales_costitem_cost_nonnegative"),
        ),
    ]
