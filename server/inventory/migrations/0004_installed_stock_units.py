import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0003_serial_tracking"),
        ("sales", "0012_workorder_customer_acceptance"),
    ]

    operations = [
        migrations.AlterField(
            model_name="stockunit",
            name="state",
            field=models.CharField(choices=[("in_stock", "En almacén"), ("assigned", "Entregado a una orden"), ("installed", "Instalado con el cliente"), ("retired", "Retirado del inventario")], db_index=True, default="in_stock", max_length=16),
        ),
        migrations.AddField(
            model_name="stockunit",
            name="customer",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="installed_serial_units", to="sales.customer"),
        ),
        migrations.AddField(
            model_name="stockunit",
            name="installed_at",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="stockunit",
            name="warranty_until",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="stockunitevent",
            name="movement",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="serial_events", to="inventory.stockmovement"),
        ),
        migrations.AddField(
            model_name="stockunitevent",
            name="action",
            field=models.CharField(choices=[("movement", "Movimiento de inventario"), ("installed", "Instalación")], default="movement", max_length=16),
        ),
        migrations.AddField(
            model_name="stockunitevent",
            name="customer",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="serial_events", to="sales.customer"),
        ),
    ]
