from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0010_invoice_line_discount_percent"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(model_name="payment", name="reversed_by", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="reversed_customer_payments", to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name="payment", name="reversed_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="payment", name="reversal_reason", field=models.CharField(blank=True, max_length=500)),
        migrations.AlterField(model_name="payment", name="state", field=models.CharField(choices=[("draft", "Borrador"), ("posted", "Aplicado"), ("reversed", "Revertido")], db_index=True, default="draft", max_length=8)),
        migrations.AlterModelOptions(name="payment", options={"ordering": ["-received_at", "-number"], "permissions": [("post_payment", "Puede aplicar cobros a facturas"), ("reverse_payment", "Puede revertir cobros de clientes con motivo")]}),
    ]
