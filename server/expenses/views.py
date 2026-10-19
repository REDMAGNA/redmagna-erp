from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from .models import Expense, ExpenseCategory, ExpensePostingConfiguration, ExpenseReceipt, ExpenseReimbursement, ExpenseReport
from .permissions import ExpensePermissions
from .serializers import ExpenseActionSerializer, ExpenseCategorySerializer, ExpensePostingConfigurationSerializer, ExpenseReceiptUploadSerializer, ExpenseReportSerializer, ExpenseReimbursementInputSerializer, ExpenseReimbursementReverseSerializer, ExpenseReimbursementSerializer, ExpenseSerializer
from .services import prepare_journal, register_reimbursement, reverse_reimbursement, review_report, submit_report


class ExpenseCategoryPermissions(ExpensePermissions):
    action_permissions = {"list": "expenses.view_expensecategory", "retrieve": "expenses.view_expensecategory", "create": "expenses.add_expensecategory", "update": "expenses.change_expensecategory", "partial_update": "expenses.change_expensecategory"}


class ExpenseCategoryViewSet(viewsets.ModelViewSet):
    queryset = ExpenseCategory.objects.select_related("expense_account")
    serializer_class = ExpenseCategorySerializer
    permission_classes = [ExpenseCategoryPermissions]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action == "list" and self.request.query_params.get("active") == "true":
            return qs.filter(is_active=True)
        return qs


class ExpenseViewSet(viewsets.ModelViewSet):
    queryset = Expense.objects.select_related("owner", "category", "report").prefetch_related("receipts")
    serializer_class = ExpenseSerializer
    permission_classes = [ExpensePermissions]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.has_perm("expenses.view_all_expenses"):
            return qs
        return qs.filter(owner=self.request.user)

    def perform_update(self, serializer):
        if serializer.instance.owner_id != self.request.user.pk:
            raise ValidationError("Solo puedes editar tus gastos sin reporte.")
        serializer.save()

    @action(detail=True, methods=["post"], parser_classes=[MultiPartParser, FormParser], url_path="receipt")
    def upload_receipt(self, request, pk=None):
        expense = self.get_object()
        if expense.owner_id != request.user.pk or (expense.report_id and expense.report.state not in [ExpenseReport.State.DRAFT, ExpenseReport.State.REJECTED]):
            raise ValidationError("Solo puedes adjuntar comprobantes a tus gastos libres o en reportes rechazados.")
        serializer = ExpenseReceiptUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        upload = serializer.validated_data["file"]
        receipt = ExpenseReceipt.objects.create(expense=expense, file=upload, original_name=upload.name, uploaded_by=request.user)
        from .serializers import ExpenseReceiptSerializer
        return Response(ExpenseReceiptSerializer(receipt).data, status=201)

    @action(detail=True, methods=["get"], url_path=r"receipt/(?P<receipt_id>[^/.]+)")
    def receipt(self, request, pk=None, receipt_id=None):
        expense = self.get_object()
        receipt = get_object_or_404(ExpenseReceipt, pk=receipt_id, expense=expense)
        return FileResponse(receipt.file.open("rb"), as_attachment=True, filename=receipt.original_name)


class ExpenseReportViewSet(viewsets.ModelViewSet):
    queryset = ExpenseReport.objects.select_related("owner", "reviewed_by", "journal_entry").prefetch_related(
        "expenses__category", "expenses__receipts", "events__actor",
        "reimbursements__registered_by", "reimbursements__reversed_by",
        "reimbursements__journal_entry", "reimbursements__reversal_journal_entry",
    )
    serializer_class = ExpenseReportSerializer
    permission_classes = [ExpensePermissions]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.has_perm("expenses.view_all_expensereports"):
            return qs
        return qs.filter(owner=self.request.user)

    def perform_update(self, serializer):
        if serializer.instance.owner_id != self.request.user.pk:
            raise ValidationError("Solo puedes editar tus propios reportes.")
        serializer.save()

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        try:
            report = submit_report(pk, request.user)
        except (DjangoValidationError, ExpenseReport.DoesNotExist) as error:
            raise ValidationError(getattr(error, "messages", [str(error)])) from error
        return Response(self.get_serializer(report).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._review(request, pk, True)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._review(request, pk, False)

    def _review(self, request, pk, approve):
        data = ExpenseActionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            report = review_report(pk, request.user, approve, data.validated_data.get("reason", ""))
        except (DjangoValidationError, ExpenseReport.DoesNotExist) as error:
            raise ValidationError(getattr(error, "messages", [str(error)])) from error
        return Response(self.get_serializer(report).data)

    @action(detail=True, methods=["post"], url_path="prepare-journal")
    def prepare_journal(self, request, pk=None):
        try:
            report = prepare_journal(pk, request.user)
        except (DjangoValidationError, ExpenseReport.DoesNotExist) as error:
            raise ValidationError(getattr(error, "messages", [str(error)])) from error
        return Response(self.get_serializer(report).data)

    @action(detail=True, methods=["post"])
    def reimburse(self, request, pk=None):
        data = ExpenseReimbursementInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            reimbursement = register_reimbursement(pk, request.user, **data.validated_data)
        except (DjangoValidationError, ExpenseReport.DoesNotExist) as error:
            raise ValidationError(getattr(error, "messages", [str(error)])) from error
        return Response(ExpenseReimbursementSerializer(reimbursement).data, status=201)

    @action(detail=True, methods=["post"], url_path=r"reimbursements/(?P<reimbursement_id>[^/.]+)/reverse", url_name="reverse-reimbursement")
    def reverse_reimbursement(self, request, pk=None, reimbursement_id=None):
        data = ExpenseReimbursementReverseSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            reimbursement = reverse_reimbursement(pk, reimbursement_id, request.user, **data.validated_data)
        except (DjangoValidationError, ExpenseReport.DoesNotExist, ExpenseReimbursement.DoesNotExist) as error:
            raise ValidationError(getattr(error, "messages", [str(error)])) from error
        return Response(ExpenseReimbursementSerializer(reimbursement).data)


class ExpensePostingConfigurationViewSet(viewsets.ModelViewSet):
    queryset = ExpensePostingConfiguration.objects.select_related("journal", "employee_payable_account", "company_funds_account")
    serializer_class = ExpensePostingConfigurationSerializer
    permission_classes = [ExpensePermissions]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            permission = "accounting.view_postingconfiguration"
        else:
            permission = "accounting.change_postingconfiguration"
        from rest_framework.permissions import BasePermission
        class AccountingConfigPermission(BasePermission):
            def has_permission(inner_self, request, view):
                return bool(request.user and request.user.is_authenticated and request.user.has_perm(permission))
        return [AccountingConfigPermission()]
