from django.utils import timezone

from .models import ApiSession


def capture_security_state(sender, instance, using, **kwargs):
    if not instance.pk:
        instance._identity_previous_security_state = None
        return
    instance._identity_previous_security_state = (
        sender.objects.using(using)
        .filter(pk=instance.pk)
        .values("password", "is_active")
        .first()
    )


def revoke_sessions_after_security_change(sender, instance, using, created, **kwargs):
    previous = getattr(instance, "_identity_previous_security_state", None)
    if created or previous is None:
        return
    password_changed = previous["password"] != instance.password
    account_disabled = previous["is_active"] and not instance.is_active
    if password_changed or account_disabled:
        ApiSession.objects.using(using).filter(user_id=instance.pk, revoked_at__isnull=True).update(
            revoked_at=timezone.now(),
            revoked_by=None,
        )
