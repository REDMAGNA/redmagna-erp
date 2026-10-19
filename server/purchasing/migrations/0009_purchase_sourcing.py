import uuid
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0007_serial_unit_reservations"),
        ("purchasing", "0008_supplier_payment_reversal"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PurchaseSourcingRequest",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("number", models.CharField(blank=True, max_length=24, unique=True)),
                ("requested_date", models.DateField(default=django.utils.timezone.localdate)),
                ("desired_date", models.DateField(blank=True, null=True)),
                ("state", models.CharField(choices=[("open", "Solicitando ofertas"), ("awarded", "Oferta seleccionada"), ("cancelled", "Cancelada")], db_index=True, default="open", max_length=12)),
                ("notes", models.CharField(blank=True, max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_sourcing_requests", to=settings.AUTH_USER_MODEL)),
                ("target_location", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_sourcing_requests", to="inventory.stocklocation")),
            ],
            options={"ordering": ["-created_at"], "permissions": [("award_purchaseoffer", "Puede seleccionar una oferta de compra")]},
        ),
        migrations.CreateModel(
            name="PurchaseSourcingLine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("line_number", models.PositiveSmallIntegerField()), ("description", models.CharField(blank=True, max_length=300)),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=14)),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_sourcing_lines", to="inventory.product")),
                ("request", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="lines", to="purchasing.purchasesourcingrequest")),
            ],
            options={"ordering": ["line_number"]},
        ),
        migrations.CreateModel(
            name="PurchaseOffer",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("supplier_reference", models.CharField(blank=True, max_length=120)),
                ("quote_date", models.DateField(default=django.utils.timezone.localdate)),
                ("valid_until", models.DateField(blank=True, null=True)), ("expected_date", models.DateField(blank=True, null=True)),
                ("currency", models.CharField(default="MXN", max_length=3)), ("notes", models.CharField(blank=True, max_length=500)),
                ("state", models.CharField(choices=[("received", "Oferta recibida"), ("selected", "Seleccionada"), ("rejected", "No seleccionada")], db_index=True, default="received", max_length=10)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("received_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="recorded_purchase_offers", to=settings.AUTH_USER_MODEL)),
                ("request", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="offers", to="purchasing.purchasesourcingrequest")),
                ("supplier", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_offers", to="purchasing.supplier")),
            ],
            options={"ordering": ["supplier__name", "created_at"]},
        ),
        migrations.CreateModel(
            name="PurchaseOfferLine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("unit_cost", models.DecimalField(decimal_places=2, max_digits=14)),
                ("offer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="lines", to="purchasing.purchaseoffer")),
                ("sourcing_line", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="offers", to="purchasing.purchasesourcingline")),
            ],
            options={"ordering": ["sourcing_line__line_number"]},
        ),
        migrations.CreateModel(
            name="PurchaseSourcingEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("action", models.CharField(max_length=32)), ("detail", models.CharField(blank=True, max_length=500)),
                ("occurred_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_sourcing_events", to=settings.AUTH_USER_MODEL)),
                ("offer", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="events", to="purchasing.purchaseoffer")),
                ("request", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="events", to="purchasing.purchasesourcingrequest")),
            ],
            options={"ordering": ["occurred_at", "id"]},
        ),
        migrations.AddField(model_name="purchasesourcingrequest", name="selected_offer", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="awarded_requests", to="purchasing.purchaseoffer")),
        migrations.AddField(model_name="purchasesourcingrequest", name="purchase_order", field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="sourcing_request_record", to="purchasing.purchaseorder")),
        migrations.AddField(model_name="purchaseorder", name="sourcing_request", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="purchase_orders", to="purchasing.purchasesourcingrequest")),
        migrations.AddField(model_name="purchaseorder", name="sourcing_offer", field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="purchase_order", to="purchasing.purchaseoffer")),
        migrations.AddConstraint(model_name="purchasesourcingline", constraint=models.UniqueConstraint(fields=("request", "line_number"), name="purch_sourcing_line_number_uniq")),
        migrations.AddConstraint(model_name="purchasesourcingline", constraint=models.CheckConstraint(condition=models.Q(quantity__gt=0), name="purch_sourcing_line_qty_positive")),
        migrations.AddConstraint(model_name="purchaseoffer", constraint=models.UniqueConstraint(fields=("request", "supplier"), name="purch_sourcing_supplier_unique")),
        migrations.AddConstraint(model_name="purchaseoffer", constraint=models.CheckConstraint(condition=models.Q(currency="MXN"), name="purch_offer_currency_mxn")),
        migrations.AddConstraint(model_name="purchaseofferline", constraint=models.UniqueConstraint(fields=("offer", "sourcing_line"), name="purch_offer_line_unique")),
        migrations.AddConstraint(model_name="purchaseofferline", constraint=models.CheckConstraint(condition=models.Q(unit_cost__gte=0), name="purch_offer_cost_nonnegative")),
    ]
