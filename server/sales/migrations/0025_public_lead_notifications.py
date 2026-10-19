import uuid
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [("sales", "0024_opportunity_utm_attribution")]

    operations = [
        migrations.CreateModel(
            name="PublicLeadNotification",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("recipient_email", models.EmailField(max_length=254)),
                ("status", models.CharField(choices=[("pending", "Pendiente"), ("sent", "Enviado"), ("failed", "Fallido")], db_index=True, default="pending", max_length=10)),
                ("attempt_count", models.PositiveSmallIntegerField(default=0)),
                ("next_attempt_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("last_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.CharField(blank=True, max_length=120)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("submission", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="notification", to="sales.publicleadsubmission")),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
    ]
