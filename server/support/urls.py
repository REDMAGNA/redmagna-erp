from rest_framework.routers import DefaultRouter
from django.urls import path

from .views import SupportTicketViewSet, support_ticket_portal

router = DefaultRouter()
router.register("tickets", SupportTicketViewSet)

urlpatterns = router.urls + [path("portal/<str:token>/", support_ticket_portal, name="support-ticket-portal")]
