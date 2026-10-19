from rest_framework.permissions import BasePermission


class ExpensePermissions(BasePermission):
    action_permissions = {
        "list": "expenses.view_expense", "retrieve": "expenses.view_expense",
        "create": "expenses.add_expense", "update": "expenses.change_expense",
        "partial_update": "expenses.change_expense", "upload_receipt": "expenses.add_expensereceipt",
        "receipt": "expenses.view_expense", "submit": "expenses.submit_expensereport",
        "approve": "expenses.approve_expensereport", "reject": "expenses.approve_expensereport",
        "prepare_journal": "expenses.post_expensereport",
        "reimburse": "expenses.register_expensereimbursement",
        "reverse_reimbursement": "expenses.reverse_expensereimbursement",
    }

    def has_permission(self, request, view):
        perm = self.action_permissions.get(getattr(view, "action", ""))
        return bool(request.user and request.user.is_authenticated and perm and request.user.has_perm(perm))
