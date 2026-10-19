from rest_framework.permissions import BasePermission


class RepairCasePermissions(BasePermission):
    permission_map = {
        "list": ["repairs.view_repaircase"],
        "retrieve": ["repairs.view_repaircase"],
        "create": ["repairs.add_repaircase"],
        "partial_update": ["repairs.change_repaircase"],
        "update": ["repairs.change_repaircase"],
        "transition": ["repairs.transition_repaircase"],
        "custody": ["repairs.transition_repaircase"],
    }

    def has_permission(self, request, view):
        required = self.permission_map.get(getattr(view, "action", ""), [])
        return bool(request.user and request.user.is_authenticated and required and request.user.has_perms(required))
