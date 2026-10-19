import os
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email


PLACEHOLDER_PARTS = ("replace-with", "change-me", "changeme", "local-only", "example-secret")


def validate_secret(name, minimum_length):
    value = os.environ.get(name, "")
    errors = []
    if not value:
        return [f"{name} es obligatorio."]
    if len(value) < minimum_length:
        errors.append(f"{name} debe tener al menos {minimum_length} caracteres.")
    if value != value.strip() or any(character.isspace() for character in value):
        errors.append(f"{name} no debe contener espacios.")
    if any(part in value.lower() for part in PLACEHOLDER_PARTS):
        errors.append(f"{name} todavía contiene un valor de ejemplo; cámbialo por un secreto aleatorio.")
    if len(set(value)) < 10:
        errors.append(f"{name} tiene poca variedad de caracteres; usa un secreto aleatorio.")
    return errors


class Command(BaseCommand):
    help = "Valida requisitos de seguridad antes de migrar o iniciar el servicio."

    def handle(self, *args, **options):
        errors = []
        errors.extend(validate_secret("DJANGO_SECRET_KEY", 50))
        errors.extend(validate_secret("POSTGRES_PASSWORD", 24))

        django_secret = os.environ.get("DJANGO_SECRET_KEY", "")
        postgres_password = os.environ.get("POSTGRES_PASSWORD", "")
        if django_secret and postgres_password and django_secret == postgres_password:
            errors.append("DJANGO_SECRET_KEY y POSTGRES_PASSWORD deben ser distintos.")
        if settings.DEBUG:
            errors.append("DJANGO_DEBUG debe estar desactivado para este despliegue.")
        if settings.ERP_API_TOKEN_TTL_HOURS < 1:
            errors.append("ERP_API_TOKEN_TTL_HOURS debe ser al menos 1 hora.")
        if "*" in settings.ALLOWED_HOSTS:
            errors.append("DJANGO_ALLOWED_HOSTS no puede incluir '*'.")

        for origin in settings.CSRF_TRUSTED_ORIGINS:
            parsed_origin = urlsplit(origin)
            if parsed_origin.scheme != "https" or not parsed_origin.netloc or parsed_origin.path or parsed_origin.query or parsed_origin.fragment:
                errors.append("DJANGO_CSRF_TRUSTED_ORIGINS solo admite orígenes HTTPS completos, sin rutas ni parámetros.")
                break
        if settings.SECURE_SSL_REDIRECT and not settings.USE_HTTPS_PROXY:
            errors.append("DJANGO_SECURE_SSL_REDIRECT=true requiere DJANGO_USE_HTTPS_PROXY=true en esta imagen.")
        if settings.USE_HTTPS_PROXY and settings.APP_BIND_ADDRESS != "127.0.0.1":
            errors.append("DJANGO_USE_HTTPS_PROXY=true requiere APP_BIND_ADDRESS=127.0.0.1 para publicar el puerto del NAS solo en loopback y aceptar X-Forwarded-Proto únicamente desde el proxy local.")
        if settings.ERP_PUBLIC_LEADS_ENABLED:
            privacy_url = urlsplit(settings.ERP_PRIVACY_URL)
            if privacy_url.scheme != "https" or not privacy_url.netloc or privacy_url.username or privacy_url.password:
                errors.append("ERP_PUBLIC_LEADS_ENABLED=true requiere ERP_PRIVACY_URL con una URL HTTPS pública válida.")
            if not settings.USE_HTTPS_PROXY or settings.APP_BIND_ADDRESS != "127.0.0.1":
                errors.append("ERP_PUBLIC_LEADS_ENABLED=true requiere HTTPS mediante el proxy inverso DSM y APP_BIND_ADDRESS=127.0.0.1 para limitar el puerto publicado al loopback del NAS.")
        if settings.CRM_LEAD_NOTIFICATION_EMAIL:
            try:
                validate_email(settings.CRM_LEAD_NOTIFICATION_EMAIL)
            except ValidationError:
                errors.append("CRM_LEAD_NOTIFICATION_EMAIL debe contener una dirección válida.")
        if settings.SESSION_COOKIE_SECURE and not settings.USE_HTTPS_PROXY:
            errors.append("DJANGO_SECURE_COOKIES=true requiere DJANGO_USE_HTTPS_PROXY=true en esta imagen.")
        if settings.SECURE_HSTS_SECONDS < 0:
            errors.append("DJANGO_SECURE_HSTS_SECONDS debe ser cero o mayor.")
        if settings.SECURE_HSTS_SECONDS and (not settings.USE_HTTPS_PROXY or not settings.SESSION_COOKIE_SECURE):
            errors.append("HSTS requiere DJANGO_USE_HTTPS_PROXY=true y DJANGO_SECURE_COOKIES=true.")

        environment = os.environ.get("FEL_ENVIRONMENT", "test").strip().lower()
        if environment not in {"test", "production"}:
            errors.append("FEL_ENVIRONMENT debe ser 'test' o 'production'.")
        if environment == "production" and os.environ.get("FEL_ALLOW_PRODUCTION", "false").lower() != "true":
            errors.append("FEL_ALLOW_PRODUCTION=true es obligatorio al usar FEL_ENVIRONMENT=production.")
        if os.environ.get("FEL_ALLOW_CANCELLATION", "false").lower() == "true":
            if environment != "production" or os.environ.get("FEL_ALLOW_PRODUCTION", "false").lower() != "true":
                errors.append("Las cancelaciones FEL requieren entorno de producción habilitado.")
            if not os.environ.get("FEL_CANCEL_PFX_BASE64", "").strip() or not os.environ.get("FEL_CANCEL_PFX_PASSWORD", ""):
                errors.append("Las cancelaciones FEL requieren FEL_CANCEL_PFX_BASE64 y FEL_CANCEL_PFX_PASSWORD.")

        if settings.EMAIL_USE_TLS and settings.EMAIL_USE_SSL:
            errors.append("EMAIL_USE_TLS y EMAIL_USE_SSL no pueden estar activos a la vez.")

        if errors:
            details = "\n".join(f"- {error}" for error in errors)
            raise CommandError(f"Verificación de despliegue falló. Corrige estos valores antes de iniciar:\n{details}")
        self.stdout.write(self.style.SUCCESS("Configuración de despliegue validada."))
