from rest_framework.permissions import BasePermission


class SupportTicketPermissions(BasePermission):
    permission_map = {
        "list": ["support.view_supportticket"],
        "retrieve": ["support.view_supportticket"],
        "create": ["support.add_supportticket"],
        "update": ["support.change_supportticket"],
        "partial_update": ["support.change_supportticket"],
        "transition": ["support.transition_supportticket"],
        "assignees": ["support.assign_supportticket"],
        "assets": ["support.view_supportticket"],
        "send_portal_link": ["support.send_supportticket_portal_link", "support.view_supportticket"],
        "add_message": ["support.add_supportticketmessage", "support.view_supportticket"],
    }

    def has_permission(self, request, view):
        required = self.permission_map.get(getattr(view, "action", ""), [])
        return bool(request.user and request.user.is_authenticated and required and request.user.has_perms(required))
