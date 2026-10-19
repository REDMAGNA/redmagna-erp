from django.contrib import admin

from .models import RepairCase, RepairCaseEvent


@admin.register(RepairCase)
class RepairCaseAdmin(admin.ModelAdmin):
    list_display = ["number", "customer", "serial_unit", "status", "warranty_review", "created_at"]
    list_filter = ["status", "warranty_review"]
    search_fields = ["number", "ticket__number", "customer__name", "serial_unit__serial_number"]
    readonly_fields = [field.name for field in RepairCase._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RepairCaseEvent)
class RepairCaseEventAdmin(admin.ModelAdmin):
    list_display = ["repair_case", "action", "from_status", "to_status", "actor", "occurred_at"]
    readonly_fields = [field.name for field in RepairCaseEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
