import django.db.models.deletion
from django.db import migrations, models


def connect_existing_invoice_lines(apps, schema_editor):
    Invoice = apps.get_model("billing", "CustomerInvoice")
    InvoiceLine = apps.get_model("billing", "InvoiceLine")
    QuoteLine = apps.get_model("sales", "QuoteLine")
    database = schema_editor.connection.alias
    for invoice in Invoice.objects.using(database).filter(sales_order__isnull=False).select_related("sales_order__quote"):
        candidates = list(QuoteLine.objects.using(database).filter(quote_id=invoice.sales_order.quote_id).order_by("id"))
        used = set()
        for line in InvoiceLine.objects.using(database).filter(invoice_id=invoice.pk).order_by("line_number"):
            matches = [item for item in candidates if item.pk not in used
                and item.description == line.description
                and item.catalog_product_id == line.catalog_product_id
                and item.unit_price == line.unit_price
                and item.tax_rate == line.tax_rate
                and line.quantity <= item.quantity]
            if matches:
                line.quote_line_id = matches[0].pk
                line.save(update_fields=["quote_line"])
                used.add(matches[0].pk)


def disconnect_existing_invoice_lines(apps, schema_editor):
    InvoiceLine = apps.get_model("billing", "InvoiceLine")
    InvoiceLine.objects.using(schema_editor.connection.alias).update(quote_line=None)


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0008_fiscal_cancellation_permission"),
        ("sales", "0012_workorder_customer_acceptance"),
    ]

    operations = [
        migrations.AddField(
            model_name="invoiceline",
            name="quote_line",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="invoice_lines", to="sales.quoteline"),
        ),
        migrations.RunPython(connect_existing_invoice_lines, disconnect_existing_invoice_lines),
        migrations.AlterField(
            model_name="customerinvoice",
            name="sales_order",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="customer_invoices", to="sales.salesorder"),
        ),
    ]
