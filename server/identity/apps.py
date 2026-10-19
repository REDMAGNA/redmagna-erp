from django.apps import AppConfig


class IdentityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "identity"
    verbose_name = "Accesos y sesiones"

    def ready(self):
        from django.contrib.auth import get_user_model
        from django.db.models.signals import post_save, pre_save

        from .signals import capture_security_state, revoke_sessions_after_security_change

        user_model = get_user_model()
        pre_save.connect(capture_security_state, sender=user_model, dispatch_uid="identity.capture_security_state")
        post_save.connect(revoke_sessions_after_security_change, sender=user_model, dispatch_uid="identity.revoke_sessions_after_security_change")
