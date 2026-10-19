import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("inventory", "0010_product_sat_border_8_review"),
        ("sales", "0029_quote_customer_contact_recipient"),
        ("support", "0010_rename_inbound_email_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="RepairCase",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("number", models.CharField(blank=True, max_length=24, unique=True)),
                ("status", models.CharField(choices=[("received", "Recibido"), ("diagnosis", "En diagnóstico"), ("waiting_authorization", "Espera autorización"), ("authorized", "Autorizado"), ("in_repair", "En reparación"), ("ready", "Listo"), ("closed", "Cerrado"), ("unrepairable", "No reparable"), ("cancelled", "Cancelado")], db_index=True, default="received", max_length=24)),
                ("warranty_review", models.CharField(choices=[("pending", "Pendiente de revisión"), ("covered", "Cobertura confirmada"), ("not_covered", "Sin cobertura confirmada"), ("unknown", "No determinada")], default="pending", max_length=16)),
                ("reported_issue", models.TextField()),
                ("diagnosis", models.TextField(blank=True)),
                ("proposed_work", models.TextField(blank=True)),
                ("authorization_record", models.TextField(blank=True)),
                ("authorized_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("authorized_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="authorized_repair_cases", to=settings.AUTH_USER_MODEL)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_repair_cases", to=settings.AUTH_USER_MODEL)),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="repair_cases", to="sales.customer")),
                ("serial_unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="repair_cases", to="inventory.stockunit")),
                ("ticket", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="repair_case", to="support.supportticket")),
            ],
            options={
                "ordering": ["-created_at", "number"],
                "permissions": [("transition_repaircase", "Puede cambiar el estado de expedientes de reparación")],
            },
        ),
        migrations.CreateModel(
            name="RepairCaseEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("action", models.CharField(max_length=32)),
                ("from_status", models.CharField(blank=True, max_length=24)),
                ("to_status", models.CharField(blank=True, max_length=24)),
                ("detail", models.CharField(blank=True, max_length=1000)),
                ("occurred_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="repair_case_events", to=settings.AUTH_USER_MODEL)),
                ("repair_case", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="events", to="repairs.repaircase")),
            ],
            options={"ordering": ["occurred_at", "id"]},
        ),
    ]
