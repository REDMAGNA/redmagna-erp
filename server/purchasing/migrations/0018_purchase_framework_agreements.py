import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("purchasing", "0017_purchaseorderline_award_reason"),
        ("inventory", "0010_product_sat_border_8_review"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PurchaseFrameworkAgreement",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("reference", models.CharField(max_length=80)),
                ("valid_from", models.DateField()),
                ("valid_until", models.DateField()),
                ("status", models.CharField(choices=[("draft", "Borrador"), ("active", "Vigente"), ("closed", "Cerrado")], db_index=True, default="draft", max_length=12)),
                ("notes", models.TextField(blank=True)),
                ("activated_at", models.DateTimeField(blank=True, null=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("activated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="activated_purchase_framework_agreements", to=settings.AUTH_USER_MODEL)),
                ("closed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="closed_purchase_framework_agreements", to=settings.AUTH_USER_MODEL)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_purchase_framework_agreements", to=settings.AUTH_USER_MODEL)),
                ("supplier", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="framework_agreements", to="purchasing.supplier")),
            ],
            options={"ordering": ["-created_at"], "permissions": [("activate_purchaseframeworkagreement", "Puede activar acuerdos marco de compra"), ("close_purchaseframeworkagreement", "Puede cerrar acuerdos marco de compra"), ("order_purchaseframeworkagreement", "Puede generar órdenes desde acuerdos marco")]},
        ),
        migrations.CreateModel(
            name="PurchaseFrameworkAgreementLine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("line_number", models.PositiveSmallIntegerField()),
                ("description", models.CharField(blank=True, max_length=300)),
                ("unit_cost", models.DecimalField(decimal_places=2, max_digits=14)),
                ("quantity_limit", models.DecimalField(blank=True, decimal_places=3, max_digits=14, null=True)),
                ("agreement", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="lines", to="purchasing.purchaseframeworkagreement")),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_framework_lines", to="inventory.product")),
            ],
            options={"ordering": ["line_number"]},
        ),
        migrations.AddField(model_name="purchaseorder", name="framework_agreement", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="purchase_orders", to="purchasing.purchaseframeworkagreement")),
        migrations.AddField(model_name="purchaseorderline", name="framework_line", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="purchase_order_lines", to="purchasing.purchaseframeworkagreementline")),
        migrations.AddConstraint(model_name="purchaseframeworkagreement", constraint=models.UniqueConstraint(fields=("supplier", "reference"), name="purch_framework_supplier_ref_uniq")),
        migrations.AddConstraint(model_name="purchaseframeworkagreementline", constraint=models.UniqueConstraint(fields=("agreement", "line_number"), name="purch_framework_line_no_uniq")),
        migrations.AddConstraint(model_name="purchaseframeworkagreementline", constraint=models.UniqueConstraint(fields=("agreement", "product"), name="purch_framework_product_uniq")),
        migrations.AddConstraint(model_name="purchaseframeworkagreementline", constraint=models.CheckConstraint(condition=models.Q(("unit_cost__gte", 0)), name="purch_framework_cost_nonnegative")),
        migrations.AddConstraint(model_name="purchaseframeworkagreementline", constraint=models.CheckConstraint(condition=models.Q(("quantity_limit__isnull", True), ("quantity_limit__gt", 0), _connector="OR"), name="purch_framework_limit_positive")),
    ]
