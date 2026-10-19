import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("billing", "0015_customerinvoice_opening_balance_batch_id_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="CustomerInvoiceReminder",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("kind", models.CharField(choices=[("upcoming", "Próximo a vencer"), ("overdue", "Vencido")], max_length=12)),
                ("status", models.CharField(choices=[("pending", "Pendiente"), ("sent", "Enviado"), ("failed", "Agotó reintentos"), ("skipped", "Omitido")], db_index=True, default="pending", max_length=12)),
                ("recipient_email", models.EmailField(blank=True, max_length=254)),
                ("balance_snapshot", models.DecimalField(blank=True, decimal_places=2, max_digits=16, null=True)),
                ("due_date_snapshot", models.DateField(blank=True, null=True)),
                ("attempt_count", models.PositiveSmallIntegerField(default=0)),
                ("manual_retry_count", models.PositiveSmallIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("next_attempt_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.CharField(blank=True, max_length=120)),
                ("manual_retried_at", models.DateTimeField(blank=True, null=True)),
                ("manual_retried_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="retried_customer_invoice_reminders", to=settings.AUTH_USER_MODEL)),
                ("invoice", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="reminders", to="billing.customerinvoice")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="customerinvoicereminder",
            constraint=models.UniqueConstraint(fields=("invoice", "kind"), name="billing_invoice_reminder_once"),
        ),
        migrations.AddConstraint(
            model_name="customerinvoicereminder",
            constraint=models.CheckConstraint(
                condition=models.Q(balance_snapshot__isnull=True) | models.Q(balance_snapshot__gte=0),
                name="billing_reminder_balance_nonnegative",
            ),
        ),
    ]
