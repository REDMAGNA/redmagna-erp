from rest_framework.routers import DefaultRouter
from .views import ExpenseCategoryViewSet, ExpensePostingConfigurationViewSet, ExpenseReportViewSet, ExpenseViewSet

router = DefaultRouter()
router.register("categories", ExpenseCategoryViewSet, basename="expense-category")
router.register("items", ExpenseViewSet, basename="expense")
router.register("reports", ExpenseReportViewSet, basename="expense-report")
router.register("posting-configurations", ExpensePostingConfigurationViewSet, basename="expense-posting-configuration")
urlpatterns = router.urls
