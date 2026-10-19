import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0007_opportunity_activities"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="OpportunityActivityReminder",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("kind", models.CharField(choices=[("upcoming", "Próximo"), ("overdue", "Vencido")], max_length=10)),
                ("due_at", models.DateTimeField()),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("activity", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="reminder_logs", to="sales.opportunityactivity")),
                ("recipient", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="redmagna_activity_reminders", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-sent_at", "-due_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="opportunityactivityreminder",
            constraint=models.UniqueConstraint(fields=("activity", "recipient", "kind", "due_at"), name="sales_activity_reminder_once"),
        ),
    ]
