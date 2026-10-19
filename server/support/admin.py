from django.contrib import admin

from .models import SupportInboundEmailReceipt, SupportSlaPolicy, SupportTicket, SupportTicketEvent, SupportTicketMessage, SupportTicketNotification


@admin.register(SupportSlaPolicy)
class SupportSlaPolicyAdmin(admin.ModelAdmin):
    list_display = ["priority", "first_response_minutes", "resolution_minutes", "updated_at"]
    list_editable = ["first_response_minutes", "resolution_minutes"]
    ordering = ["priority"]


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ["number", "title", "customer", "status", "priority", "assigned_to", "created_at"]
    list_filter = ["status", "priority", "channel"]
    search_fields = ["number", "title", "customer__name"]
    readonly_fields = ["id", "number", "customer", "work_order", "title", "description", "status", "priority", "channel", "assigned_to", "created_by", "created_at", "updated_at", "resolved_at", "closed_at", "portal_link_version"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SupportTicketMessage)
class SupportTicketMessageAdmin(admin.ModelAdmin):
    list_display = ["ticket", "sender_display", "is_public", "created_at"]
    readonly_fields = ["ticket", "author", "sender_name", "sender_email", "is_public", "body", "created_at"]

    @admin.display(description="remitente")
    def sender_display(self, obj):
        if obj.author_id:
            return obj.author.get_full_name() or obj.author.get_username()
        return obj.sender_name or "Cliente"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SupportTicketEvent)
class SupportTicketEventAdmin(admin.ModelAdmin):
    list_display = ["ticket", "action", "from_status", "to_status", "actor_display", "occurred_at"]
    readonly_fields = ["ticket", "action", "from_status", "to_status", "actor", "actor_label", "occurred_at"]

    @admin.display(description="actor")
    def actor_display(self, obj):
        if obj.actor_id:
            return obj.actor.get_full_name() or obj.actor.get_username()
        return obj.actor_label or "Actor externo"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SupportTicketNotification)
class SupportTicketNotificationAdmin(admin.ModelAdmin):
    list_display = ["ticket", "recipient_email", "status", "attempt_count", "next_attempt_at", "sent_at"]
    list_filter = ["status"]
    search_fields = ["ticket__number", "recipient_email"]
    readonly_fields = ["ticket", "message", "recipient", "recipient_email", "status", "attempt_count", "next_attempt_at", "last_attempt_at", "sent_at", "last_error", "created_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SupportInboundEmailReceipt)
class SupportInboundEmailReceiptAdmin(admin.ModelAdmin):
    list_display = ["received_at", "status", "reason_code", "sender_email", "ticket", "mailbox", "uid"]
    list_filter = ["status", "reason_code"]
    search_fields = ["sender_email", "email_message_id", "ticket__number"]
    readonly_fields = ["mailbox", "uidvalidity", "uid", "email_message_id", "sender_email", "ticket", "ticket_message", "status", "reason_code", "received_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
