from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("support", "0006_support_ticket_notifications"),
    ]

    operations = [
        migrations.CreateModel(
            name="SupportSlaPolicy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("priority", models.CharField(choices=[("low", "Baja"), ("normal", "Normal"), ("high", "Alta"), ("urgent", "Urgente")], max_length=10, unique=True)),
                ("first_response_minutes", models.PositiveIntegerField()),
                ("resolution_minutes", models.PositiveIntegerField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["priority"]},
        ),
        migrations.AddConstraint(
            model_name="supportslapolicy",
            constraint=models.CheckConstraint(condition=models.Q(first_response_minutes__gt=0), name="support_sla_response_gt_zero"),
        ),
        migrations.AddConstraint(
            model_name="supportslapolicy",
            constraint=models.CheckConstraint(condition=models.Q(resolution_minutes__gt=0), name="support_sla_resolution_gt_zero"),
        ),
        migrations.AddField(
            model_name="supportticket",
            name="sla_response_target_minutes",
            field=models.PositiveIntegerField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="supportticket",
            name="sla_resolution_target_minutes",
            field=models.PositiveIntegerField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="supportticket",
            name="first_response_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="supportticket",
            name="sla_paused_since",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="supportticket",
            name="sla_paused_seconds",
            field=models.PositiveIntegerField(default=0, editable=False),
        ),
    ]
