import decimal

import django.db.models.deletion
from django.db import migrations, models


def backfill_quoted_quantity(apps, schema_editor):
    OfferLine = apps.get_model("purchasing", "PurchaseOfferLine")
    for line in OfferLine.objects.select_related("sourcing_line").iterator():
        line.quoted_quantity = line.sourcing_line.quantity
        line.save(update_fields=["quoted_quantity"])


def backfill_order_line_sources(apps, schema_editor):
    Order = apps.get_model("purchasing", "PurchaseOrder")
    for order in Order.objects.filter(sourcing_request__isnull=False).iterator():
        request_lines = {
            line.product_id: line.id
            for line in apps.get_model("purchasing", "PurchaseSourcingLine").objects.filter(request_id=order.sourcing_request_id)
        }
        for order_line in apps.get_model("purchasing", "PurchaseOrderLine").objects.filter(purchase_order_id=order.id):
            source_id = request_lines.get(order_line.product_id)
            if source_id:
                apps.get_model("purchasing", "PurchaseOrderLine").objects.filter(pk=order_line.pk).update(sourcing_line_id=source_id)


class Migration(migrations.Migration):
    dependencies = [
        ("purchasing", "0015_supplierbillcfdi_issuer_seal_verification"),
        ("inventory", "0007_serial_unit_reservations"),
    ]

    operations = [
        migrations.AlterField(
            model_name="purchasesourcingrequest",
            name="state",
            field=models.CharField(choices=[("open", "Solicitando ofertas"), ("partial", "Adjudicación parcial"), ("awarded", "Oferta seleccionada"), ("cancelled", "Cancelada")], db_index=True, default="open", max_length=12),
        ),
        migrations.AlterField(
            model_name="purchaseoffer",
            name="state",
            field=models.CharField(choices=[("received", "Oferta recibida"), ("partial", "Seleccionada parcialmente"), ("selected", "Seleccionada"), ("rejected", "No seleccionada")], db_index=True, default="received", max_length=10),
        ),
        migrations.AddField(
            model_name="purchaseofferline",
            name="quoted_quantity",
            field=models.DecimalField(decimal_places=3, default=decimal.Decimal("0.000"), max_digits=14),
        ),
        migrations.RunPython(backfill_quoted_quantity, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="purchaseorder",
            name="sourcing_offer",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="purchase_orders", to="purchasing.purchaseoffer"),
        ),
        migrations.AddField(
            model_name="purchaseorderline",
            name="sourcing_line",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="awarded_order_lines", to="purchasing.purchasesourcingline"),
        ),
        migrations.RunPython(backfill_order_line_sources, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="purchaseofferline",
            constraint=models.CheckConstraint(condition=models.Q(quoted_quantity__gt=0), name="purch_offer_qty_positive"),
        ),
    ]
