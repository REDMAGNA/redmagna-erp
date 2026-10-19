import decimal
import uuid

from django.conf import settings
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion
import django.utils.timezone


def create_default_discount_policy(apps, schema_editor):
    QuoteDiscountPolicy = apps.get_model("sales", "QuoteDiscountPolicy")
    QuoteDiscountPolicy.objects.get_or_create(
        id=1,
        defaults={"enabled": False, "maximum_discount_percent": decimal.Decimal("0.00")},
    )


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("sales", "0030_quote_cost_sheets"),
    ]

    operations = [
        migrations.CreateModel(
            name="QuoteDiscountApproval",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("quote_snapshot_hash", models.CharField(max_length=64)),
                ("threshold_percent", models.DecimalField(decimal_places=2, max_digits=5)),
                ("maximum_discount_percent", models.DecimalField(decimal_places=2, max_digits=5)),
                ("approved_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("approved_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="approved_quote_discount_exceptions", to=settings.AUTH_USER_MODEL)),
                ("quote", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="discount_approvals", to="sales.quote")),
            ],
            options={"ordering": ["-approved_at", "-id"]},
        ),
        migrations.CreateModel(
            name="QuoteDiscountPolicy",
            fields=[
                ("id", models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ("enabled", models.BooleanField(default=False)),
                ("maximum_discount_percent", models.DecimalField(decimal_places=2, default=decimal.Decimal("0.00"), max_digits=5, validators=[django.core.validators.MinValueValidator(decimal.Decimal("0.00")), django.core.validators.MaxValueValidator(decimal.Decimal("100.00"))])),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="updated_quote_discount_policies", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name="quotediscountpolicy",
            constraint=models.CheckConstraint(condition=models.Q(("id", 1)), name="sales_qdisc_singleton"),
        ),
        migrations.AddConstraint(
            model_name="quotediscountpolicy",
            constraint=models.CheckConstraint(condition=models.Q(("maximum_discount_percent__gte", 0), ("maximum_discount_percent__lte", 100)), name="sales_qdisc_range"),
        ),
        migrations.AddIndex(
            model_name="quotediscountapproval",
            index=models.Index(fields=["quote", "quote_snapshot_hash"], name="sales_qdisc_approv_idx"),
        ),
        migrations.RunPython(create_default_discount_policy, migrations.RunPython.noop),
    ]
