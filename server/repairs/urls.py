from rest_framework.routers import DefaultRouter

from .views import RepairCaseViewSet

router = DefaultRouter()
router.register("cases", RepairCaseViewSet, basename="repair-case")

urlpatterns = router.urls
