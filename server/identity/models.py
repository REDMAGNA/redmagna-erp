import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class ApiSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="api_sessions")
    token_digest = models.CharField(max_length=64, unique=True)
    token_prefix = models.CharField(max_length=12)
    session_name = models.CharField(max_length=120, default="Navegador web")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True, db_index=True)
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="revoked_api_sessions")
    remote_ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = [
            ("view_all_apisessions", "Puede consultar sesiones de todas las cuentas"),
            ("revoke_apisessions", "Puede revocar sesiones de cualquier cuenta"),
        ]

    @property
    def is_active(self):
        return self.revoked_at is None and self.expires_at > timezone.now() and self.user.is_active

    def revoke(self, actor=None):
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.revoked_by = actor
            self.save(update_fields=["revoked_at", "revoked_by"])
