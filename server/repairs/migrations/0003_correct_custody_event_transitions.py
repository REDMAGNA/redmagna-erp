from django.db import migrations


def correct_custody_event_transitions(apps, schema_editor):
    RepairCaseEvent = apps.get_model("repairs", "RepairCaseEvent")
    RepairCaseEvent.objects.filter(action="custody_received").update(
        from_status="not_received",
        to_status="in_custody",
    )
    RepairCaseEvent.objects.filter(action="custody_returned").update(
        from_status="in_custody",
        to_status="returned",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("repairs", "0002_repaircase_physical_custody"),
    ]

    operations = [
        migrations.RunPython(correct_custody_event_transitions, migrations.RunPython.noop),
    ]
