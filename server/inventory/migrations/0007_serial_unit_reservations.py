from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("inventory", "0006_stock_reservations")]

    operations = [
        migrations.AlterField(
            model_name="stockunit",
            name="state",
            field=models.CharField(
                choices=[
                    ("in_stock", "En almacén"),
                    ("reserved", "Reservado para orden"),
                    ("assigned", "Entregado a una orden"),
                    ("installed", "Instalado con el cliente"),
                    ("retired", "Retirado del inventario"),
                ],
                db_index=True,
                default="in_stock",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="stockunitevent",
            name="action",
            field=models.CharField(
                choices=[
                    ("movement", "Movimiento de inventario"),
                    ("reserved", "Reservado para orden"),
                    ("released", "Reserva liberada"),
                    ("installed", "Instalación"),
                ],
                default="movement",
                max_length=16,
            ),
        ),
    ]
