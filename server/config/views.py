from django.conf import settings
from django.db import connection
from django.http import FileResponse, JsonResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from identity.models import ApiSession


def _session_data(session, current_id=None):
    return {
        "id": str(session.pk),
        "username": session.user.get_username(),
        "session_name": session.session_name,
        "token_prefix": session.token_prefix,
        "created_at": session.created_at.isoformat(),
        "last_used_at": session.last_used_at.isoformat() if session.last_used_at else None,
        "expires_at": session.expires_at.isoformat(),
        "revoked_at": session.revoked_at.isoformat() if session.revoked_at else None,
        "remote_ip": session.remote_ip,
        "user_agent": session.user_agent,
        "is_current": str(session.pk) == str(current_id),
        "is_active": session.is_active,
    }


def health_check(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return JsonResponse({"status": "unhealthy"}, status=503)
    return JsonResponse({"status": "ok"})


class CurrentUserView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            "username": request.user.get_username(),
            "groups": list(request.user.groups.order_by("name").values_list("name", flat=True)),
            "permissions": sorted(request.user.get_all_permissions()),
            "token_expires_at": request.auth.expires_at.isoformat() if isinstance(request.auth, ApiSession) else None,
            "session_id": str(request.auth.pk) if isinstance(request.auth, ApiSession) else None,
        })


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if isinstance(request.auth, ApiSession):
            request.auth.revoke(request.user)
        return Response(status=204)


class ApiSessionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sessions = ApiSession.objects.select_related("user", "revoked_by")
        if not request.user.has_perm("identity.view_all_apisessions"):
            sessions = sessions.filter(user=request.user)
        return Response([_session_data(session, request.auth.pk if isinstance(request.auth, ApiSession) else None) for session in sessions[:200]])


class ApiSessionRevokeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        sessions = ApiSession.objects.filter(pk=session_id)
        if not request.user.has_perm("identity.revoke_apisessions"):
            sessions = sessions.filter(user=request.user)
        session = sessions.first()
        if session is None:
            raise NotFound("No se encontró una sesión disponible para esta cuenta.")
        session.revoke(request.user)
        return Response(status=204)


def serve_frontend_script(request):
    script_path = settings.BASE_DIR / "app.js"
    if not script_path.exists():
        script_path = settings.BASE_DIR.parent / "dist" / "app.js"
    return FileResponse(open(script_path, "rb"), content_type="application/javascript; charset=utf-8")


def serve_license(request):
    license_path = settings.BASE_DIR.parent / "LICENSE"
    return FileResponse(open(license_path, "rb"), content_type="text/plain; charset=utf-8", as_attachment=False)


def serve_source_bundle(request):
    source_path = settings.BASE_DIR.parent / "source.zip"
    return FileResponse(open(source_path, "rb"), content_type="application/zip", as_attachment=True, filename="redmagna-erp-source.zip")
