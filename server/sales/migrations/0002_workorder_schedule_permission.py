from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("sales", "0001_initial")]

    operations = [
        migrations.AlterModelOptions(
            name="workorder",
            options={
                "permissions": [
                    ("transition_workorder", "Puede cambiar el estado de órdenes de trabajo"),
                    ("schedule_workorder", "Puede programar y asignar órdenes de trabajo"),
                ]
            },
        ),
    ]
