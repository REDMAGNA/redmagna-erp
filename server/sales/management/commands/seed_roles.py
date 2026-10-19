from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand


ROLE_PERMISSIONS = {
    "Ventas": [
        "view_customer", "add_customer", "change_customer",
        "view_opportunity", "add_opportunity", "change_opportunity", "transition_opportunity",
        "view_opportunityactivity", "add_opportunityactivity", "change_opportunityactivity", "complete_opportunityactivity",
        "view_quote", "add_quote", "change_quote", "send_quote", "revise_quote",
        "view_quotecostsheet", "add_quotecostsheet", "change_quotecostsheet",
        "view_salesorder", "view_workorder", "view_workorderevidence",
    ],
    "Gerencia": [
        "view_customer", "view_opportunity", "transition_opportunity", "view_opportunityactivity", "change_opportunityactivity", "complete_opportunityactivity", "view_quote", "change_quote", "approve_quote", "cancel_quote", "revise_quote", "view_quotediscountpolicy", "change_quotediscountpolicy", "view_quotediscountapproval", "view_quotecostsheet", "add_quotecostsheet", "change_quotecostsheet",
        "view_salesorder", "view_workorder", "view_workorderevidence", "schedule_workorder", "record_workorder_acceptance", "view_auditevent",
    ],
    "Operaciones": [
        "view_customer", "view_salesorder", "view_workorder",
        "transition_workorder", "schedule_workorder", "log_workorder_hours", "record_workorder_acceptance", "view_workorderevidence", "add_workorderevidence", "view_auditevent",
    ],
    "Técnicos": [
        "view_workorder", "change_workorder", "transition_workorder", "log_workorder_hours",
        "record_workorder_acceptance", "view_workorderevidence", "add_workorderevidence",
    ],
    "Contabilidad": [
        "view_customer", "view_quote", "view_salesorder", "view_workorder", "view_workorderevidence",
    ],
    "Almacén": ["view_customer", "view_quote", "view_salesorder", "view_workorder", "view_workorderevidence"],
    "Compras": [],
}

ACCOUNTING_ROLE_PERMISSIONS = {
    "Gerencia": ["view_account", "view_journal", "view_journalentry", "view_postingconfiguration", "view_bankstatement", "view_accountingperiod", "review_openingbalancebatch"],
    "Contabilidad": [
        "add_account", "change_account", "add_journal", "change_journal",
        "view_account", "view_journal", "view_journalentry", "add_journalentry",
        "prepare_openingbalancebatch",
        "change_journalentry", "post_journalentry", "reverse_journalentry",
        "view_postingconfiguration", "add_postingconfiguration", "change_postingconfiguration",
        "view_bankstatement", "add_bankstatement", "change_bankstatement", "reconcile_bankstatement",
        "view_accountingperiod", "add_accountingperiod", "close_accountingperiod", "reopen_accountingperiod",
    ],
}

BILLING_ROLE_PERMISSIONS = {
    "Ventas": ["view_customerinvoice", "add_customerinvoice", "change_customerinvoice"],
    "Gerencia": ["view_customerinvoice", "view_payment", "view_fiscaldocument"],
    "Contabilidad": ["view_customerinvoice", "add_customerinvoice", "change_customerinvoice", "open_customerinvoice", "view_customercreditnote", "add_customercreditnote", "post_customercreditnote", "reverse_customercreditnote", "view_payment", "add_payment", "change_payment", "post_payment", "reverse_payment", "view_fiscaldocument", "prepare_fiscaldocument", "generate_fiscaldocument_xml", "send_fiscaldocument", "send_customer_copy_fiscaldocument", "query_fiscaldocument", "cancel_fiscaldocument"],
}

INVENTORY_ROLE_PERMISSIONS = {
    "Gerencia": ["view_product", "view_stocklocation", "view_stockbalance", "view_stockmovement", "view_reorderrule", "view_inventorycount", "review_inventorycount"],
    "Ventas": ["view_product"],
    "Operaciones": ["view_product", "view_stocklocation", "view_stockbalance", "view_stockmovement", "issue_stock"],
    "Contabilidad": ["view_product", "view_stocklocation", "view_stockbalance", "view_stockmovement", "view_reorderrule"],
    "Almacén": ["view_product", "add_product", "change_product", "view_stocklocation", "add_stocklocation", "change_stocklocation", "view_stockbalance", "view_stockmovement", "view_reorderrule", "add_reorderrule", "change_reorderrule", "view_inventorycount", "receive_stock", "issue_stock", "adjust_stock", "transfer_stock"],
    "Compras": ["view_product", "view_stocklocation", "view_stockbalance", "view_reorderrule", "add_reorderrule", "change_reorderrule"],
}

PURCHASING_ROLE_PERMISSIONS = {
    "Gerencia": ["view_supplier", "view_supplierproduct", "view_purchaseorder", "view_purchasereceipt", "view_supplierbill", "view_supplierpayment", "view_purchasesourcingrequest", "view_purchaseoffer", "view_purchaseframeworkagreement"],
    "Contabilidad": ["view_supplier", "view_purchaseorder", "view_purchasereceipt", "view_supplierbill", "register_supplierbill", "attach_cfdi_supplierbill", "view_supplierpayment", "add_supplierpayment", "change_supplierpayment", "post_supplierpayment", "reverse_supplierpayment"],
    "Compras": ["view_supplier", "add_supplier", "change_supplier", "view_supplierproduct", "add_supplierproduct", "change_supplierproduct", "view_purchaseorder", "add_purchaseorder", "change_purchaseorder", "confirm_purchaseorder", "cancel_purchaseorder", "view_purchasereceipt", "view_purchasesourcingrequest", "add_purchasesourcingrequest", "view_purchaseoffer", "add_purchaseoffer", "award_purchaseoffer", "send_purchasingsourcingrequest", "view_purchaseframeworkagreement", "add_purchaseframeworkagreement", "change_purchaseframeworkagreement", "activate_purchaseframeworkagreement", "close_purchaseframeworkagreement", "order_purchaseframeworkagreement"],
    "Almacén": ["view_supplier", "view_purchaseorder", "view_purchasereceipt", "receive_purchaseorder"],
}

EXPENSE_ROLE_PERMISSIONS = {
    "Gerencia": ["view_expensecategory", "view_expense", "view_all_expenses", "view_expensereport", "view_all_expensereports", "approve_expensereport"],
    "Ventas": ["view_expensecategory", "view_expense", "add_expense", "change_expense", "add_expensereceipt", "view_expensereceipt", "add_expensereport", "change_expensereport", "submit_expensereport"],
    "Operaciones": ["view_expensecategory", "view_expense", "add_expense", "change_expense", "add_expensereceipt", "view_expensereceipt", "add_expensereport", "change_expensereport", "submit_expensereport"],
    "Contabilidad": ["view_expensecategory", "add_expensecategory", "change_expensecategory", "view_expense", "view_all_expenses", "view_expensereceipt", "view_expensereport", "view_all_expensereports", "approve_expensereport", "post_expensereport", "register_expensereimbursement", "reverse_expensereimbursement"],
}


class Command(BaseCommand):
    help = "Crea o actualiza los grupos iniciales de acceso del ERP."

    def handle(self, *args, **options):
        all_sales_permissions = list(Permission.objects.filter(content_type__app_label="sales"))
        all_accounting_permissions = list(Permission.objects.filter(content_type__app_label="accounting"))
        all_billing_permissions = list(Permission.objects.filter(content_type__app_label="billing"))
        all_inventory_permissions = list(Permission.objects.filter(content_type__app_label="inventory"))
        all_purchasing_permissions = list(Permission.objects.filter(content_type__app_label="purchasing"))
        all_identity_permissions = list(Permission.objects.filter(content_type__app_label="identity"))
        all_support_permissions = list(Permission.objects.filter(content_type__app_label="support"))
        all_repair_permissions = list(Permission.objects.filter(content_type__app_label="repairs"))
        all_expense_permissions = list(Permission.objects.filter(content_type__app_label="expenses"))
        groups = {name: permissions for name, permissions in ROLE_PERMISSIONS.items()}
        groups["Administración"] = [permission.codename for permission in all_sales_permissions]

        for group_name, codenames in groups.items():
            group, _ = Group.objects.get_or_create(name=group_name)
            accounting_codenames = ACCOUNTING_ROLE_PERMISSIONS.get(group_name, [])
            billing_codenames = BILLING_ROLE_PERMISSIONS.get(group_name, [])
            inventory_codenames = INVENTORY_ROLE_PERMISSIONS.get(group_name, [])
            purchasing_codenames = PURCHASING_ROLE_PERMISSIONS.get(group_name, [])
            expense_codenames = EXPENSE_ROLE_PERMISSIONS.get(group_name, [])
            support_codenames = {
                "Ventas": ["view_supportticket", "add_supportticket", "add_supportticketmessage", "publish_supportticketmessage", "send_supportticket_portal_link"],
                "Gerencia": ["view_supportticket", "add_supportticket", "change_supportticket", "transition_supportticket", "assign_supportticket", "add_supportticketmessage", "publish_supportticketmessage", "send_supportticket_portal_link"],
                "Operaciones": ["view_supportticket", "add_supportticket", "change_supportticket", "transition_supportticket", "assign_supportticket", "add_supportticketmessage", "publish_supportticketmessage", "send_supportticket_portal_link"],
            }.get(group_name, [])
            repair_codenames = {
                "Gerencia": ["view_repaircase", "add_repaircase", "change_repaircase", "transition_repaircase"],
                "Operaciones": ["view_repaircase", "add_repaircase", "change_repaircase", "transition_repaircase"],
            }.get(group_name, [])
            identity_codenames = ["view_apisession", "view_all_apisessions", "revoke_apisessions"] if group_name == "Administración" else []
            if group_name == "Administración":
                accounting_codenames = [permission.codename for permission in all_accounting_permissions]
                billing_codenames = [permission.codename for permission in all_billing_permissions]
                inventory_codenames = [permission.codename for permission in all_inventory_permissions]
                purchasing_codenames = [permission.codename for permission in all_purchasing_permissions]
                support_codenames = [permission.codename for permission in all_support_permissions]
                repair_codenames = [permission.codename for permission in all_repair_permissions]
                identity_codenames = [permission.codename for permission in all_identity_permissions]
                expense_codenames = [permission.codename for permission in all_expense_permissions]
            sales_permissions = Permission.objects.filter(content_type__app_label="sales", codename__in=codenames)
            accounting_permissions = Permission.objects.filter(content_type__app_label="accounting", codename__in=accounting_codenames)
            billing_permissions = Permission.objects.filter(content_type__app_label="billing", codename__in=billing_codenames)
            inventory_permissions = Permission.objects.filter(content_type__app_label="inventory", codename__in=inventory_codenames)
            purchasing_permissions = Permission.objects.filter(content_type__app_label="purchasing", codename__in=purchasing_codenames)
            support_permissions = Permission.objects.filter(content_type__app_label="support", codename__in=support_codenames)
            repair_permissions = Permission.objects.filter(content_type__app_label="repairs", codename__in=repair_codenames)
            identity_permissions = Permission.objects.filter(content_type__app_label="identity", codename__in=identity_codenames)
            expense_permissions = Permission.objects.filter(content_type__app_label="expenses", codename__in=expense_codenames)
            permissions = list(sales_permissions) + list(accounting_permissions) + list(billing_permissions) + list(inventory_permissions) + list(purchasing_permissions) + list(support_permissions) + list(repair_permissions) + list(identity_permissions) + list(expense_permissions)
            found_sales = set(sales_permissions.values_list("codename", flat=True))
            found_accounting = set(accounting_permissions.values_list("codename", flat=True))
            found_billing = set(billing_permissions.values_list("codename", flat=True))
            found_inventory = set(inventory_permissions.values_list("codename", flat=True))
            found_purchasing = set(purchasing_permissions.values_list("codename", flat=True))
            found_support = set(support_permissions.values_list("codename", flat=True))
            found_repairs = set(repair_permissions.values_list("codename", flat=True))
            found_identity = set(identity_permissions.values_list("codename", flat=True))
            found_expenses = set(expense_permissions.values_list("codename", flat=True))
            missing = (set(codenames) - found_sales) | (set(accounting_codenames) - found_accounting) | (set(billing_codenames) - found_billing) | (set(inventory_codenames) - found_inventory) | (set(purchasing_codenames) - found_purchasing) | (set(support_codenames) - found_support) | (set(repair_codenames) - found_repairs) | (set(identity_codenames) - found_identity) | (set(expense_codenames) - found_expenses)
            if missing:
                raise RuntimeError(f"Faltan permisos del ERP para el rol {group_name}: {', '.join(sorted(missing))}")
            group.permissions.set(permissions)
            self.stdout.write(f"Rol preparado: {group_name}")
