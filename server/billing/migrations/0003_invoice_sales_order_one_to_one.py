from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("billing", "0002_mxn_only"), ("sales", "0001_initial")]
    operations = [
        migrations.AlterField(
            model_name="customerinvoice",
            name="sales_order",
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="customer_invoice", to="sales.salesorder"),
        ),
    ]
