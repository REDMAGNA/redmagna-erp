import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0006_opportunities"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="OpportunityActivity",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("activity_type", models.CharField(choices=[("call", "Llamada"), ("email", "Correo"), ("meeting", "Reunión"), ("task", "Tarea")], default="task", max_length=12)),
                ("title", models.CharField(max_length=240)),
                ("due_at", models.DateTimeField(db_index=True)),
                ("status", models.CharField(choices=[("planned", "Pendiente"), ("done", "Completada"), ("cancelled", "Cancelada")], db_index=True, default="planned", max_length=12)),
                ("note", models.TextField(blank=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("assigned_to", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="assigned_redmagna_activities", to=settings.AUTH_USER_MODEL)),
                ("completed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="completed_redmagna_activities", to=settings.AUTH_USER_MODEL)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_redmagna_activities", to=settings.AUTH_USER_MODEL)),
                ("opportunity", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="activities", to="sales.opportunity")),
            ],
            options={
                "ordering": ["status", "due_at", "created_at"],
                "permissions": [("complete_opportunityactivity", "Puede completar actividades comerciales")],
            },
        ),
    ]
