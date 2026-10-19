import uuid
from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL), ("sales", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="CustomerInvoice",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("number", models.CharField(blank=True, max_length=24, unique=True)),
                ("currency", models.CharField(default="MXN", max_length=3)),
                ("issue_date", models.DateField(default=django.utils.timezone.localdate)),
                ("due_date", models.DateField(blank=True, null=True)),
                ("memo", models.CharField(blank=True, max_length=240)),
                ("state", models.CharField(choices=[("draft", "Borrador"), ("open", "Abierta"), ("partial", "Pago parcial"), ("paid", "Pagada"), ("cancelled", "Cancelada")], db_index=True, default="draft", max_length=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("opened_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_customer_invoices", to=settings.AUTH_USER_MODEL)),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="invoices", to="sales.customer")),
                ("opened_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="opened_customer_invoices", to=settings.AUTH_USER_MODEL)),
                ("sales_order", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="invoices", to="sales.salesorder")),
            ],
            options={"ordering": ["-issue_date", "-number"], "permissions": [("open_customerinvoice", "Puede abrir facturas en cuentas por cobrar")]},
        ),
        migrations.CreateModel(
            name="Payment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("number", models.CharField(blank=True, max_length=24, unique=True)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=16)),
                ("currency", models.CharField(default="MXN", max_length=3)),
                ("method", models.CharField(choices=[("transfer", "Transferencia"), ("cash", "Efectivo"), ("card", "Tarjeta"), ("check", "Cheque"), ("other", "Otro")], max_length=12)),
                ("received_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("reference", models.CharField(blank=True, max_length=120)),
                ("memo", models.CharField(blank=True, max_length=240)),
                ("state", models.CharField(choices=[("draft", "Borrador"), ("posted", "Aplicado")], db_index=True, default="draft", max_length=8)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("posted_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_customer_payments", to=settings.AUTH_USER_MODEL)),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payments", to="sales.customer")),
                ("posted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="posted_customer_payments", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-received_at", "-number"], "permissions": [("post_payment", "Puede aplicar cobros a facturas")]},
        ),
        migrations.CreateModel(
            name="InvoiceLine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("line_number", models.PositiveSmallIntegerField()),
                ("description", models.CharField(max_length=300)),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=12)),
                ("unit_price", models.DecimalField(decimal_places=2, max_digits=14)),
                ("tax_rate", models.DecimalField(decimal_places=2, default=Decimal("16.00"), max_digits=5)),
                ("invoice", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="billing.customerinvoice")),
            ],
            options={"ordering": ["line_number"], "constraints": [models.UniqueConstraint(fields=("invoice", "line_number"), name="billing_invoice_line_number_uniq")]},
        ),
        migrations.CreateModel(
            name="PaymentAllocation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=16)),
                ("invoice", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="allocations", to="billing.customerinvoice")),
                ("payment", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="allocations", to="billing.payment")),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("payment", "invoice"), name="billing_payment_invoice_uniq"), models.CheckConstraint(condition=models.Q(("amount__gt", 0)), name="billing_allocation_positive")]},
        ),
        migrations.CreateModel(
            name="FiscalDocument",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("document_type", models.CharField(choices=[("I", "Ingreso"), ("E", "Egreso"), ("T", "Traslado"), ("P", "Pago")], max_length=1)),
                ("cfdi_version", models.CharField(default="4.0", max_length=8)),
                ("provider_code", models.CharField(max_length=80)),
                ("idempotency_key", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("provider_request_id", models.CharField(blank=True, max_length=120)),
                ("cfdi_uuid", models.UUIDField(blank=True, null=True, unique=True)),
                ("state", models.CharField(choices=[("prepared", "Preparado"), ("submitted", "Enviado al PAC"), ("stamped", "Timbrado"), ("rejected", "Rechazado"), ("cancel_pending", "Cancelación solicitada"), ("cancelled", "Cancelado"), ("cancel_rejected", "Cancelación rechazada")], db_index=True, default="prepared", max_length=16)),
                ("issuer_rfc", models.CharField(blank=True, max_length=13)),
                ("recipient_rfc", models.CharField(max_length=13)),
                ("recipient_name", models.CharField(max_length=250)),
                ("recipient_fiscal_regime", models.CharField(max_length=3)),
                ("recipient_postal_code", models.CharField(max_length=5)),
                ("cfdi_use", models.CharField(max_length=3)),
                ("payment_method", models.CharField(blank=True, max_length=3)),
                ("payment_form", models.CharField(blank=True, max_length=2)),
                ("currency", models.CharField(default="MXN", max_length=3)),
                ("request_payload", models.JSONField(default=dict)),
                ("xml_content", models.TextField(blank=True)),
                ("pdf_storage_key", models.CharField(blank=True, max_length=500)),
                ("stamped_at", models.DateTimeField(blank=True, null=True)),
                ("cancellation_reason", models.CharField(blank=True, choices=[("01", "Error con relación"), ("02", "Error sin relación"), ("03", "Operación no realizada"), ("04", "Operación nominativa relacionada con factura global")], max_length=2)),
                ("replacement_uuid", models.UUIDField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("invoice", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="fiscal_documents", to="billing.customerinvoice")),
                ("payment", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="fiscal_documents", to="billing.payment")),
                ("replaces", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="replacements", to="billing.fiscaldocument")),
            ],
            options={"ordering": ["-created_at"], "constraints": [models.CheckConstraint(condition=(models.Q(("invoice__isnull", False), ("payment__isnull", True)) | models.Q(("invoice__isnull", True), ("payment__isnull", False))), name="billing_fiscal_one_source")]},
        ),
        migrations.CreateModel(
            name="FiscalEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("action", models.CharField(choices=[("submit", "Envío"), ("stamp", "Timbrado"), ("query", "Consulta"), ("cancel", "Cancelación"), ("response", "Respuesta"), ("error", "Error")], max_length=12)),
                ("state_before", models.CharField(blank=True, max_length=16)),
                ("state_after", models.CharField(blank=True, max_length=16)),
                ("provider_request_id", models.CharField(blank=True, max_length=120)),
                ("response_code", models.CharField(blank=True, max_length=80)),
                ("response_payload", models.JSONField(blank=True, default=dict)),
                ("occurred_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("fiscal_document", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="events", to="billing.fiscaldocument")),
            ],
            options={"ordering": ["occurred_at"]},
        ),
    ]
