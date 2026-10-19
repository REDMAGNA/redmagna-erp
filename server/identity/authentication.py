import hashlib
from datetime import timedelta

from django.utils import timezone
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from .models import ApiSession


class SessionTokenAuthentication(BaseAuthentication):
    keyword = b"token"
    touch_interval = timedelta(minutes=1)

    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts:
            return None
        if parts[0].lower() != self.keyword:
            return None
        if len(parts) != 2:
            raise AuthenticationFailed("La cabecera de autenticación no es válida.")
        try:
            key = parts[1].decode("ascii")
        except UnicodeDecodeError as error:
            raise AuthenticationFailed("La sesión no es válida.") from error
        digest = hashlib.sha256(key.encode("ascii")).hexdigest()
        try:
            session = ApiSession.objects.select_related("user").get(token_digest=digest)
        except ApiSession.DoesNotExist as error:
            raise AuthenticationFailed("La sesión no existe o fue revocada.") from error
        now = timezone.now()
        if session.revoked_at is not None:
            raise AuthenticationFailed("La sesión fue revocada. Vuelve a conectar tu usuario.")
        if session.expires_at <= now:
            raise AuthenticationFailed("La sesión expiró. Vuelve a conectar tu usuario.")
        if not session.user.is_active:
            raise AuthenticationFailed("La cuenta está inactiva.")
        if session.last_used_at is None or session.last_used_at <= now - self.touch_interval:
            ApiSession.objects.filter(pk=session.pk, revoked_at__isnull=True, expires_at__gt=now).update(last_used_at=now)
            session.last_used_at = now
        return session.user, session

    def authenticate_header(self, request):
        return "Token"
