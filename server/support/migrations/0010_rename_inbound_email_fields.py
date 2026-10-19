from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("support", "0009_business_time_sla_calendar"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="supportinboundemailreceipt",
            name="support_inbound_mail_final_state",
        ),
        migrations.RenameField(
            model_name="supportinboundemailreceipt",
            old_name="message_id",
            new_name="email_message_id",
        ),
        migrations.RenameField(
            model_name="supportinboundemailreceipt",
            old_name="message",
            new_name="ticket_message",
        ),
        migrations.AddConstraint(
            model_name="supportinboundemailreceipt",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(status="accepted", ticket__isnull=False, ticket_message__isnull=False, reason_code="")
                    | (models.Q(status__in=["rejected", "ignored"], ticket__isnull=True, ticket_message__isnull=True) & ~models.Q(reason_code=""))
                ),
                name="support_inbound_mail_final_state",
            ),
        ),
    ]
