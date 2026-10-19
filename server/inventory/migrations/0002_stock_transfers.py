import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("inventory", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="StockTransfer",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("idempotency_key", models.UUIDField(unique=True)),
                ("reference", models.CharField(blank=True, max_length=120)),
                ("note", models.CharField(blank=True, max_length=240)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="redmagna_stock_transfers", to=settings.AUTH_USER_MODEL)),
                ("destination_location", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="incoming_transfers", to="inventory.stocklocation")),
                ("source_location", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="outgoing_transfers", to="inventory.stocklocation")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="stocktransfer",
            constraint=models.CheckConstraint(condition=~models.Q(source_location=models.F("destination_location")), name="inventory_transfer_distinct_locations"),
        ),
        migrations.CreateModel(
            name="StockTransferLine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=14)),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="transfer_lines", to="inventory.product")),
                ("transfer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="lines", to="inventory.stocktransfer")),
            ],
        ),
        migrations.AddConstraint(
            model_name="stocktransferline",
            constraint=models.CheckConstraint(condition=models.Q(quantity__gt=0), name="inventory_transfer_line_positive"),
        ),
        migrations.AddField(
            model_name="stockmovement",
            name="counterpart_location",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="counterpart_movements", to="inventory.stocklocation"),
        ),
        migrations.AddField(
            model_name="stockmovement",
            name="transfer_line",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="movements", to="inventory.stocktransferline"),
        ),
        migrations.AlterField(
            model_name="stockmovement",
            name="kind",
            field=models.CharField(choices=[("receipt", "Entrada"), ("issue", "Salida a trabajo"), ("return", "Devolución de trabajo"), ("adjustment_in", "Ajuste positivo"), ("adjustment_out", "Ajuste negativo"), ("transfer_in", "Traspaso recibido"), ("transfer_out", "Traspaso enviado")], db_index=True, max_length=16),
        ),
        migrations.AlterModelOptions(
            name="stockmovement",
            options={
                "ordering": ["-created_at"],
                "permissions": [
                    ("receive_stock", "Puede registrar entradas de inventario"),
                    ("issue_stock", "Puede entregar materiales a órdenes de trabajo"),
                    ("adjust_stock", "Puede realizar ajustes de inventario"),
                    ("transfer_stock", "Puede realizar traspasos entre ubicaciones"),
                ],
            },
        ),
    ]
