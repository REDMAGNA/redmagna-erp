from rest_framework.routers import DefaultRouter

from .views import InventoryCountViewSet, ProductViewSet, ReorderRuleViewSet, StockBalanceViewSet, StockLocationViewSet, StockMovementViewSet, StockReservationViewSet, StockTransferViewSet, StockUnitViewSet

router = DefaultRouter()
router.register("products", ProductViewSet)
router.register("locations", StockLocationViewSet)
router.register("balances", StockBalanceViewSet)
router.register("reorder-rules", ReorderRuleViewSet, basename="reorder-rule")
router.register("movements", StockMovementViewSet)
router.register("transfers", StockTransferViewSet)
router.register("reservations", StockReservationViewSet)
router.register("counts", InventoryCountViewSet, basename="inventory-count")
router.register("units", StockUnitViewSet)
urlpatterns = router.urls
