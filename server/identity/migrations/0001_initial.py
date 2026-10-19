import hashlib
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.utils import timezone


def migrate_legacy_tokens(apps, schema_editor):
    LegacyToken = apps.get_model("authtoken", "Token")
    ApiSession = apps.get_model("identity", "ApiSession")
    ttl_hours = int(getattr(settings, "ERP_API_TOKEN_TTL_HOURS", 12))
    for token in LegacyToken.objects.select_related("user").iterator():
        ApiSession.objects.get_or_create(
            token_digest=hashlib.sha256(token.key.encode("ascii")).hexdigest(),
            defaults={
                "user_id": token.user_id,
                "token_prefix": token.key[:12],
                "session_name": "Sesión migrada",
                "created_at": token.created,
                "expires_at": token.created + timedelta(hours=ttl_hours),
            },
        )
    LegacyToken.objects.all().delete()


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("authtoken", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ApiSession",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("token_digest", models.CharField(max_length=64, unique=True)),
                ("token_prefix", models.CharField(max_length=12)),
                ("session_name", models.CharField(default="Navegador web", max_length=120)),
                ("created_at", models.DateTimeField(db_index=True, default=timezone.now)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("last_used_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("remote_ip", models.GenericIPAddressField(blank=True, null=True)),
                ("user_agent", models.CharField(blank=True, max_length=500)),
                ("revoked_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="revoked_api_sessions", to=settings.AUTH_USER_MODEL)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="api_sessions", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at"],
                "permissions": [
                    ("view_all_apisessions", "Puede consultar sesiones de todas las cuentas"),
                    ("revoke_apisessions", "Puede revocar sesiones de cualquier cuenta"),
                ],
            },
        ),
        migrations.RunPython(migrate_legacy_tokens),
    ]
