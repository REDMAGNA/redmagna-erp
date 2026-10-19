from django.contrib import admin
from django.utils import timezone
from django.contrib import messages

from .models import CustomerCreditNote, CustomerCreditNoteLine, CustomerInvoice, CustomerInvoiceReminder, FiscalDocument, FiscalEvent, InvoiceLine, Payment, PaymentAllocation


class InvoiceLineInline(admin.TabularInline):
    model = InvoiceLine
    extra = 0


class PaymentAllocationInline(admin.TabularInline):
    model = PaymentAllocation
    extra = 0


class CustomerCreditNoteLineInline(admin.TabularInline):
    model = CustomerCreditNoteLine
    extra = 0


@admin.register(CustomerCreditNote)
class CustomerCreditNoteAdmin(admin.ModelAdmin):
    list_display = ["number", "invoice", "issue_date", "state", "created_by", "posted_by"]
    list_filter = ["state", "issue_date"]
    search_fields = ["number", "invoice__number", "invoice__customer__name"]
    readonly_fields = ["number", "state", "created_by", "created_at", "posted_by", "posted_at"]
    inlines = [CustomerCreditNoteLineInline]

    def save_model(self, request, obj, form, change):
        if not change and not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def has_change_permission(self, request, obj=None):
        if obj and obj.state != CustomerCreditNote.State.DRAFT:
            return False
        return super().has_change_permission(request, obj)


@admin.register(CustomerInvoice)
class CustomerInvoiceAdmin(admin.ModelAdmin):
    list_display = ["number", "customer", "issue_date", "due_date", "state", "currency"]
    list_filter = ["state", "currency"]
    search_fields = ["number", "customer__name", "customer__rfc"]
    readonly_fields = ["number", "state", "created_by", "created_at", "opened_by", "opened_at"]
    inlines = [InvoiceLineInline]

    def has_change_permission(self, request, obj=None):
        if obj and obj.state != CustomerInvoice.State.DRAFT:
            return False
        return super().has_change_permission(request, obj)


@admin.register(CustomerInvoiceReminder)
class CustomerInvoiceReminderAdmin(admin.ModelAdmin):
    list_display = ["invoice", "kind", "status", "recipient_email", "attempt_count", "manual_retry_count", "last_attempt_at", "sent_at"]
    list_filter = ["kind", "status", "created_at"]
    search_fields = ["invoice__number", "invoice__customer__name", "recipient_email"]
    readonly_fields = [field.name for field in CustomerInvoiceReminder._meta.fields]
    actions = ["retry_terminal_reminders"]

    @admin.action(description="Reintentar recordatorios agotados u omitidos seleccionados")
    def retry_terminal_reminders(self, request, queryset):
        selected = queryset.filter(status__in=[
            CustomerInvoiceReminder.Status.FAILED,
            CustomerInvoiceReminder.Status.SKIPPED,
        ])
        count = 0
        for reminder in selected.iterator():
            reminder.status = CustomerInvoiceReminder.Status.PENDING
            reminder.attempt_count = 0
            reminder.manual_retry_count += 1
            reminder.next_attempt_at = timezone.now()
            reminder.last_error = ""
            reminder.manual_retried_by = request.user
            reminder.manual_retried_at = timezone.now()
            reminder.save(update_fields=[
                "status", "attempt_count", "manual_retry_count", "next_attempt_at", "last_error",
                "manual_retried_by", "manual_retried_at",
            ])
            count += 1
        self.message_user(request, f"{count} recordatorio(s) regresaron a la cola.", messages.SUCCESS)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ["number", "customer", "amount", "currency", "method", "received_at", "state"]
    list_filter = ["state", "method", "currency"]
    search_fields = ["number", "reference", "customer__name"]
    readonly_fields = ["number", "state", "created_by", "created_at", "posted_by", "posted_at"]
    inlines = [PaymentAllocationInline]

    def has_change_permission(self, request, obj=None):
        if obj and obj.state != Payment.State.DRAFT:
            return False
        return super().has_change_permission(request, obj)


class FiscalEventInline(admin.TabularInline):
    model = FiscalEvent
    extra = 0
    can_delete = False
    readonly_fields = [field.name for field in FiscalEvent._meta.fields]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(FiscalDocument)
class FiscalDocumentAdmin(admin.ModelAdmin):
    list_display = ["id", "document_type", "provider_code", "cfdi_uuid", "state", "created_at"]
    list_filter = ["state", "document_type", "provider_code"]
    search_fields = ["cfdi_uuid", "recipient_rfc", "provider_request_id"]
    readonly_fields = [field.name for field in FiscalDocument._meta.fields]
    inlines = [FiscalEventInline]

    def has_add_permission(self, request):
        return False
