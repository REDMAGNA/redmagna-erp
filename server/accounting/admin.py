from django.contrib import admin

from .models import AccountingPeriod, AccountingPeriodEvent, Account, BankStatement, BankStatementLine, Journal, JournalEntry, JournalLine, OpeningBalanceBatch, OpeningBalanceItem, PostingConfiguration, PostingConfigurationEvent
from .services import posting_configuration_snapshot, record_posting_configuration_change


@admin.register(AccountingPeriod)
class AccountingPeriodAdmin(admin.ModelAdmin):
    list_display = ["period_start", "period_end", "state", "closed_by", "closed_at"]
    list_filter = ["state", "period_start"]
    readonly_fields = [field.name for field in AccountingPeriod._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm("accounting.view_accountingperiod")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AccountingPeriodEvent)
class AccountingPeriodEventAdmin(admin.ModelAdmin):
    list_display = ["period", "action", "actor", "occurred_at"]
    readonly_fields = [field.name for field in AccountingPeriodEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm("accounting.view_accountingperiod")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PostingConfiguration)
class PostingConfigurationAdmin(admin.ModelAdmin):
    list_display = ["event_type", "journal", "receivable_account", "payable_account", "purchase_account", "funds_account", "is_active", "updated_at"]
    list_filter = ["event_type", "is_active"]
    readonly_fields = ["updated_at"]

    def save_model(self, request, obj, form, change):
        previous = PostingConfiguration.objects.select_related(
            "journal", "receivable_account", "revenue_account", "tax_account", "funds_account",
            "payable_account", "purchase_account", "supplier_tax_account",
        ).get(pk=obj.pk) if change else None
        before = posting_configuration_snapshot(previous) if previous else None
        super().save_model(request, obj, form, change)
        record_posting_configuration_change(obj, before, request.user)


@admin.register(PostingConfigurationEvent)
class PostingConfigurationEventAdmin(admin.ModelAdmin):
    list_display = ["configuration", "actor", "occurred_at"]
    list_filter = ["occurred_at"]
    readonly_fields = ["configuration", "before", "after", "actor", "occurred_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm("accounting.view_postingconfiguration")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "category", "normal_balance", "is_active"]
    list_filter = ["category", "normal_balance", "is_active"]
    search_fields = ["code", "name"]
    readonly_fields = ["created_at"]

    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(Journal)
class JournalAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "kind", "is_active"]
    list_filter = ["kind", "is_active"]

    def has_delete_permission(self, request, obj=None):
        return False


class JournalLineInline(admin.TabularInline):
    model = JournalLine
    extra = 0

    def has_add_permission(self, request, obj=None):
        return obj is None or obj.state == JournalEntry.State.DRAFT

    def has_change_permission(self, request, obj=None):
        return obj is None or obj.state == JournalEntry.State.DRAFT

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ["number", "entry_date", "journal", "memo", "state", "posted_at"]
    list_filter = ["state", "journal", "entry_date"]
    search_fields = ["number", "memo", "origin_type"]
    inlines = [JournalLineInline]
    readonly_fields = ["number", "state", "created_by", "created_at", "posted_by", "posted_at", "reversal_of"]

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.state == JournalEntry.State.POSTED:
            return False
        return super().has_change_permission(request, obj)


class BankStatementLineInline(admin.TabularInline):
    model = BankStatementLine
    extra = 0
    readonly_fields = ["line_number", "transaction_date", "reference", "description", "amount", "journal_line", "matched_by", "matched_at"]
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(BankStatement)
class BankStatementAdmin(admin.ModelAdmin):
    list_display = ["account", "period_start", "period_end", "opening_balance", "closing_balance", "state", "reconciled_at"]
    list_filter = ["state", "account"]
    readonly_fields = ["state", "created_by", "created_at", "reconciled_by", "reconciled_at"]
    inlines = [BankStatementLineInline]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class OpeningBalanceItemInline(admin.TabularInline):
    model = OpeningBalanceItem
    extra = 0
    can_delete = False
    readonly_fields = [field.name for field in OpeningBalanceItem._meta.fields]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(OpeningBalanceBatch)
class OpeningBalanceBatchAdmin(admin.ModelAdmin):
    list_display = ["cutoff_date", "state", "item_count", "receivables_total", "payables_total", "created_by", "reviewed_by", "created_at"]
    list_filter = ["state", "cutoff_date"]
    search_fields = ["csv_sha256", "created_by__username", "reviewed_by__username"]
    readonly_fields = [field.name for field in OpeningBalanceBatch._meta.fields]
    inlines = [OpeningBalanceItemInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm("accounting.view_journalentry")

    def has_delete_permission(self, request, obj=None):
        return False
