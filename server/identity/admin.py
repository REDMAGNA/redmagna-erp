from django.contrib import admin

from .models import ApiSession


@admin.register(ApiSession)
class ApiSessionAdmin(admin.ModelAdmin):
    list_display = ["user", "session_name", "created_at", "last_used_at", "expires_at", "revoked_at", "revoked_by"]
    list_filter = ["created_at", "expires_at", "revoked_at"]
    search_fields = ["user__username", "user__email", "session_name", "token_prefix", "remote_ip"]
    readonly_fields = [field.name for field in ApiSession._meta.fields if field.name != "token_digest"]
    actions = ["revoke_selected_sessions"]

    @admin.action(description="Revocar sesiones seleccionadas")
    def revoke_selected_sessions(self, request, queryset):
        count = 0
        for session in queryset.select_related("user"):
            if session.revoked_at is None:
                session.revoke(request.user)
                count += 1
        self.message_user(request, f"Se revocaron {count} sesiones.")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or request.user.has_perm("identity.revoke_apisessions")

    def has_delete_permission(self, request, obj=None):
        return False
