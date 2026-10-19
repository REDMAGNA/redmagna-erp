import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("accounting", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="PostingConfiguration",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("event_type", models.CharField(choices=[("customer_invoice", "Factura de cliente"), ("customer_payment", "Cobro de cliente")], max_length=24, unique=True)),
                ("is_active", models.BooleanField(default=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("funds_account", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="funds_posting_configurations", to="accounting.account")),
                ("journal", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="posting_configurations", to="accounting.journal")),
                ("receivable_account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="receivable_posting_configurations", to="accounting.account")),
                ("revenue_account", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="revenue_posting_configurations", to="accounting.account")),
                ("tax_account", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="tax_posting_configurations", to="accounting.account")),
            ],
            options={"ordering": ["event_type"], "verbose_name": "Configuración de generación de pólizas", "verbose_name_plural": "Configuraciones de generación de pólizas"},
        ),
    ]
