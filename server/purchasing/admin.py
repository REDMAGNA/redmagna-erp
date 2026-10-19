from django.contrib import admin

from .models import PurchaseFrameworkAgreement, PurchaseFrameworkAgreementLine, PurchaseOffer, PurchaseOfferLine, PurchaseOrder, PurchaseOrderEvent, PurchaseOrderLine, PurchaseReceipt, PurchaseReceiptLine, PurchaseSourcingEvent, PurchaseSourcingLine, PurchaseSourcingRequest, Supplier, SupplierProduct, SupplierProductRevision, SupplierBillCFDI


class PurchaseOrderLineInline(admin.TabularInline):
    model = PurchaseOrderLine
    extra = 0
    readonly_fields = ["received_quantity", "sourcing_line", "framework_line", "award_reason"]


class PurchaseFrameworkAgreementLineInline(admin.TabularInline):
    model = PurchaseFrameworkAgreementLine
    extra = 0


@admin.register(PurchaseFrameworkAgreement)
class PurchaseFrameworkAgreementAdmin(admin.ModelAdmin):
    list_display = ["reference", "supplier", "valid_from", "valid_until", "status"]
    list_filter = ["status", "supplier"]
    search_fields = ["reference", "supplier__name"]
    readonly_fields = ["status", "activated_by", "activated_at", "closed_by", "closed_at", "created_by", "created_at"]
    inlines = [PurchaseFrameworkAgreementLineInline]


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ["number", "supplier", "order_date", "expected_date", "status"]
    list_filter = ["status", "order_date"]
    search_fields = ["number", "supplier__name"]
    readonly_fields = ["number", "status", "confirmed_by", "confirmed_at"]
    inlines = [PurchaseOrderLineInline]


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ["name", "legal_name", "rfc", "email", "is_active"]
    search_fields = ["name", "legal_name", "rfc"]
    list_filter = ["is_active"]


admin.site.register([PurchaseReceipt, PurchaseReceiptLine, PurchaseOrderEvent])


@admin.register(SupplierProduct)
class SupplierProductAdmin(admin.ModelAdmin):
    list_display = ["supplier", "product", "supplier_reference", "unit_cost", "lead_time_days", "last_verified_on", "is_active"]
    search_fields = ["supplier__name", "product__sku", "product__name", "supplier_reference"]
    list_filter = ["is_active", "supplier"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SupplierProductRevision)
class SupplierProductRevisionAdmin(admin.ModelAdmin):
    list_display = ["supplier_product", "revision", "unit_cost", "lead_time_days", "changed_by", "changed_at"]
    list_filter = ["changed_at", "is_active"]
    search_fields = ["supplier_product__supplier__name", "supplier_product__product__sku", "change_reason"]
    readonly_fields = [field.name for field in SupplierProductRevision._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PurchaseSourcingRequest)
class PurchaseSourcingRequestAdmin(admin.ModelAdmin):
    list_display = ["number", "requested_date", "desired_date", "target_location", "state", "created_by"]
    list_filter = ["state", "requested_date"]
    search_fields = ["number", "notes"]
    readonly_fields = [field.name for field in PurchaseSourcingRequest._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register([PurchaseSourcingLine, PurchaseOffer, PurchaseOfferLine, PurchaseSourcingEvent])


@admin.register(SupplierBillCFDI)
class SupplierBillCFDIAdmin(admin.ModelAdmin):
    list_display = ["supplier_bill", "cfdi_uuid", "issuer_rfc", "invoice_date", "total", "xsd_validated_at", "uploaded_by"]
    search_fields = ["supplier_bill__invoice_number", "cfdi_uuid", "issuer_rfc"]
    readonly_fields = [field.name for field in SupplierBillCFDI._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
