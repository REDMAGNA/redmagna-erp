from rest_framework.routers import DefaultRouter

from .views import CustomerContactViewSet, CustomerSiteViewSet, CustomerViewSet, OpportunityActivityViewSet, OpportunityViewSet, QuoteTemplateViewSet, QuoteViewSet, WorkOrderChecklistTemplateViewSet, WorkOrderViewSet

router = DefaultRouter()
router.register("customers", CustomerViewSet)
router.register("customer-contacts", CustomerContactViewSet)
router.register("customer-sites", CustomerSiteViewSet)
router.register("checklist-templates", WorkOrderChecklistTemplateViewSet)
router.register("opportunities", OpportunityViewSet)
router.register("opportunity-activities", OpportunityActivityViewSet)
router.register("quotes", QuoteViewSet)
router.register("quote-templates", QuoteTemplateViewSet)
router.register("work-orders", WorkOrderViewSet)

urlpatterns = router.urls
