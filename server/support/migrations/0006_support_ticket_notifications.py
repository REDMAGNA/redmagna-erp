import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("support", "0005_support_message_public_replies"),
    ]

    operations = [
        migrations.CreateModel(
            name="SupportTicketNotification",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("recipient_email", models.EmailField(blank=True, max_length=254)),
                ("status", models.CharField(choices=[("pending", "Pendiente"), ("sent", "Enviado"), ("failed", "Fallido"), ("skipped", "Sin correo disponible")], db_index=True, default="pending", max_length=10)),
                ("attempt_count", models.PositiveSmallIntegerField(default=0)),
                ("next_attempt_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("last_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.CharField(blank=True, max_length=300)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("message", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="staff_notification", to="support.supportticketmessage")),
                ("recipient", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="support_ticket_notifications", to=settings.AUTH_USER_MODEL)),
                ("ticket", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="notifications", to="support.supportticket")),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
    ]
