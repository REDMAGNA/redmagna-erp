from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("support", "0008_support_inbound_email_receipt"),
    ]

    operations = [
        migrations.AddField(
            model_name="supportslapolicy",
            name="weekly_schedule",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Calendario local por día: 0=lunes…6=domingo. Ejemplo L-V: {"0":[["09:00","13:00"],["14:00","18:00"]],"1":[["09:00","13:00"],["14:00","18:00"]],"2":[["09:00","13:00"],["14:00","18:00"]],"3":[["09:00","13:00"],["14:00","18:00"]],"4":[["09:00","13:00"],["14:00","18:00"]]}. Vacío conserva minutos corridos.',
            ),
        ),
        migrations.AddField(
            model_name="supportslapolicy",
            name="calendar_timezone",
            field=models.CharField(
                default="America/Mexico_City",
                help_text="Zona IANA para interpretar los horarios, por ejemplo America/Mexico_City.",
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name="supportticket",
            name="sla_paused_working_seconds",
            field=models.PositiveIntegerField(default=0, editable=False),
        ),
        migrations.AddField(
            model_name="supportticket",
            name="sla_weekly_schedule",
            field=models.JSONField(blank=True, default=dict, editable=False),
        ),
        migrations.AddField(
            model_name="supportticket",
            name="sla_calendar_timezone",
            field=models.CharField(default="America/Mexico_City", editable=False, max_length=64),
        ),
    ]
