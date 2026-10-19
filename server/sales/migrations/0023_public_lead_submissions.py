import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("sales", "0022_material_supply_location"),
    ]

    operations = [
        migrations.AlterField(
            model_name="opportunity",
            name="created_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="created_redmagna_opportunities", to=settings.AUTH_USER_MODEL),
        ),
        migrations.CreateModel(
            name="PublicLeadSubmission",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("nonce", models.UUIDField(unique=True)),
                ("email_digest", models.CharField(db_index=True, max_length=64)),
                ("consent_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("opportunity", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="public_submission", to="sales.opportunity")),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
