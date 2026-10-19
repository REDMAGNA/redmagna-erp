import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.response import Response
from django.utils import timezone

from identity.models import ApiSession


class TokenLoginView(ObtainAuthToken):
    """Issue a separately revocable, bounded token for each browser session."""

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        key = secrets.token_urlsafe(48)
        created_at = timezone.now()
        expires_at = created_at + timedelta(hours=settings.ERP_API_TOKEN_TTL_HOURS)
        session_name = request.data.get("session_name", "Navegador web")
        if not isinstance(session_name, str):
            session_name = "Navegador web"
        session_name = session_name.strip()[:120] or "Navegador web"
        remote_ip = request.META.get("REMOTE_ADDR") or None
        user_agent = request.META.get("HTTP_USER_AGENT", "")[:500]
        with transaction.atomic():
            session = ApiSession.objects.create(
                user=user,
                token_digest=hashlib.sha256(key.encode("ascii")).hexdigest(),
                token_prefix=key[:12],
                session_name=session_name,
                created_at=created_at,
                expires_at=expires_at,
                remote_ip=remote_ip,
                user_agent=user_agent,
            )

        return Response({"token": key, "session_id": str(session.pk), "session_name": session.session_name, "expires_at": expires_at.isoformat()})
