import django.db.models.deletion
import django.utils.timezone
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("support", "0007_support_sla_policies"),
    ]

    operations = [
        migrations.CreateModel(
            name="SupportInboundEmailReceipt",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("mailbox", models.CharField(max_length=200)),
                ("uidvalidity", models.PositiveBigIntegerField()),
                ("uid", models.PositiveBigIntegerField()),
                ("message_id", models.CharField(blank=True, max_length=255)),
                ("sender_email", models.EmailField(blank=True, max_length=254)),
                ("status", models.CharField(choices=[("accepted", "Agregado al ticket"), ("rejected", "Rechazado"), ("ignored", "Ignorado")], db_index=True, max_length=10)),
                ("reason_code", models.CharField(blank=True, max_length=40)),
                ("received_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("message", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="inbound_email", to="support.supportticketmessage")),
                ("ticket", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="inbound_emails", to="support.supportticket")),
            ],
            options={"ordering": ["-received_at", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="supportinboundemailreceipt",
            constraint=models.UniqueConstraint(fields=("mailbox", "uidvalidity", "uid"), name="support_inbound_mail_uid_unique"),
        ),
        migrations.AddConstraint(
            model_name="supportinboundemailreceipt",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(status="accepted", ticket__isnull=False, message__isnull=False, reason_code="")
                    | (models.Q(status__in=["rejected", "ignored"], ticket__isnull=True, message__isnull=True) & ~models.Q(reason_code=""))
                ),
                name="support_inbound_mail_final_state",
            ),
        ),
    ]
