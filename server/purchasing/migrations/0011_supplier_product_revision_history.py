import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def create_baseline_revisions(apps, schema_editor):
    SupplierProduct = apps.get_model("purchasing", "SupplierProduct")
    SupplierProductRevision = apps.get_model("purchasing", "SupplierProductRevision")
    rows = []
    for term in SupplierProduct.objects.all().iterator():
        rows.append(SupplierProductRevision(
            supplier_product_id=term.pk,
            revision=1,
            supplier_reference=term.supplier_reference,
            unit_cost=term.unit_cost,
            minimum_order_quantity=term.minimum_order_quantity,
            lead_time_days=term.lead_time_days,
            last_verified_on=term.last_verified_on,
            is_active=term.is_active,
            change_reason="Condición vigente al activar el historial",
        ))
    SupplierProductRevision.objects.bulk_create(rows, batch_size=500)


class Migration(migrations.Migration):
    dependencies = [
        ("purchasing", "0010_supplier_product_catalog"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SupplierProductRevision",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("revision", models.PositiveIntegerField()),
                ("supplier_reference", models.CharField(blank=True, max_length=120)),
                ("unit_cost", models.DecimalField(decimal_places=2, max_digits=14)),
                ("minimum_order_quantity", models.DecimalField(blank=True, decimal_places=3, max_digits=14, null=True)),
                ("lead_time_days", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("last_verified_on", models.DateField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("change_reason", models.CharField(max_length=500)),
                ("changed_at", models.DateTimeField(auto_now_add=True)),
                ("changed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="supplier_product_revisions", to=settings.AUTH_USER_MODEL)),
                ("supplier_product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="history", to="purchasing.supplierproduct")),
            ],
            options={"ordering": ["-revision"]},
        ),
        migrations.AddConstraint(
            model_name="supplierproductrevision",
            constraint=models.UniqueConstraint(fields=("supplier_product", "revision"), name="purch_supplier_product_revision_uniq"),
        ),
        migrations.RunPython(create_baseline_revisions, migrations.RunPython.noop),
    ]
