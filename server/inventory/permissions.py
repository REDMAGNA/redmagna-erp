from rest_framework.permissions import BasePermission


class InventoryPermissions(BasePermission):
    permission_map = {
        "ProductViewSet": {"list": "view_product", "retrieve": "view_product", "create": "add_product", "import_csv": "add_product", "update": "change_product", "partial_update": "change_product"},
        "StockLocationViewSet": {"list": "view_stocklocation", "retrieve": "view_stocklocation", "create": "add_stocklocation", "partial_update": "change_stocklocation"},
        "StockBalanceViewSet": {"list": "view_stockbalance", "retrieve": "view_stockbalance"},
        "ReorderRuleViewSet": {"list": "view_reorderrule", "retrieve": "view_reorderrule", "forecast": "view_reorderrule", "create": "add_reorderrule", "update": "change_reorderrule", "partial_update": "change_reorderrule"},
        "StockUnitViewSet": {"list": "view_stockbalance", "retrieve": "view_stockbalance", "install": "issue_stock", "reserve": "issue_stock", "release": "issue_stock"},
        "StockMovementViewSet": {
            "list": "view_stockmovement", "retrieve": "view_stockmovement",
            "receive": "receive_stock", "issue": "issue_stock", "return_stock": "issue_stock", "adjust": "adjust_stock",
        },
        "StockTransferViewSet": {"list": "view_stockmovement", "retrieve": "view_stockmovement", "create": "transfer_stock"},
        "StockReservationViewSet": {"list": "view_stockmovement", "retrieve": "view_stockmovement", "create": "issue_stock", "release": "issue_stock"},
        "InventoryCountViewSet": {"list": "view_inventorycount", "retrieve": "view_inventorycount", "create": "adjust_stock", "record_line": "adjust_stock", "submit": "adjust_stock", "apply": "review_inventorycount"},
    }

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        required = self.permission_map.get(view.__class__.__name__, {}).get(getattr(view, "action", ""))
        return bool(required and request.user.has_perm(f"inventory.{required}"))
