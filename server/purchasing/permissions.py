from rest_framework.permissions import BasePermission


class ActionPermissions(BasePermission):
    permission_map = {}

    def has_permission(self, request, view):
        required = self.permission_map.get(getattr(view, "action", ""))
        return bool(request.user and request.user.is_authenticated and required and request.user.has_perms(required))


class SupplierPermissions(ActionPermissions):
    permission_map = {
        "list": ["purchasing.view_supplier"], "retrieve": ["purchasing.view_supplier"],
        "import_csv": ["purchasing.view_supplier", "purchasing.add_supplier"],
        "create": ["purchasing.add_supplier"], "update": ["purchasing.change_supplier"],
        "partial_update": ["purchasing.change_supplier"], "destroy": ["purchasing.delete_supplier"],
    }


class SupplierProductPermissions(ActionPermissions):
    permission_map = {
        "list": ["purchasing.view_supplierproduct"], "retrieve": ["purchasing.view_supplierproduct"],
        "create": ["purchasing.add_supplierproduct"], "update": ["purchasing.change_supplierproduct"],
        "partial_update": ["purchasing.change_supplierproduct"], "destroy": ["purchasing.change_supplierproduct"],
    }


class PurchaseOrderPermissions(ActionPermissions):
    permission_map = {
        "list": ["purchasing.view_purchaseorder"], "retrieve": ["purchasing.view_purchaseorder"],
        "create": ["purchasing.add_purchaseorder"], "update": ["purchasing.change_purchaseorder"],
        "partial_update": ["purchasing.change_purchaseorder"], "confirm": ["purchasing.confirm_purchaseorder"],
        "cancel": ["purchasing.cancel_purchaseorder"], "receive": ["purchasing.receive_purchaseorder"],
        "register_bill": ["purchasing.register_supplierbill"],
    }


class PurchaseFrameworkAgreementPermissions(ActionPermissions):
    permission_map = {
        "list": ["purchasing.view_purchaseframeworkagreement"],
        "retrieve": ["purchasing.view_purchaseframeworkagreement"],
        "create": ["purchasing.add_purchaseframeworkagreement"],
        "update": ["purchasing.change_purchaseframeworkagreement"],
        "partial_update": ["purchasing.change_purchaseframeworkagreement"],
        "activate": ["purchasing.activate_purchaseframeworkagreement"],
        "close": ["purchasing.close_purchaseframeworkagreement"],
        "create_order": ["purchasing.order_purchaseframeworkagreement"],
    }


class PurchaseSourcingPermissions(ActionPermissions):
    permission_map = {
        "list": ["purchasing.view_purchasesourcingrequest"],
        "retrieve": ["purchasing.view_purchasesourcingrequest"],
        "create": ["purchasing.add_purchasesourcingrequest"],
        "offers": ["purchasing.view_purchasesourcingrequest"],
        "award": ["purchasing.award_purchaseoffer"],
        "award_lines": ["purchasing.award_purchaseoffer"],
        "send_rfq": ["purchasing.send_purchasingsourcingrequest"],
    }

    def has_permission(self, request, view):
        if getattr(view, "action", "") == "offers" and request.method == "POST":
            required = ["purchasing.add_purchaseoffer"]
        else:
            required = self.permission_map.get(getattr(view, "action", ""), [])
        return bool(request.user and request.user.is_authenticated and required and request.user.has_perms(required))


class PurchaseReceiptPermissions(ActionPermissions):
    permission_map = {"list": ["purchasing.view_purchasereceipt"], "retrieve": ["purchasing.view_purchasereceipt"]}


class SupplierBillPermissions(ActionPermissions):
    permission_map = {
        "list": ["purchasing.view_supplierbill"],
        "retrieve": ["purchasing.view_supplierbill"],
        "payables_aging": ["purchasing.view_supplierbill"],
        "supplier_statement": ["purchasing.view_supplierbill"],
        "cfdi_register": ["purchasing.view_supplierbill"],
        "attach_cfdi": ["purchasing.attach_cfdi_supplierbill"],
        "download_cfdi_xml": ["purchasing.view_supplierbill"],
    }


class SupplierPaymentPermissions(ActionPermissions):
    permission_map = {
        "list": ["purchasing.view_supplierpayment"], "retrieve": ["purchasing.view_supplierpayment"],
        "create": ["purchasing.add_supplierpayment"], "update": ["purchasing.change_supplierpayment"],
        "partial_update": ["purchasing.change_supplierpayment"], "post": ["purchasing.post_supplierpayment"],
        "reverse": ["purchasing.reverse_supplierpayment"],
    }
