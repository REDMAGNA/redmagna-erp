import decimal
import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):
    initial = True

    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="Customer",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=200, verbose_name="nombre comercial")),
                ("legal_name", models.CharField(blank=True, max_length=250, verbose_name="razón social")),
                ("rfc", models.CharField(blank=True, db_index=True, max_length=13)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("phone", models.CharField(blank=True, max_length=40)),
                ("fiscal_regime", models.CharField(blank=True, max_length=3)),
                ("fiscal_postal_code", models.CharField(blank=True, max_length=5)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="Quote",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("number", models.CharField(blank=True, max_length=24, unique=True)),
                ("title", models.CharField(max_length=240, verbose_name="proyecto o servicio")),
                ("status", models.CharField(choices=[("draft", "Borrador"), ("sent", "Enviada"), ("approved", "Aprobada"), ("cancelled", "Cancelada"), ("expired", "Vencida")], db_index=True, default="draft", max_length=12)),
                ("issue_date", models.DateField(default=timezone.localdate)),
                ("valid_until", models.DateField(blank=True, null=True)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_quotes", to=settings.AUTH_USER_MODEL)),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="quotes", to="sales.customer")),
            ],
            options={
                "ordering": ["-created_at"],
                "permissions": [
                    ("send_quote", "Puede enviar cotizaciones"),
                    ("approve_quote", "Puede aprobar cotizaciones"),
                    ("cancel_quote", "Puede cancelar cotizaciones"),
                ],
            },
        ),
        migrations.CreateModel(
            name="QuoteLine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("kind", models.CharField(choices=[("equipment", "Equipo"), ("material", "Material"), ("installation", "Instalación"), ("service", "Servicio")], max_length=16)),
                ("description", models.CharField(max_length=300)),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=12)),
                ("unit_price", models.DecimalField(decimal_places=2, max_digits=14)),
                ("tax_rate", models.DecimalField(decimal_places=2, default=decimal.Decimal("16.00"), max_digits=5)),
                ("quote", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="sales.quote")),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.CreateModel(
            name="SalesOrder",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("confirmed_at", models.DateTimeField(default=timezone.now)),
                ("confirmed_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("quote", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="sales_order", to="sales.quote")),
            ],
        ),
        migrations.CreateModel(
            name="WorkOrder",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=240)),
                ("status", models.CharField(choices=[("planned", "Programada"), ("in_progress", "En curso"), ("blocked", "Bloqueada"), ("done", "Terminada"), ("cancelled", "Cancelada")], db_index=True, default="planned", max_length=16)),
                ("scheduled_start", models.DateTimeField(blank=True, null=True)),
                ("scheduled_end", models.DateTimeField(blank=True, null=True)),
                ("completion_notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("assigned_to", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="assigned_work_orders", to=settings.AUTH_USER_MODEL)),
                ("sales_order", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="work_order", to="sales.salesorder")),
            ],
        ),
        migrations.CreateModel(
            name="AuditEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("entity_type", models.CharField(max_length=60)),
                ("entity_id", models.UUIDField()),
                ("action", models.CharField(max_length=60)),
                ("from_value", models.CharField(blank=True, max_length=32)),
                ("to_value", models.CharField(blank=True, max_length=32)),
                ("occurred_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-occurred_at"]},
        ),
        migrations.AlterModelOptions(
            name="workorder",
            options={"permissions": [("transition_workorder", "Puede cambiar el estado de órdenes de trabajo")]},
        ),
    ]
