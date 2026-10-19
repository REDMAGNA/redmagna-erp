from rest_framework.routers import DefaultRouter

from .views import CustomerCreditNoteViewSet, FiscalDocumentViewSet, InvoiceViewSet, PaymentViewSet

router = DefaultRouter()
router.register("invoices", InvoiceViewSet)
router.register("payments", PaymentViewSet)
router.register("credit-notes", CustomerCreditNoteViewSet)
router.register("fiscal-documents", FiscalDocumentViewSet)
urlpatterns = router.urls
