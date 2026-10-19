from datetime import date

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.views import APIView

from .models import AccountingPeriod, Account, BankStatement, BankStatementLine, Journal, JournalEntry, JournalLine, OpeningBalanceBatch, PostingConfiguration
from .open_items import preview_open_items_csv
from .permissions import AccountPermissions, AccountingPeriodPermissions, BankStatementPermissions, JournalEntryPermissions, JournalPermissions, OpeningBalanceBatchPermissions, PostingConfigurationPermissions
from .reports import financial_statements, general_ledger, subledger_control_reconciliation, trial_balance
from .serializers import AccountingPeriodSerializer, AccountSerializer, BankAdjustmentCreateSerializer, BankCandidateLineSerializer, BankStatementCreateSerializer, BankStatementSerializer, JournalEntrySerializer, JournalSerializer, OpeningBalanceBatchPrepareSerializer, OpeningBalanceBatchReviewSerializer, OpeningBalanceBatchSerializer, OpeningBalanceBatchSummarySerializer, OpeningBalanceImportSerializer, PostingConfigurationSerializer
from .services import auto_match_bank_statement_references, bank_statement_candidates, close_accounting_period, create_bank_statement, import_opening_balances, match_bank_statement_line, post_entry, posting_configuration_snapshot, prepare_bank_statement_adjustment, record_posting_configuration_change, reconcile_bank_statement, reopen_accounting_period, reverse_entry, unmatch_bank_statement_line
from .opening_balance_services import prepare_opening_balance_batch, review_opening_balance_batch


class AccountingPeriodViewSet(viewsets.ModelViewSet):
    queryset = AccountingPeriod.objects.select_related("created_by", "closed_by", "reopened_by").prefetch_related("events__actor")
    serializer_class = AccountingPeriodSerializer
    permission_classes = [AccountingPeriodPermissions]
    http_method_names = ["get", "post", "head", "options"]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def handle_exception(self, exc):
        if isinstance(exc, DjangoValidationError):
            detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            exc = ValidationError(detail)
        return super().handle_exception(exc)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        current = self.get_object()
        period = close_accounting_period(current.pk, request.user, str(request.data.get("reason", "")).strip())
        return Response(self.get_serializer(period).data)

    @action(detail=True, methods=["post"])
    def reopen(self, request, pk=None):
        current = self.get_object()
        period = reopen_accounting_period(current.pk, request.user, str(request.data.get("reason", "")))
        return Response(self.get_serializer(period).data)


class TrialBalanceQuerySerializer(serializers.Serializer):
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False, default=timezone.localdate)

    def validate(self, attrs):
        date_from = attrs.get("date_from")
        date_to = attrs.get("date_to")
        if date_from and date_to and date_from > date_to:
            raise serializers.ValidationError({"date_from": "La fecha inicial no puede ser posterior a la fecha final."})
        return attrs


class GeneralLedgerQuerySerializer(serializers.Serializer):
    account_code = serializers.CharField(max_length=32)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False, default=timezone.localdate)

    def validate(self, attrs):
        date_from = attrs.get("date_from")
        date_to = attrs.get("date_to")
        if date_from and date_to and date_from > date_to:
            raise serializers.ValidationError({"date_from": "La fecha inicial no puede ser posterior a la fecha final."})
        return attrs


class TrialBalanceView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not request.user.has_perm("accounting.view_journalentry"):
            raise PermissionDenied("No tienes permiso para consultar la balanza de comprobación.")
        query = TrialBalanceQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response(trial_balance(**query.validated_data))


class GeneralLedgerView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not request.user.has_perm("accounting.view_journalentry"):
            raise PermissionDenied("No tienes permiso para consultar el libro mayor.")
        query = GeneralLedgerQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        parameters = dict(query.validated_data)
        account_code = parameters.pop("account_code")
        account = Account.objects.filter(code=account_code).first()
        if account is None:
            raise ValidationError({"account_code": "No se encontró una cuenta con ese código."})
        return Response(general_ledger(account, **parameters))


class FinancialStatementsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not request.user.has_perm("accounting.view_journalentry"):
            raise PermissionDenied("No tienes permiso para consultar los estados financieros.")
        query = TrialBalanceQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response(financial_statements(**query.validated_data))


class SubledgerReconciliationQuerySerializer(serializers.Serializer):
    receivables_account_code = serializers.CharField(max_length=32)
    payables_account_code = serializers.CharField(max_length=32)
    as_of = serializers.DateField(required=False, default=timezone.localdate)


class SubledgerReconciliationView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not request.user.has_perm("accounting.view_journalentry"):
            raise PermissionDenied("No tienes permiso para consultar la conciliación de auxiliares contables.")
        query = SubledgerReconciliationQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
        accounts = {
            account.code: account
            for account in Account.objects.filter(code__in=[values["receivables_account_code"], values["payables_account_code"]])
        }
        receivables = accounts.get(values["receivables_account_code"])
        payables = accounts.get(values["payables_account_code"])
        errors = {}
        if receivables is None:
            errors["receivables_account_code"] = "No se encontró la cuenta indicada para CxC."
        if payables is None:
            errors["payables_account_code"] = "No se encontró la cuenta indicada para CxP."
        if errors:
            raise ValidationError(errors)
        try:
            return Response(subledger_control_reconciliation(receivables, payables, values["as_of"]))
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            raise ValidationError(detail) from exc


class OpenItemsPreviewSerializer(serializers.Serializer):
    file = serializers.FileField()
    as_of = serializers.DateField()
    receivables_account_code = serializers.CharField(max_length=32)
    payables_account_code = serializers.CharField(max_length=32)


class OpenItemsPreviewView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        if not request.user.has_perm("accounting.view_journalentry"):
            raise PermissionDenied("No tienes permiso para revisar partidas abiertas de apertura.")
        serializer = OpenItemsPreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        accounts = {
            account.code: account
            for account in Account.objects.filter(code__in=[values["receivables_account_code"], values["payables_account_code"]])
        }
        receivables = accounts.get(values["receivables_account_code"])
        payables = accounts.get(values["payables_account_code"])
        errors = {}
        if receivables is None:
            errors["receivables_account_code"] = "No se encontró la cuenta indicada para CxC."
        if payables is None:
            errors["payables_account_code"] = "No se encontró la cuenta indicada para CxP."
        if errors:
            raise ValidationError(errors)
        try:
            preview = preview_open_items_csv(values["file"], values["as_of"], receivables, payables)
            preview.pop("_csv_sha256", None)
            preview.pop("_validated_items", None)
            return Response(preview)
        except ValueError as exc:
            raise ValidationError({"file": str(exc)}) from exc


class AccountViewSet(viewsets.ModelViewSet):
    queryset = Account.objects.select_related("parent")
    serializer_class = AccountSerializer
    permission_classes = [AccountPermissions]
    search_fields = ["code", "name"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def handle_exception(self, exc):
        if isinstance(exc, DjangoValidationError):
            detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            exc = ValidationError(detail)
        return super().handle_exception(exc)


class JournalViewSet(viewsets.ModelViewSet):
    queryset = Journal.objects.all()
    serializer_class = JournalSerializer
    permission_classes = [JournalPermissions]
    search_fields = ["code", "name"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def handle_exception(self, exc):
        if isinstance(exc, DjangoValidationError):
            detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            exc = ValidationError(detail)
        return super().handle_exception(exc)


class PostingConfigurationViewSet(viewsets.ModelViewSet):
    queryset = PostingConfiguration.objects.select_related(
        "journal", "receivable_account", "revenue_account", "tax_account", "funds_account",
        "payable_account", "purchase_account", "supplier_tax_account",
    )
    serializer_class = PostingConfigurationSerializer
    permission_classes = [PostingConfigurationPermissions]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        return super().get_queryset().prefetch_related("change_history__actor")

    def perform_create(self, serializer):
        with transaction.atomic():
            configuration = serializer.save()
            record_posting_configuration_change(configuration, None, self.request.user)

    def perform_update(self, serializer):
        with transaction.atomic():
            before = posting_configuration_snapshot(serializer.instance)
            configuration = serializer.save()
            record_posting_configuration_change(configuration, before, self.request.user)

    def handle_exception(self, exc):
        if isinstance(exc, DjangoValidationError):
            detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            exc = ValidationError(detail)
        return super().handle_exception(exc)

    def perform_destroy(self, instance):
        raise ValidationError("Las reglas contables se conservan; desactívalas para detener nuevas pólizas.")


class OpeningBalanceBatchViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = OpeningBalanceBatch.objects.select_related(
        "receivables_account", "payables_account", "created_by", "reviewed_by",
    )
    serializer_class = OpeningBalanceBatchSerializer
    permission_classes = [OpeningBalanceBatchPermissions]
    http_method_names = ["get", "post", "head", "options"]
    ordering_fields = ["cutoff_date", "created_at", "state"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == "retrieve":
            queryset = queryset.prefetch_related("items__customer_invoice", "items__supplier_bill")
        return queryset

    def get_serializer_class(self):
        if self.action in ["list", "prepare", "review"]:
            return OpeningBalanceBatchSummarySerializer
        return OpeningBalanceBatchSerializer

    def handle_exception(self, exc):
        if isinstance(exc, DjangoValidationError):
            detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            exc = ValidationError(detail)
        return super().handle_exception(exc)

    @action(detail=False, methods=["post"], parser_classes=[MultiPartParser, FormParser])
    def prepare(self, request):
        serializer = OpeningBalanceBatchPrepareSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            values = dict(serializer.validated_data)
            upload = values.pop("file")
            batch, created = prepare_opening_balance_batch(request.user, upload=upload, **values)
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            raise ValidationError(detail) from exc
        batch = self.get_queryset().get(pk=batch.pk)
        return Response(self.get_serializer(batch).data, status=201 if created else 200)

    @action(detail=True, methods=["post"])
    def review(self, request, pk=None):
        serializer = OpeningBalanceBatchReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            batch, _ = review_opening_balance_batch(pk, request.user, **serializer.validated_data)
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            raise ValidationError(detail) from exc
        batch = self.get_queryset().get(pk=batch.pk)
        return Response(self.get_serializer(batch).data)


class JournalEntryViewSet(viewsets.ModelViewSet):
    queryset = JournalEntry.objects.select_related("journal", "created_by", "posted_by", "reversal_of").prefetch_related(
        Prefetch("lines", queryset=JournalLine.objects.select_related("account"))
    )
    serializer_class = JournalEntrySerializer
    permission_classes = [JournalEntryPermissions]
    search_fields = ["number", "memo", "origin_type"]
    ordering_fields = ["number", "entry_date", "created_at", "state"]
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def handle_exception(self, exc):
        if isinstance(exc, DjangoValidationError):
            detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            exc = ValidationError(detail)
        return super().handle_exception(exc)

    @action(detail=False, methods=["post"], url_path="import-opening-balances")
    def import_opening_balances(self, request):
        serializer = OpeningBalanceImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            values = dict(serializer.validated_data)
            journal = values.pop("journal")
            entry = import_opening_balances(actor=request.user, journal_id=journal.pk, **values)
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            raise ValidationError(detail) from exc
        entry = self.get_queryset().get(pk=entry.pk)
        return Response(self.get_serializer(entry).data, status=201)

    @action(detail=True, methods=["post"])
    def post(self, request, pk=None):
        try:
            entry = post_entry(pk, request.user)
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            raise ValidationError(detail) from exc
        return Response(self.get_serializer(entry).data)

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        try:
            reversal_date = date.fromisoformat(request.data["entry_date"]) if request.data.get("entry_date") else None
            entry = reverse_entry(pk, request.user, reversal_date=reversal_date)
        except (DjangoValidationError, ValueError, KeyError, TypeError) as exc:
            if isinstance(exc, DjangoValidationError):
                detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
                raise ValidationError(detail) from exc
            raise ValidationError({"entry_date": "Usa una fecha en formato AAAA-MM-DD."}) from exc
        return Response(self.get_serializer(entry).data)


class BankStatementViewSet(viewsets.ModelViewSet):
    queryset = BankStatement.objects.select_related("account", "created_by", "reconciled_by").prefetch_related(
        "lines__journal_line__entry__journal", "lines__journal_line__account", "lines__matched_by", "lines__prepared_entry__journal"
    )
    serializer_class = BankStatementSerializer
    permission_classes = [BankStatementPermissions]
    http_method_names = ["get", "post", "head", "options"]
    ordering_fields = ["period_start", "period_end", "state", "account__code"]

    def create(self, request, *args, **kwargs):
        input_serializer = BankStatementCreateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        try:
            statement = create_bank_statement(actor=request.user, **input_serializer.validated_data)
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            raise ValidationError(detail) from exc
        statement = self.get_queryset().get(pk=statement.pk)
        return Response(BankStatementSerializer(statement).data, status=201)

    @action(detail=True, methods=["get"], url_path="candidate-lines")
    def candidate_lines(self, request, pk=None):
        statement = self.get_object()
        line_id = request.query_params.get("line_id")
        if not line_id:
            raise ValidationError({"line_id": "Indica el movimiento del estado de cuenta."})
        line = get_object_or_404(BankStatementLine.objects.select_related("statement", "statement__account"), pk=line_id, statement=statement)
        candidates = bank_statement_candidates(line)
        return Response({"line_id": str(line.id), "candidates": BankCandidateLineSerializer(candidates, many=True).data})

    @action(detail=True, methods=["post"], url_path="auto-match-references")
    def auto_match_references(self, request, pk=None):
        try:
            result = auto_match_bank_statement_references(pk, request.user)
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            raise ValidationError(detail) from exc
        statement = self.get_queryset().get(pk=pk)
        return Response({**result, "statement": BankStatementSerializer(statement).data})

    @action(detail=True, methods=["post"], url_path="match-line")
    def match_line(self, request, pk=None):
        statement = self.get_object()
        line_id = request.data.get("line_id")
        journal_line_id = request.data.get("journal_line")
        if not line_id or not journal_line_id:
            raise ValidationError({"detail": "Indica line_id y journal_line para conciliar."})
        try:
            match_bank_statement_line(statement.id, line_id, journal_line_id, request.user)
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            raise ValidationError(detail) from exc
        statement = self.get_queryset().get(pk=statement.pk)
        return Response(BankStatementSerializer(statement).data)

    @action(detail=True, methods=["post"], url_path="prepare-adjustment")
    def prepare_adjustment(self, request, pk=None):
        statement = self.get_object()
        input_serializer = BankAdjustmentCreateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        try:
            entry, created = prepare_bank_statement_adjustment(
                statement.pk, input_serializer.validated_data["line_id"],
                input_serializer.validated_data["journal"].pk,
                input_serializer.validated_data["counterpart_account"].pk,
                input_serializer.validated_data["memo"], request.user,
            )
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            raise ValidationError(detail) from exc
        statement = self.get_queryset().get(pk=statement.pk)
        return Response({"created": created, "entry": JournalEntrySerializer(entry).data, "statement": BankStatementSerializer(statement).data}, status=201 if created else 200)

    @action(detail=True, methods=["post"], url_path="unmatch-line")
    def unmatch_line(self, request, pk=None):
        statement = self.get_object()
        line_id = request.data.get("line_id")
        if not line_id:
            raise ValidationError({"line_id": "Indica el movimiento del estado de cuenta."})
        try:
            unmatch_bank_statement_line(statement.id, line_id)
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            raise ValidationError(detail) from exc
        statement = self.get_queryset().get(pk=statement.pk)
        return Response(BankStatementSerializer(statement).data)

    @action(detail=True, methods=["post"])
    def reconcile(self, request, pk=None):
        try:
            statement = reconcile_bank_statement(pk, request.user)
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            raise ValidationError(detail) from exc
        statement = self.get_queryset().get(pk=statement.pk)
        return Response(BankStatementSerializer(statement).data)
