from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers

from accounting.models import Account, Journal
from .models import Expense, ExpenseCategory, ExpensePostingConfiguration, ExpenseReceipt, ExpenseReimbursement, ExpenseReport, ExpenseReportEvent


class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = ["id", "code", "name", "expense_account", "receipt_required", "is_active"]


class ExpenseReceiptSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseReceipt
        fields = ["id", "original_name", "content_type", "file_size", "created_at"]
        read_only_fields = fields


class ExpenseSerializer(serializers.ModelSerializer):
    owner = serializers.PrimaryKeyRelatedField(read_only=True)
    owner_name = serializers.SerializerMethodField()
    category_name = serializers.CharField(source="category.name", read_only=True)
    receipts = ExpenseReceiptSerializer(many=True, read_only=True)

    class Meta:
        model = Expense
        fields = ["id", "report", "owner", "owner_name", "category", "category_name", "description", "merchant", "expense_date", "amount", "currency", "paid_by", "reference", "receipts", "created_at"]
        read_only_fields = ["id", "report", "owner", "owner_name", "category_name", "currency", "receipts", "created_at"]

    def get_owner_name(self, obj):
        return obj.owner.get_full_name() or obj.owner.get_username()

    def validate_category(self, category):
        if not category.is_active:
            raise serializers.ValidationError("La categoría está inactiva.")
        return category

    def validate(self, attrs):
        if self.instance and self.instance.report_id and self.instance.report.state not in [ExpenseReport.State.DRAFT, ExpenseReport.State.REJECTED]:
            raise serializers.ValidationError("Un gasto agregado a un reporte ya no se puede editar.")
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        return Expense.objects.create(owner=self.context["request"].user, **validated_data)


class ExpenseReportEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = ExpenseReportEvent
        fields = ["action", "state_before", "state_after", "detail", "actor_name", "occurred_at"]

    def get_actor_name(self, obj):
        return obj.actor.get_full_name() or obj.actor.get_username()


class ExpenseReimbursementSerializer(serializers.ModelSerializer):
    registered_by_name = serializers.SerializerMethodField()
    reversed_by_name = serializers.SerializerMethodField()
    journal_number = serializers.CharField(source="journal_entry.number", read_only=True, default="")
    journal_state = serializers.CharField(source="journal_entry.state", read_only=True, default="")
    reversal_journal_number = serializers.CharField(source="reversal_journal_entry.number", read_only=True, default="")

    class Meta:
        model = ExpenseReimbursement
        fields = ["id", "number", "report", "amount", "payment_date", "method", "reference", "state", "journal_entry", "journal_number", "journal_state", "reversal_journal_entry", "reversal_journal_number", "registered_by", "registered_by_name", "created_at", "reversed_by", "reversed_by_name", "reversed_at", "reversal_reason"]
        read_only_fields = fields

    def get_registered_by_name(self, obj):
        return obj.registered_by.get_full_name() or obj.registered_by.get_username()

    def get_reversed_by_name(self, obj):
        return (obj.reversed_by.get_full_name() or obj.reversed_by.get_username()) if obj.reversed_by_id else ""


class ExpenseReportSerializer(serializers.ModelSerializer):
    expenses = ExpenseSerializer(many=True, read_only=True)
    reimbursements = ExpenseReimbursementSerializer(many=True, read_only=True)
    expense_ids = serializers.ListField(child=serializers.UUIDField(), write_only=True, required=False)
    total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    reimbursable_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    reimbursed_amount = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    reimbursement_balance = serializers.SerializerMethodField()
    journal_state = serializers.CharField(source="journal_entry.state", read_only=True, default="")
    owner_name = serializers.SerializerMethodField()
    reviewed_by_name = serializers.SerializerMethodField()
    events = ExpenseReportEventSerializer(many=True, read_only=True)
    journal_number = serializers.CharField(source="journal_entry.number", read_only=True, default=None)

    class Meta:
        model = ExpenseReport
        fields = ["id", "number", "owner", "owner_name", "state", "submitted_at", "reviewed_by", "reviewed_by_name", "reviewed_at", "rejection_reason", "journal_entry", "journal_number", "journal_state", "total", "reimbursable_total", "reimbursed_amount", "reimbursement_balance", "reimbursements", "expense_ids", "expenses", "events", "created_at"]
        read_only_fields = ["id", "number", "owner", "owner_name", "state", "submitted_at", "reviewed_by", "reviewed_by_name", "reviewed_at", "rejection_reason", "journal_entry", "journal_number", "journal_state", "total", "reimbursable_total", "reimbursed_amount", "reimbursement_balance", "reimbursements", "expenses", "events", "created_at"]

    def get_owner_name(self, obj):
        return obj.owner.get_full_name() or obj.owner.get_username()

    def get_reviewed_by_name(self, obj):
        return (obj.reviewed_by.get_full_name() or obj.reviewed_by.get_username()) if obj.reviewed_by_id else ""

    def get_reimbursement_balance(self, obj):
        return obj.reimbursable_total - obj.reimbursed_amount

    def create(self, validated_data):
        expense_ids = validated_data.pop("expense_ids", [])
        report = ExpenseReport.objects.create(owner=self.context["request"].user)
        if expense_ids:
            expenses = Expense.objects.filter(id__in=expense_ids, owner=report.owner, report__isnull=True)
            if expenses.count() != len(set(expense_ids)):
                raise serializers.ValidationError({"expense_ids": "Cada gasto debe ser tuyo y estar libre de otro reporte."})
            expenses.update(report=report)
        from .services import record_event
        record_event(report, "created", self.context["request"].user, after=report.state)
        return report

    @transaction.atomic
    def update(self, instance, validated_data):
        if instance.state not in [ExpenseReport.State.DRAFT, ExpenseReport.State.REJECTED]:
            raise serializers.ValidationError("Solo puedes modificar reportes en borrador o rechazados.")
        ids = validated_data.pop("expense_ids", None)
        if ids is not None:
            Expense.objects.filter(report=instance).update(report=None)
            expenses = Expense.objects.filter(id__in=ids, owner=instance.owner, report__isnull=True)
            if expenses.count() != len(set(ids)):
                raise serializers.ValidationError({"expense_ids": "Cada gasto debe ser tuyo y estar libre de otro reporte."})
            expenses.update(report=instance)
        return instance


class ExpenseActionSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)


class ExpenseReimbursementInputSerializer(serializers.Serializer):
    idempotency_key = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    payment_date = serializers.DateField()
    method = serializers.ChoiceField(choices=ExpenseReimbursement.Method.choices)
    reference = serializers.CharField(max_length=120, required=False, allow_blank=True)
    confirm_payment_made = serializers.BooleanField()

    def validate(self, attrs):
        if attrs["method"] in [ExpenseReimbursement.Method.BANK_TRANSFER, ExpenseReimbursement.Method.CHECK] and not attrs.get("reference", "").strip():
            raise serializers.ValidationError({"reference": "La transferencia o cheque requiere referencia bancaria."})
        return attrs


class ExpenseReimbursementReverseSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)
    confirm_payment_returned = serializers.BooleanField()


class ExpenseReceiptUploadSerializer(serializers.Serializer):
    file = serializers.FileField()


class ExpensePostingConfigurationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpensePostingConfiguration
        fields = ["id", "journal", "reimbursement_journal", "employee_payable_account", "company_funds_account", "is_active", "updated_at"]
        read_only_fields = ["id", "updated_at"]

    def validate(self, attrs):
        journal = attrs.get("journal", getattr(self.instance, "journal", None))
        payable = attrs.get("employee_payable_account", getattr(self.instance, "employee_payable_account", None))
        funds = attrs.get("company_funds_account", getattr(self.instance, "company_funds_account", None))
        if not all([journal, payable, funds]):
            raise serializers.ValidationError("Selecciona diario y cuentas contables.")
        if attrs.get("is_active", getattr(self.instance, "is_active", False)) and not attrs.get("reimbursement_journal", getattr(self.instance, "reimbursement_journal", None)):
            raise serializers.ValidationError({"reimbursement_journal": "Selecciona el diario de banco o caja usado al registrar reembolsos."})
        return attrs
