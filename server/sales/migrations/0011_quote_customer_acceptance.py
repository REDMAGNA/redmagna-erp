import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("sales", "0010_workorder_evidence"),
    ]

    operations = [
        migrations.AlterField(
            model_name="salesorder",
            name="confirmed_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="salesorder",
            name="confirmation_source",
            field=models.CharField(choices=[("staff", "Personal de Redmagna"), ("customer", "Cliente")], default="staff", max_length=12),
        ),
        migrations.AlterField(
            model_name="auditevent",
            name="actor",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL),
        ),
        migrations.CreateModel(
            name="QuoteAcceptance",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("accepted_by_name", models.CharField(max_length=160)),
                ("accepted_by_email", models.EmailField(max_length=254)),
                ("accepted_at", models.DateTimeField(db_index=True, default=timezone.now)),
                ("quote", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="acceptance", to="sales.quote")),
            ],
            options={"ordering": ["-accepted_at"]},
        ),
    ]
