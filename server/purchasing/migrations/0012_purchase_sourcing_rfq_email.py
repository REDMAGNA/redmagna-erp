from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("purchasing", "0011_supplier_product_revision_history"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="purchasesourcingevent",
            name="supplier",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="purchase_sourcing_events", to="purchasing.supplier"),
        ),
        migrations.AddField(
            model_name="purchasesourcingevent",
            name="recipient_email",
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AlterModelOptions(
            name="purchasesourcingrequest",
            options={
                "ordering": ["-created_at"],
                "permissions": [
                    ("award_purchaseoffer", "Puede seleccionar una oferta de compra"),
                    ("send_purchasingsourcingrequest", "Puede enviar solicitudes de cotización a proveedores"),
                ],
            },
        ),
    ]
