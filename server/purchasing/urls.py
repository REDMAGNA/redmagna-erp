from rest_framework.routers import DefaultRouter

from .views import PurchaseFrameworkAgreementViewSet, PurchaseOrderViewSet, PurchaseReceiptViewSet, PurchaseSourcingRequestViewSet, SupplierBillViewSet, SupplierPaymentViewSet, SupplierProductViewSet, SupplierViewSet

router = DefaultRouter()
router.register("suppliers", SupplierViewSet)
router.register("supplier-products", SupplierProductViewSet)
router.register("orders", PurchaseOrderViewSet)
router.register("framework-agreements", PurchaseFrameworkAgreementViewSet)
router.register("sourcing", PurchaseSourcingRequestViewSet, basename="purchase-sourcing")
router.register("receipts", PurchaseReceiptViewSet)
router.register("supplier-bills", SupplierBillViewSet)
router.register("supplier-payments", SupplierPaymentViewSet)

urlpatterns = router.urls
