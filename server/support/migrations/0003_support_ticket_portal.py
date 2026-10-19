from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("support", "0002_ticket_serial_unit"),
    ]

    operations = [
        migrations.AddField(
            model_name="supportticket",
            name="portal_link_version",
            field=models.PositiveIntegerField(default=0, editable=False),
        ),
        migrations.AlterModelOptions(
            name="supportticket",
            options={
                "ordering": ["-updated_at", "-created_at"],
                "permissions": [
                    ("transition_supportticket", "Puede cambiar el estado de tickets de soporte"),
                    ("assign_supportticket", "Puede asignar tickets de soporte"),
                    ("send_supportticket_portal_link", "Puede enviar enlaces de seguimiento de soporte a clientes"),
                ],
            },
        ),
    ]
