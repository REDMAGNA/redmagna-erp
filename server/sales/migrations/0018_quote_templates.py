import decimal
import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("sales", "0017_workorder_checklist_templates"),
    ]

    operations = [
        migrations.CreateModel(
            name="QuoteTemplate",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=160, unique=True)),
                ("title", models.CharField(max_length=240)),
                ("validity_days", models.PositiveSmallIntegerField(default=30)),
                ("notes", models.TextField(blank=True)),
                ("tax_rate", models.DecimalField(decimal_places=2, default=decimal.Decimal("16.00"), max_digits=5)),
                ("lines", models.JSONField(default=list)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_quote_templates", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["name"]},
        ),
    ]
