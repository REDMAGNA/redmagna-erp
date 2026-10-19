from django.contrib import admin

from .models import Expense, ExpenseCategory, ExpensePostingConfiguration, ExpenseReceipt, ExpenseReimbursement, ExpenseReport, ExpenseReportEvent


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "expense_account", "receipt_required", "is_active"]
    list_filter = ["is_active", "receipt_required"]
    search_fields = ["code", "name"]


class ExpenseInline(admin.TabularInline):
    model = Expense
    extra = 0
    can_delete = False
    readonly_fields = ["owner", "category", "description", "merchant", "expense_date", "amount", "paid_by", "reference"]


@admin.register(ExpenseReport)
class ExpenseReportAdmin(admin.ModelAdmin):
    list_display = ["number", "owner", "state", "submitted_at", "reviewed_by", "created_at"]
    list_filter = ["state", "created_at"]
    search_fields = ["number", "owner__username", "owner__first_name", "owner__last_name"]
    readonly_fields = ["number", "owner", "state", "submitted_at", "reviewed_by", "reviewed_at", "rejection_reason", "journal_entry"]
    inlines = [ExpenseInline]


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ["expense_date", "description", "owner", "category", "amount", "paid_by", "report"]
    list_filter = ["paid_by", "category", "expense_date"]
    search_fields = ["description", "merchant", "owner__username"]
    readonly_fields = ["owner", "expense_account", "report"]


@admin.register(ExpenseReimbursement)
class ExpenseReimbursementAdmin(admin.ModelAdmin):
    list_display = ["number", "report", "amount", "payment_date", "method", "state", "journal_entry"]
    list_filter = ["state", "method", "payment_date"]
    search_fields = ["number", "report__number", "reference"]
    readonly_fields = [field.name for field in ExpenseReimbursement._meta.fields]


admin.site.register([ExpenseReceipt, ExpenseReportEvent, ExpensePostingConfiguration])
