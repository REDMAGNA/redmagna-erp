from django.contrib import admin

from .models import Product, ReorderRule, StockBalance, StockLocation, StockMovement, StockUnit, StockUnitEvent


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["sku", "name", "kind", "tracking_policy", "unit", "sat_border_8_eligible", "is_active"]
    list_filter = ["kind", "tracking_policy", "sat_border_8_eligible", "is_active"]
    search_fields = ["sku", "name"]


@admin.register(StockLocation)
class StockLocationAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["code", "name"]


@admin.register(ReorderRule)
class ReorderRuleAdmin(admin.ModelAdmin):
    list_display = ["product", "location", "minimum_quantity", "target_quantity", "is_active", "updated_at"]
    list_filter = ["is_active", "location"]
    search_fields = ["product__sku", "product__name", "location__code", "location__name"]


@admin.register(StockBalance)
class StockBalanceAdmin(admin.ModelAdmin):
    list_display = ["product", "location", "quantity", "updated_at"]
    list_filter = ["location"]
    search_fields = ["product__sku", "product__name"]
    readonly_fields = [field.name for field in StockBalance._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ["created_at", "kind", "product", "location", "quantity", "work_order", "created_by"]
    list_filter = ["kind", "location"]
    search_fields = ["product__sku", "reference", "work_order__sales_order__quote__number"]
    readonly_fields = [field.name for field in StockMovement._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StockUnit)
class StockUnitAdmin(admin.ModelAdmin):
    list_display = ["serial_number", "product", "state", "location", "customer", "work_order", "warranty_until", "updated_at"]
    list_filter = ["state", "product"]
    search_fields = ["serial_number", "product__sku", "product__name", "work_order__sales_order__quote__number"]
    readonly_fields = [field.name for field in StockUnit._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StockUnitEvent)
class StockUnitEventAdmin(admin.ModelAdmin):
    list_display = ["created_at", "unit", "movement", "state_before", "state_after", "created_by"]
    readonly_fields = [field.name for field in StockUnitEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
