import uuid

import django.utils.timezone
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0012_remove_openingbalanceitem_accounting_opening_external_item_uniq_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PostingConfigurationEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("before", models.JSONField(blank=True, null=True)),
                ("after", models.JSONField()),
                ("occurred_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="posting_configuration_events", to=settings.AUTH_USER_MODEL)),
                ("configuration", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="change_history", to="accounting.postingconfiguration")),
            ],
            options={
                "verbose_name": "Cambio de configuración de póliza",
                "verbose_name_plural": "Cambios de configuración de pólizas",
                "ordering": ["-occurred_at", "-id"],
            },
        ),
    ]
