import uuid

import django.db.models.deletion
import sales.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("sales", "0009_workorder_checklist_item"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkOrderEvidence",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("file", models.FileField(max_length=300, upload_to=sales.models.work_order_evidence_upload_to)),
                ("original_name", models.CharField(max_length=255)),
                ("content_type", models.CharField(max_length=40)),
                ("file_size", models.PositiveBigIntegerField()),
                ("description", models.CharField(blank=True, max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("uploaded_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="redmagna_work_order_evidence", to=settings.AUTH_USER_MODEL)),
                ("work_order", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="evidence", to="sales.workorder")),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
