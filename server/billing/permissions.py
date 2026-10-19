from rest_framework.permissions import BasePermission


class BillingPermissions(BasePermission):
    actions = {
        "InvoiceViewSet": {"list": "view_customerinvoice", "retrieve": "view_customerinvoice", "receivables_aging": "view_customerinvoice", "customer_statement": "view_customerinvoice", "create": "add_customerinvoice", "update": "change_customerinvoice", "partial_update": "change_customerinvoice", "open": "open_customerinvoice", "prepare_cfdi": "prepare_fiscaldocument"},
        "PaymentViewSet": {"list": "view_payment", "retrieve": "view_payment", "create": "add_payment", "update": "change_payment", "partial_update": "change_payment", "post": "post_payment", "reverse": "reverse_payment", "prepare_payment_cfdi": "prepare_fiscaldocument"},
        "CustomerCreditNoteViewSet": {"list": "view_customercreditnote", "retrieve": "view_customercreditnote", "create": "add_customercreditnote", "update": "change_customercreditnote", "partial_update": "change_customercreditnote", "post": "post_customercreditnote", "reverse": "reverse_customercreditnote", "prepare_cfdi": "prepare_fiscaldocument"},
        "FiscalDocumentViewSet": {"list": "view_fiscaldocument", "retrieve": "view_fiscaldocument", "issued_register": "view_fiscaldocument", "download_pdf": "view_fiscaldocument", "query": "query_fiscaldocument", "generate_xml": "generate_fiscaldocument_xml", "send": "send_fiscaldocument", "send_customer_copy": "send_customer_copy_fiscaldocument", "cancel": "cancel_fiscaldocument"},
    }

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        codename = self.actions.get(view.__class__.__name__, {}).get(getattr(view, "action", ""))
        return bool(codename and request.user.has_perm(f"billing.{codename}"))
