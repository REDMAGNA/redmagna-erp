import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("sales", "0012_workorder_customer_acceptance"),
    ]

    operations = [
        migrations.CreateModel(
            name="SupportTicket",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("number", models.CharField(blank=True, max_length=24, unique=True)),
                ("title", models.CharField(max_length=240)),
                ("description", models.TextField()),
                ("status", models.CharField(choices=[("new", "Nuevo"), ("in_progress", "En atención"), ("waiting_customer", "En espera del cliente"), ("resolved", "Resuelto"), ("closed", "Cerrado"), ("cancelled", "Cancelado")], db_index=True, default="new", max_length=20)),
                ("priority", models.CharField(choices=[("low", "Baja"), ("normal", "Normal"), ("high", "Alta"), ("urgent", "Urgente")], db_index=True, default="normal", max_length=10)),
                ("channel", models.CharField(choices=[("phone", "Teléfono"), ("email", "Correo"), ("web", "Web"), ("internal", "Interno")], default="internal", max_length=10)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("assigned_to", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="assigned_support_tickets", to=settings.AUTH_USER_MODEL)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_support_tickets", to=settings.AUTH_USER_MODEL)),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="support_tickets", to="sales.customer")),
                ("work_order", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="support_tickets", to="sales.workorder")),
            ],
            options={
                "ordering": ["-updated_at", "-created_at"],
                "permissions": [("transition_supportticket", "Puede cambiar el estado de tickets de soporte"), ("assign_supportticket", "Puede asignar tickets de soporte")],
            },
        ),
        migrations.CreateModel(
            name="SupportTicketMessage",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("body", models.TextField(max_length=4000)),
                ("created_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("author", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="support_ticket_messages", to=settings.AUTH_USER_MODEL)),
                ("ticket", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="messages", to="support.supportticket")),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
        migrations.CreateModel(
            name="SupportTicketEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("action", models.CharField(max_length=40)),
                ("from_status", models.CharField(blank=True, max_length=20)),
                ("to_status", models.CharField(blank=True, max_length=20)),
                ("detail", models.CharField(blank=True, max_length=500)),
                ("occurred_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="support_ticket_events", to=settings.AUTH_USER_MODEL)),
                ("ticket", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="events", to="support.supportticket")),
            ],
            options={"ordering": ["-occurred_at", "-id"]},
        ),
    ]
