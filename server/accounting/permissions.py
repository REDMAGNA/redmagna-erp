from rest_framework.permissions import BasePermission


class ActionPermissions(BasePermission):
    permission_map = {}

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        required = self.permission_map.get(getattr(view, "action", ""))
        return bool(required and request.user.has_perms(required))


class AccountPermissions(ActionPermissions):
    permission_map = {
        "list": ["accounting.view_account"], "retrieve": ["accounting.view_account"],
        "create": ["accounting.add_account"], "partial_update": ["accounting.change_account"],
    }


class JournalPermissions(ActionPermissions):
    permission_map = {
        "list": ["accounting.view_journal"], "retrieve": ["accounting.view_journal"],
        "create": ["accounting.add_journal"], "partial_update": ["accounting.change_journal"],
    }


class PostingConfigurationPermissions(ActionPermissions):
    permission_map = {
        "list": ["accounting.view_postingconfiguration"],
        "retrieve": ["accounting.view_postingconfiguration"],
        "create": ["accounting.add_postingconfiguration"],
        "partial_update": ["accounting.change_postingconfiguration"],
    }


class JournalEntryPermissions(ActionPermissions):
    permission_map = {
        "list": ["accounting.view_journalentry"],
        "retrieve": ["accounting.view_journalentry"],
        "create": ["accounting.add_journalentry"],
        "import_opening_balances": ["accounting.add_journalentry"],
        "update": ["accounting.change_journalentry"],
        "partial_update": ["accounting.change_journalentry"],
        "post": ["accounting.post_journalentry"],
        "reverse": ["accounting.reverse_journalentry"],
    }


class BankStatementPermissions(ActionPermissions):
    permission_map = {
        "list": ["accounting.view_bankstatement"],
        "retrieve": ["accounting.view_bankstatement"],
        "create": ["accounting.add_bankstatement"],
        "candidate_lines": ["accounting.view_bankstatement", "accounting.view_journalentry"],
        "auto_match_references": ["accounting.change_bankstatement", "accounting.view_journalentry"],
        "match_line": ["accounting.change_bankstatement", "accounting.view_journalentry"],
        "prepare_adjustment": ["accounting.change_bankstatement", "accounting.add_journalentry", "accounting.view_account", "accounting.view_journal"],
        "unmatch_line": ["accounting.change_bankstatement", "accounting.view_journalentry"],
        "reconcile": ["accounting.reconcile_bankstatement"],
    }


class AccountingPeriodPermissions(ActionPermissions):
    permission_map = {
        "list": ["accounting.view_accountingperiod"],
        "retrieve": ["accounting.view_accountingperiod"],
        "create": ["accounting.add_accountingperiod"],
        "close": ["accounting.close_accountingperiod"],
        "reopen": ["accounting.reopen_accountingperiod"],
    }


class OpeningBalanceBatchPermissions(ActionPermissions):
    permission_map = {
        "list": ["accounting.view_journalentry"],
        "retrieve": ["accounting.view_journalentry"],
        "prepare": ["accounting.prepare_openingbalancebatch"],
        "review": ["accounting.review_openingbalancebatch"],
    }
