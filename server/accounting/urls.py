from rest_framework.routers import DefaultRouter
from django.urls import path

from .views import AccountViewSet, AccountingPeriodViewSet, BankStatementViewSet, FinancialStatementsView, GeneralLedgerView, JournalEntryViewSet, JournalViewSet, OpenItemsPreviewView, OpeningBalanceBatchViewSet, PostingConfigurationViewSet, SubledgerReconciliationView, TrialBalanceView

router = DefaultRouter()
router.register("accounts", AccountViewSet)
router.register("periods", AccountingPeriodViewSet)
router.register("journals", JournalViewSet)
router.register("posting-configurations", PostingConfigurationViewSet)
router.register("entries", JournalEntryViewSet)
router.register("opening-balance-batches", OpeningBalanceBatchViewSet)
router.register("bank-statements", BankStatementViewSet)

urlpatterns = [
    path("reports/trial-balance/", TrialBalanceView.as_view(), name="accounting-trial-balance"),
    path("reports/general-ledger/", GeneralLedgerView.as_view(), name="accounting-general-ledger"),
    path("reports/financial-statements/", FinancialStatementsView.as_view(), name="accounting-financial-statements"),
    path("reports/subledger-reconciliation/", SubledgerReconciliationView.as_view(), name="accounting-subledger-reconciliation"),
    path("reports/open-items-preview/", OpenItemsPreviewView.as_view(), name="accounting-open-items-preview"),
] + router.urls
