from decimal import Decimal
from calendar import monthrange
from datetime import date

from rest_framework import serializers
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction

from .models import AccountingPeriod, AccountingPeriodEvent, Account, BankStatement, BankStatementLine, Journal, JournalEntry, JournalLine, OpeningBalanceBatch, OpeningBalanceItem, PostingConfiguration


class AccountingPeriodEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = AccountingPeriodEvent
        fields = ["action", "reason", "actor_name", "occurred_at"]

    def get_actor_name(self, obj):
        return obj.actor.get_full_name() or obj.actor.get_username()


class AccountingPeriodSerializer(serializers.ModelSerializer):
    month = serializers.CharField(write_only=True, required=True)
    label = serializers.CharField(read_only=True)
    events = AccountingPeriodEventSerializer(many=True, read_only=True)
    closed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = AccountingPeriod
        fields = ["id", "month", "label", "period_start", "period_end", "state", "created_by", "created_at", "closed_by_name", "closed_at", "reopened_at", "events"]
        read_only_fields = ["id", "label", "period_start", "period_end", "state", "created_by", "created_at", "closed_by_name", "closed_at", "reopened_at", "events"]

    def validate_month(self, value):
        if len(value) != 7 or value[4] != "-":
            raise serializers.ValidationError("Usa el formato AAAA-MM.")
        try:
            year, month = (int(part) for part in value.split("-"))
            date(year, month, 1)
        except (ValueError, TypeError):
            raise serializers.ValidationError("Indica un mes calendario válido.")
        if AccountingPeriod.objects.filter(period_start=date(year, month, 1)).exists():
            raise serializers.ValidationError("Ese periodo ya está registrado.")
        return year, month

    def create(self, validated_data):
        year, month = validated_data["month"]
        return AccountingPeriod.objects.create(
            period_start=date(year, month, 1),
            period_end=date(year, month, monthrange(year, month)[1]),
            created_by=validated_data["created_by"],
        )

    def get_closed_by_name(self, obj):
        if not obj.closed_by_id:
            return ""
        return obj.closed_by.get_full_name() or obj.closed_by.get_username()


class AccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Account
        fields = ["id", "code", "name", "category", "normal_balance", "parent", "allow_reconciliation", "is_active"]


class JournalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Journal
        fields = ["id", "code", "name", "kind", "is_active"]


class OpeningBalanceLineInputSerializer(serializers.Serializer):
    account_code = serializers.CharField(max_length=32, trim_whitespace=True)
    debit = serializers.DecimalField(max_digits=16, decimal_places=2, min_value=Decimal("0.00"))
    credit = serializers.DecimalField(max_digits=16, decimal_places=2, min_value=Decimal("0.00"))
    description = serializers.CharField(max_length=240, required=False, allow_blank=True, default="Saldo inicial")

    def validate(self, attrs):
        if (attrs["debit"] > 0) == (attrs["credit"] > 0):
            raise serializers.ValidationError("Cada cuenta debe tener cargo o abono, pero no ambos ni quedar en cero.")
        return attrs


class OpeningBalanceImportSerializer(serializers.Serializer):
    journal = serializers.PrimaryKeyRelatedField(queryset=Journal.objects.filter(is_active=True, kind=Journal.Kind.GENERAL))
    entry_date = serializers.DateField()
    memo = serializers.CharField(max_length=240, required=False, allow_blank=True, default="Saldos iniciales")
    lines = OpeningBalanceLineInputSerializer(many=True, allow_empty=False, max_length=2000)

    def validate_lines(self, lines):
        if len(lines) < 2:
            raise serializers.ValidationError("Carga al menos dos cuentas para formar la póliza inicial.")
        codes = [line["account_code"].strip() for line in lines]
        if len(codes) != len(set(codes)):
            raise serializers.ValidationError("Cada cuenta debe aparecer una sola vez en la carga.")
        accounts = {account.code: account for account in Account.objects.filter(code__in=codes).prefetch_related("children")}
        missing = [code for code in codes if code not in accounts]
        if missing:
            raise serializers.ValidationError(f"No se encontraron estas cuentas del catálogo: {', '.join(missing[:10])}.")
        for code in codes:
            account = accounts[code]
            if not account.is_active:
                raise serializers.ValidationError(f"La cuenta {code} está inactiva.")
            if account.children.filter(is_active=True).exists():
                raise serializers.ValidationError(f"Usa cuentas de movimiento; {code} tiene subcuentas activas.")
        for line in lines:
            line["account_code"] = line["account_code"].strip()
        debits = sum((line["debit"] for line in lines), Decimal("0.00"))
        credits = sum((line["credit"] for line in lines), Decimal("0.00"))
        if debits <= 0 or debits != credits:
            raise serializers.ValidationError("Los cargos y abonos deben coincidir y ser mayores que cero.")
        return lines


class OpeningBalanceItemSerializer(serializers.ModelSerializer):
    customer_invoice_number = serializers.CharField(source="customer_invoice.number", read_only=True, allow_null=True)
    supplier_bill_number = serializers.CharField(source="supplier_bill.invoice_number", read_only=True, allow_null=True)

    class Meta:
        model = OpeningBalanceItem
        fields = ["id", "direction", "counterparty_rfc", "source_system", "external_number", "issue_date", "due_date", "currency", "original_total", "paid_before_cutoff", "open_balance", "is_reserved", "customer_invoice", "customer_invoice_number", "supplier_bill", "supplier_bill_number"]
        read_only_fields = fields


class OpeningBalanceBatchSerializer(serializers.ModelSerializer):
    receivables_account_code = serializers.CharField(source="receivables_account.code", read_only=True)
    payables_account_code = serializers.CharField(source="payables_account.code", read_only=True)
    created_by_name = serializers.SerializerMethodField()
    reviewed_by_name = serializers.SerializerMethodField()
    items = OpeningBalanceItemSerializer(many=True, read_only=True)

    class Meta:
        model = OpeningBalanceBatch
        fields = ["id", "cutoff_date", "csv_sha256", "receivables_account_code", "payables_account_code", "receivables_total", "payables_total", "item_count", "state", "created_by", "created_by_name", "created_at", "reviewed_by", "reviewed_by_name", "reviewed_at", "review_note", "items"]
        read_only_fields = fields

    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() or obj.created_by.get_username()

    def get_reviewed_by_name(self, obj):
        if not obj.reviewed_by_id:
            return ""
        return obj.reviewed_by.get_full_name() or obj.reviewed_by.get_username()


class OpeningBalanceBatchSummarySerializer(OpeningBalanceBatchSerializer):
    class Meta(OpeningBalanceBatchSerializer.Meta):
        fields = [field for field in OpeningBalanceBatchSerializer.Meta.fields if field != "items"]


class OpeningBalanceBatchPrepareSerializer(serializers.Serializer):
    file = serializers.FileField()
    cutoff_date = serializers.DateField()
    receivables_account = serializers.PrimaryKeyRelatedField(queryset=Account.objects.filter(is_active=True))
    payables_account = serializers.PrimaryKeyRelatedField(queryset=Account.objects.filter(is_active=True))

    def validate(self, attrs):
        if attrs["receivables_account"].pk == attrs["payables_account"].pk:
            raise serializers.ValidationError("Selecciona dos cuentas de control distintas.")
        return attrs


class OpeningBalanceBatchReviewSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=[("publish", "Publicar"), ("reject", "Rechazar")])
    note = serializers.CharField(max_length=500, required=False, allow_blank=True)

    def validate(self, attrs):
        if attrs["decision"] == "reject" and len(attrs.get("note", "").strip()) < 10:
            raise serializers.ValidationError({"note": "Explica el rechazo en al menos 10 caracteres."})
        return attrs


class JournalLineSerializer(serializers.ModelSerializer):
    account_code = serializers.CharField(source="account.code", read_only=True)
    account_name = serializers.CharField(source="account.name", read_only=True)

    class Meta:
        model = JournalLine
        fields = ["id", "line_number", "account", "account_code", "account_name", "description", "debit", "credit"]
        read_only_fields = ["id", "account_code", "account_name"]

    def validate(self, attrs):
        debit = attrs.get("debit", getattr(self.instance, "debit", 0))
        credit = attrs.get("credit", getattr(self.instance, "credit", 0))
        if debit < 0 or credit < 0 or (debit > 0) == (credit > 0):
            raise serializers.ValidationError("Cada línea debe tener un cargo o un abono positivo, nunca ambos.")
        return attrs


class JournalEntrySerializer(serializers.ModelSerializer):
    lines = JournalLineSerializer(many=True)
    journal_code = serializers.CharField(source="journal.code", read_only=True)
    debit_total = serializers.DecimalField(max_digits=20, decimal_places=2, read_only=True)
    credit_total = serializers.DecimalField(max_digits=20, decimal_places=2, read_only=True)
    created_by = serializers.StringRelatedField(read_only=True)
    posted_by = serializers.StringRelatedField(read_only=True)
    has_reversal = serializers.SerializerMethodField()

    class Meta:
        model = JournalEntry
        fields = ["id", "journal", "journal_code", "number", "entry_date", "memo", "origin_type", "origin_id", "reversal_of", "has_reversal", "state", "lines", "debit_total", "credit_total", "created_by", "created_at", "posted_by", "posted_at"]
        read_only_fields = ["id", "number", "reversal_of", "has_reversal", "state", "created_by", "created_at", "posted_by", "posted_at"]

    def get_has_reversal(self, obj):
        return JournalEntry.objects.filter(reversal_of=obj).exists()

    @transaction.atomic
    def create(self, validated_data):
        lines_data = validated_data.pop("lines")
        entry = JournalEntry.objects.create(**validated_data)
        for line_data in lines_data:
            JournalLine.objects.create(entry=entry, **line_data)
        return entry

    @transaction.atomic
    def update(self, instance, validated_data):
        instance = JournalEntry.objects.select_for_update().get(pk=instance.pk)
        if instance.state != JournalEntry.State.DRAFT:
            raise serializers.ValidationError("Solo se pueden editar pólizas en borrador.")
        lines_data = validated_data.pop("lines", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if lines_data is not None:
            instance.lines.all().delete()
            for line_data in lines_data:
                JournalLine.objects.create(entry=instance, **line_data)
        return instance


class BankStatementLineInputSerializer(serializers.Serializer):
    transaction_date = serializers.DateField()
    reference = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    description = serializers.CharField(max_length=240, required=False, allow_blank=True, default="")
    amount = serializers.DecimalField(max_digits=16, decimal_places=2)

    def validate_amount(self, value):
        if value == 0:
            raise serializers.ValidationError("El movimiento debe tener un importe distinto de cero.")
        return value


class BankAdjustmentCreateSerializer(serializers.Serializer):
    line_id = serializers.UUIDField()
    journal = serializers.PrimaryKeyRelatedField(queryset=Journal.objects.filter(is_active=True, kind__in=[Journal.Kind.GENERAL, Journal.Kind.BANK]))
    counterpart_account = serializers.PrimaryKeyRelatedField(queryset=Account.objects.filter(is_active=True))
    memo = serializers.CharField(max_length=240, min_length=5, trim_whitespace=True)


class BankStatementCreateSerializer(serializers.Serializer):
    account = serializers.PrimaryKeyRelatedField(queryset=Account.objects.filter(is_active=True, allow_reconciliation=True, category=Account.Category.ASSET))
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    opening_balance = serializers.DecimalField(max_digits=16, decimal_places=2)
    closing_balance = serializers.DecimalField(max_digits=16, decimal_places=2)
    lines = BankStatementLineInputSerializer(many=True, allow_empty=True)

    def validate(self, attrs):
        if attrs["period_start"] > attrs["period_end"]:
            raise serializers.ValidationError({"period_end": "El final del periodo no puede ser anterior al inicio."})
        total = Decimal("0.00")
        for index, line in enumerate(attrs["lines"], start=1):
            if not attrs["period_start"] <= line["transaction_date"] <= attrs["period_end"]:
                raise serializers.ValidationError({"lines": f"La fecha de la línea {index} está fuera del periodo."})
            total += line["amount"]
        if attrs["opening_balance"] + total != attrs["closing_balance"]:
            raise serializers.ValidationError({"closing_balance": "El saldo inicial más los movimientos debe coincidir exactamente con el saldo final."})
        return attrs


class BankStatementLineSerializer(serializers.ModelSerializer):
    journal_line = serializers.UUIDField(source="journal_line_id", read_only=True, allow_null=True)
    journal_entry_number = serializers.CharField(source="journal_line.entry.number", read_only=True, allow_null=True)
    journal_entry_date = serializers.DateField(source="journal_line.entry.entry_date", read_only=True, allow_null=True)
    journal_entry_memo = serializers.CharField(source="journal_line.entry.memo", read_only=True, allow_null=True)
    adjustment_entry_number = serializers.CharField(source="prepared_entry.number", read_only=True, allow_null=True)
    adjustment_entry_state = serializers.CharField(source="prepared_entry.state", read_only=True, allow_null=True)
    matched_by_name = serializers.SerializerMethodField()

    class Meta:
        model = BankStatementLine
        fields = ["id", "line_number", "transaction_date", "reference", "description", "amount", "journal_line", "journal_entry_number", "journal_entry_date", "journal_entry_memo", "adjustment_entry_number", "adjustment_entry_state", "matched_by_name", "matched_at"]

    def get_matched_by_name(self, obj):
        if not obj.matched_by_id:
            return ""
        return obj.matched_by.get_full_name() or obj.matched_by.get_username()


class BankStatementSerializer(serializers.ModelSerializer):
    account_code = serializers.CharField(source="account.code", read_only=True)
    account_name = serializers.CharField(source="account.name", read_only=True)
    movement_total = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    calculated_closing_balance = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    balance_difference = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    lines = BankStatementLineSerializer(many=True, read_only=True)
    created_by_name = serializers.SerializerMethodField()
    reconciled_by_name = serializers.SerializerMethodField()
    unmatched_line_count = serializers.SerializerMethodField()

    class Meta:
        model = BankStatement
        fields = ["id", "account", "account_code", "account_name", "period_start", "period_end", "opening_balance", "closing_balance", "movement_total", "calculated_closing_balance", "balance_difference", "state", "lines", "unmatched_line_count", "created_by_name", "created_at", "reconciled_by_name", "reconciled_at"]
        read_only_fields = fields

    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() or obj.created_by.get_username()

    def get_reconciled_by_name(self, obj):
        if not obj.reconciled_by_id:
            return ""
        return obj.reconciled_by.get_full_name() or obj.reconciled_by.get_username()

    def get_unmatched_line_count(self, obj):
        return obj.lines.filter(journal_line__isnull=True).count()


class BankCandidateLineSerializer(serializers.ModelSerializer):
    entry_number = serializers.CharField(source="entry.number", read_only=True)
    entry_date = serializers.DateField(source="entry.entry_date", read_only=True)
    entry_memo = serializers.CharField(source="entry.memo", read_only=True)
    journal_code = serializers.CharField(source="entry.journal.code", read_only=True)
    account_code = serializers.CharField(source="account.code", read_only=True)
    signed_amount = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    match_score = serializers.IntegerField(read_only=True)
    match_reasons = serializers.ListField(child=serializers.CharField(), read_only=True)

    class Meta:
        model = JournalLine
        fields = ["id", "entry_number", "entry_date", "entry_memo", "journal_code", "account_code", "description", "debit", "credit", "signed_amount", "match_score", "match_reasons"]


class PostingConfigurationSerializer(serializers.ModelSerializer):
    event_type_label = serializers.CharField(source="get_event_type_display", read_only=True)
    journal_code = serializers.CharField(source="journal.code", read_only=True)
    change_history = serializers.SerializerMethodField()

    class Meta:
        model = PostingConfiguration
        fields = [
            "id", "event_type", "event_type_label", "journal", "journal_code",
            "receivable_account", "revenue_account", "tax_account", "funds_account",
            "payable_account", "purchase_account", "supplier_tax_account", "is_active", "updated_at", "change_history",
        ]
        read_only_fields = ["id", "event_type_label", "journal_code", "updated_at", "change_history"]
        extra_kwargs = {
            "journal": {"queryset": Journal.objects.filter(is_active=True)},
            "receivable_account": {"queryset": Account.objects.filter(is_active=True)},
            "revenue_account": {"queryset": Account.objects.filter(is_active=True)},
            "tax_account": {"queryset": Account.objects.filter(is_active=True)},
            "funds_account": {"queryset": Account.objects.filter(is_active=True)},
            "payable_account": {"queryset": Account.objects.filter(is_active=True)},
            "purchase_account": {"queryset": Account.objects.filter(is_active=True)},
            "supplier_tax_account": {"queryset": Account.objects.filter(is_active=True)},
        }

    def get_change_history(self, obj):
        return [{
            "before": event.before,
            "after": event.after,
            "actor_name": event.actor.get_full_name() or event.actor.get_username(),
            "occurred_at": event.occurred_at,
        } for event in obj.change_history.select_related("actor").all()[:10]]

    def validate(self, attrs):
        candidate = self.instance or PostingConfiguration()
        if self.instance and "event_type" in attrs and attrs["event_type"] != self.instance.event_type:
            raise serializers.ValidationError({"event_type": "El tipo de evento de una regla existente no se puede cambiar."})
        for field, value in attrs.items():
            setattr(candidate, field, value)
        try:
            candidate.full_clean()
        except DjangoValidationError as error:
            if hasattr(error, "message_dict"):
                raise serializers.ValidationError(error.message_dict) from error
            raise serializers.ValidationError(error.messages) from error
        return attrs
