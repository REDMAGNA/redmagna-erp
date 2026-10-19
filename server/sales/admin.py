import uuid

from django.contrib import admin

from .models import AuditEvent, Customer, CustomerContact, Opportunity, OpportunityActivity, OpportunityActivityReminder, PublicLeadNotification, PublicLeadSubmission, Quote, QuoteAcceptance, QuoteDiscountApproval, QuoteDiscountPolicy, QuoteLine, SalesOrder, WorkOrder, WorkOrderCustomerAcceptance, WorkOrderEvidence


@admin.register(QuoteDiscountPolicy)
class QuoteDiscountPolicyAdmin(admin.ModelAdmin):
    list_display = ["enabled", "maximum_discount_percent", "updated_at", "updated_by"]
    readonly_fields = ["updated_by", "updated_at"]
    fieldsets = [(None, {"fields": ["enabled", "maximum_discount_percent", "updated_by", "updated_at"], "description": "Define el porcentaje máximo que puede autorizar Ventas sin revisión adicional. Una cotización que lo supere requiere autorización de Gerencia antes de aceptarse. El porcentaje es una decisión de Redmagna; no se fija automáticamente."})]

    def has_add_permission(self, request):
        return not QuoteDiscountPolicy.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.pk = 1
        previous = QuoteDiscountPolicy.objects.filter(pk=1).first()
        old_value = f"{int(previous.enabled)}:{previous.maximum_discount_percent:.2f}" if previous else "sin configuración"
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
        new_value = f"{int(obj.enabled)}:{obj.maximum_discount_percent:.2f}"
        if old_value != new_value:
            AuditEvent.objects.create(
                entity_type="quote_discount_policy",
                entity_id=uuid.UUID(int=1),
                action="policy_changed",
                from_value=old_value,
                to_value=new_value,
                actor=request.user,
            )


@admin.register(QuoteDiscountApproval)
class QuoteDiscountApprovalAdmin(admin.ModelAdmin):
    list_display = ["quote", "maximum_discount_percent", "threshold_percent", "approved_by", "approved_at"]
    list_filter = ["approved_at"]
    readonly_fields = ["quote", "quote_snapshot_hash", "threshold_percent", "maximum_discount_percent", "approved_by", "approved_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class QuoteLineInline(admin.TabularInline):
    model = QuoteLine
    extra = 0

    def has_add_permission(self, request, obj=None):
        return obj is None or obj.status == Quote.Status.DRAFT

    def has_change_permission(self, request, obj=None):
        return obj is None or obj.status == Quote.Status.DRAFT

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Quote)
class QuoteAdmin(admin.ModelAdmin):
    list_display = ["number", "customer", "title", "status", "issue_date", "created_by"]
    list_filter = ["status", "issue_date"]
    search_fields = ["number", "title", "customer__name", "customer__rfc"]
    inlines = [QuoteLineInline]
    readonly_fields = ["number", "status", "created_by", "created_at", "updated_at"]

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(QuoteAcceptance)
class QuoteAcceptanceAdmin(admin.ModelAdmin):
    list_display = ["quote", "accepted_by_name", "accepted_by_email", "accepted_at"]
    search_fields = ["quote__number", "accepted_by_name", "accepted_by_email"]
    readonly_fields = ["quote", "accepted_by_name", "accepted_by_email", "accepted_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ["name", "rfc", "email", "is_active"]
    search_fields = ["name", "legal_name", "rfc", "email"]

    def delete_model(self, request, obj):
        obj.is_active = False
        obj.save(update_fields=["is_active", "updated_at"])

    def delete_queryset(self, request, queryset):
        queryset.update(is_active=False)


@admin.register(CustomerContact)
class CustomerContactAdmin(admin.ModelAdmin):
    list_display = ["customer", "name", "role", "email", "phone", "is_primary", "is_active"]
    list_filter = ["is_primary", "is_active"]
    search_fields = ["customer__name", "name", "role", "email", "phone"]

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Opportunity)
class OpportunityAdmin(admin.ModelAdmin):
    list_display = ["name", "company_name", "customer", "stage", "source", "utm_campaign", "expected_revenue", "probability", "expected_close_date", "assigned_to"]
    list_filter = ["stage", "source", "utm_source", "utm_medium", "utm_campaign", "expected_close_date"]
    search_fields = ["name", "company_name", "contact_name", "email", "customer__name", "utm_source", "utm_medium", "utm_campaign"]
    readonly_fields = [field.name for field in Opportunity._meta.fields]
    inlines = []

    def get_inline_instances(self, request, obj=None):
        instances = super().get_inline_instances(request, obj)
        if obj and hasattr(obj, "public_submission"):
            instances.append(PublicLeadConsentInline(self.model, self.admin_site))
        return instances

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_staff

    def has_delete_permission(self, request, obj=None):
        return False


class PublicLeadConsentInline(admin.StackedInline):
    model = PublicLeadSubmission
    verbose_name = "Consentimiento de solicitud web"
    verbose_name_plural = "Consentimiento de solicitud web"
    fields = ["consent_at", "created_at"]
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_staff

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PublicLeadNotification)
class PublicLeadNotificationAdmin(admin.ModelAdmin):
    list_display = ["submission", "recipient_email", "status", "attempt_count", "manual_retry_count", "next_attempt_at", "sent_at"]
    list_filter = ["status", "created_at"]
    search_fields = ["recipient_email", "submission__opportunity__company_name", "submission__opportunity__name"]
    readonly_fields = [field.name for field in PublicLeadNotification._meta.fields]
    actions = ["retry_failed_notifications"]

    @admin.action(description="Reintentar avisos fallidos seleccionados")
    def retry_failed_notifications(self, request, queryset):
        requeued = 0
        for notification in queryset:
            requeued += notification.retry_failed()
        self.message_user(request, f"Se programaron {requeued} aviso(s) para reintento.", level="success")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_staff

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OpportunityActivity)
class OpportunityActivityAdmin(admin.ModelAdmin):
    list_display = ["title", "activity_type", "opportunity", "due_at", "status", "assigned_to", "completed_by"]
    list_filter = ["activity_type", "status", "due_at"]
    search_fields = ["title", "opportunity__name", "opportunity__company_name"]
    readonly_fields = [field.name for field in OpportunityActivity._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_staff

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OpportunityActivityReminder)
class OpportunityActivityReminderAdmin(admin.ModelAdmin):
    list_display = ["activity", "recipient", "kind", "due_at", "sent_at"]
    list_filter = ["kind", "sent_at"]
    search_fields = ["activity__title", "activity__opportunity__name", "recipient__username", "recipient__email"]
    readonly_fields = [field.name for field in OpportunityActivityReminder._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_staff

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SalesOrder)
class SalesOrderAdmin(admin.ModelAdmin):
    list_display = ["quote", "confirmation_source", "confirmed_at", "confirmed_by"]
    readonly_fields = ["quote", "confirmation_source", "confirmed_at", "confirmed_by"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WorkOrder)
class WorkOrderAdmin(admin.ModelAdmin):
    list_display = ["title", "status", "sales_order", "assigned_to", "scheduled_start"]
    readonly_fields = [field.name for field in WorkOrder._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WorkOrderEvidence)
class WorkOrderEvidenceAdmin(admin.ModelAdmin):
    list_display = ["created_at", "work_order", "original_name", "file_size", "uploaded_by"]
    readonly_fields = [field.name for field in WorkOrderEvidence._meta.fields]
    search_fields = ["original_name", "description", "work_order__title"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WorkOrderCustomerAcceptance)
class WorkOrderCustomerAcceptanceAdmin(admin.ModelAdmin):
    list_display = ["work_order", "customer_contact_name", "accepted_at", "captured_by"]
    search_fields = ["work_order__title", "customer_contact_name", "customer_contact_email"]
    readonly_fields = [field.name for field in WorkOrderCustomerAcceptance._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ["occurred_at", "entity_type", "entity_id", "action", "actor"]
    readonly_fields = [field.name for field in AuditEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.is_staff

    def has_delete_permission(self, request, obj=None):
        return False
