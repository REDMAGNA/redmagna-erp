import django.db.models.deletion
from django.db import migrations, models


def assign_existing_requirements_to_main(apps, schema_editor):
    Requirement = apps.get_model("sales", "WorkOrderMaterialRequirement")
    Location = apps.get_model("inventory", "StockLocation")
    main = Location.objects.filter(code="MAIN").first()
    if main:
        Requirement.objects.filter(supply_location__isnull=True).update(supply_location_id=main.pk)


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0007_serial_unit_reservations"),
        ("sales", "0021_quote_line_discount_percent"),
    ]

    operations = [
        migrations.AddField(
            model_name="workordermaterialrequirement",
            name="supply_location",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="work_order_material_requirements",
                to="inventory.stocklocation",
            ),
        ),
        migrations.RunPython(assign_existing_requirements_to_main, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="workordermaterialrequirement",
            name="supply_location",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="work_order_material_requirements",
                to="inventory.stocklocation",
            ),
        ),
    ]
