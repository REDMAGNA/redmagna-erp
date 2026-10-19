import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("sales", "0002_workorder_schedule_permission"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkLog",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("work_date", models.DateField(db_index=True, default=timezone.localdate)),
                ("hours", models.DecimalField(decimal_places=2, max_digits=5)),
                ("description", models.CharField(max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="redmagna_work_logs", to=settings.AUTH_USER_MODEL)),
                ("work_order", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="time_logs", to="sales.workorder")),
            ],
            options={"ordering": ["-work_date", "-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="worklog",
            constraint=models.CheckConstraint(condition=models.Q(hours__gt=0, hours__lte=24), name="sales_worklog_hours_valid"),
        ),
        migrations.AlterModelOptions(
            name="workorder",
            options={
                "permissions": [
                    ("transition_workorder", "Puede cambiar el estado de órdenes de trabajo"),
                    ("schedule_workorder", "Puede programar y asignar órdenes de trabajo"),
                    ("log_workorder_hours", "Puede registrar horas de trabajo en órdenes"),
                ]
            },
        ),
    ]
