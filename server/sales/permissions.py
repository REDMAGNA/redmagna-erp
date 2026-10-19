from rest_framework.permissions import BasePermission


class ActionPermissions(BasePermission):
    """Map each API action to Django model/group permissions."""

    permission_map = {}

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        required = self.permission_map.get(getattr(view, "action", ""))
        return bool(required and request.user.has_perms(required))


class CustomerPermissions(ActionPermissions):
    permission_map = {
        "list": ["sales.view_customer"],
        "retrieve": ["sales.view_customer"],
        "create": ["sales.add_customer"],
        "import_csv": ["sales.view_customer", "sales.add_customer"],
        "update": ["sales.change_customer"],
        "partial_update": ["sales.change_customer"],
        "destroy": ["sales.delete_customer"],
    }


class CustomerSitePermissions(ActionPermissions):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        action = getattr(view, "action", "")
        if action in {"list", "retrieve"}:
            return request.user.has_perm("sales.view_customer") or request.user.has_perm("sales.schedule_workorder")
        if action == "create":
            return request.user.has_perm("sales.add_customer") or request.user.has_perm("sales.schedule_workorder")
        if action in {"update", "partial_update"}:
            return request.user.has_perm("sales.change_customer") or request.user.has_perm("sales.schedule_workorder")
        return False


class CustomerContactPermissions(ActionPermissions):
    permission_map = {
        "list": ["sales.view_customer"],
        "retrieve": ["sales.view_customer"],
        "create": ["sales.add_customer"],
        "update": ["sales.change_customer"],
        "partial_update": ["sales.change_customer"],
    }


class OpportunityPermissions(ActionPermissions):
    permission_map = {
        "list": ["sales.view_opportunity"],
        "retrieve": ["sales.view_opportunity"],
        "create": ["sales.add_opportunity"],
        "update": ["sales.change_opportunity"],
        "partial_update": ["sales.change_opportunity"],
        "qualify": ["sales.transition_opportunity"],
        "reopen": ["sales.transition_opportunity"],
        "mark_lost": ["sales.transition_opportunity"],
        "convert": ["sales.transition_opportunity"],
        "assignees": ["sales.view_opportunity"],
        "report": ["sales.view_opportunity"],
    }


class OpportunityActivityPermissions(ActionPermissions):
    permission_map = {
        "list": ["sales.view_opportunityactivity"],
        "retrieve": ["sales.view_opportunityactivity"],
        "create": ["sales.add_opportunityactivity"],
        "update": ["sales.change_opportunityactivity"],
        "partial_update": ["sales.change_opportunityactivity"],
        "complete": ["sales.complete_opportunityactivity"],
        "cancel": ["sales.change_opportunityactivity"],
    }


class QuotePermissions(ActionPermissions):
    permission_map = {
        "list": ["sales.view_quote"],
        "retrieve": ["sales.view_quote"],
        "create": ["sales.add_quote"],
        "update": ["sales.change_quote"],
        "partial_update": ["sales.change_quote"],
        "send": ["sales.send_quote"],
        "send_email": ["sales.send_quote"],
        "approve": ["sales.approve_quote"],
        "approve_discount": ["sales.approve_quote"],
        "cancel": ["sales.cancel_quote"],
        "revise": ["sales.revise_quote"],
    }


class QuoteCostSheetPermissions(BasePermission):
    """Keep internal purchase costs behind dedicated permissions."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        permission = "sales.view_quotecostsheet" if request.method in {"GET", "HEAD", "OPTIONS"} else "sales.change_quotecostsheet"
        return request.user.has_perms(["sales.view_quote", permission])


class QuoteTemplatePermissions(ActionPermissions):
    permission_map = {
        "list": ["sales.view_quote"],
        "retrieve": ["sales.view_quote"],
        "create": ["sales.add_quote"],
        "update": ["sales.change_quote"],
        "partial_update": ["sales.change_quote"],
    }


class WorkOrderPermissions(ActionPermissions):
    permission_map = {
        "list": ["sales.view_workorder"],
        "retrieve": ["sales.view_workorder"],
        "transition": ["sales.transition_workorder"],
        "schedule": ["sales.schedule_workorder"],
        "assign_material_location": ["inventory.change_reorderrule"],
        "checklist": ["sales.view_workorder"],
        "add_checklist_item": ["sales.transition_workorder"],
        "update_checklist_item": ["sales.transition_workorder"],
        "apply_checklist_template": ["sales.transition_workorder"],
        "customer_acceptance": ["sales.record_workorder_acceptance"],
        "assignees": ["sales.schedule_workorder"],
        "log_hours": ["sales.log_workorder_hours"],
        "hours_report": ["sales.view_workorder"],
        "create_invoice": ["billing.add_customerinvoice"],
    }

    def has_permission(self, request, view):
        if (getattr(view, "action", "") == "schedule"
                and request.user.has_perm("sales.change_workorder")
                and not request.user.has_perm("sales.schedule_workorder")):
            return True
        return super().has_permission(request, view)


class WorkOrderChecklistTemplatePermissions(ActionPermissions):
    permission_map = {
        "list": ["sales.view_workorder"],
        "retrieve": ["sales.view_workorder"],
        "create": ["sales.schedule_workorder"],
        "update": ["sales.schedule_workorder"],
        "partial_update": ["sales.schedule_workorder"],
    }


class WorkOrderEvidencePermissions(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        required = ["sales.view_workorder", "sales.view_workorderevidence"]
        if request.method == "POST":
            required = ["sales.view_workorder", "sales.add_workorderevidence"]
        return request.user.has_perms(required)
