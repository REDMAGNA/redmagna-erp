import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("sales", "0011_quote_customer_acceptance"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="workorder",
            options={
                "permissions": [
                    ("transition_workorder", "Puede cambiar el estado de órdenes de trabajo"),
                    ("schedule_workorder", "Puede programar y asignar órdenes de trabajo"),
                    ("log_workorder_hours", "Puede registrar horas de trabajo en órdenes"),
                    ("record_workorder_acceptance", "Puede registrar conformidad del cliente en órdenes de trabajo"),
                ],
            },
        ),
        migrations.CreateModel(
            name="WorkOrderCustomerAcceptance",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("customer_contact_name", models.CharField(max_length=160)),
                ("customer_contact_email", models.EmailField(blank=True, max_length=254)),
                ("notes", models.CharField(blank=True, max_length=500)),
                ("accepted_at", models.DateTimeField(db_index=True, default=timezone.now)),
                ("captured_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="recorded_work_order_acceptances", to=settings.AUTH_USER_MODEL)),
                ("work_order", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="customer_acceptance", to="sales.workorder")),
            ],
            options={"ordering": ["-accepted_at"]},
        ),
    ]
