from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("support", "0004_support_ticket_portal_replies"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="supportticketmessage",
            options={
                "ordering": ["created_at", "id"],
                "permissions": [
                    ("publish_supportticketmessage", "Puede compartir respuestas de soporte con el cliente"),
                ],
            },
        ),
        migrations.RemoveConstraint(
            model_name="supportticketmessage",
            name="support_message_visibility_has_actor",
        ),
        migrations.AddConstraint(
            model_name="supportticketmessage",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(author__isnull=False)
                    | (
                        models.Q(is_public=True, author__isnull=True)
                        & ~models.Q(sender_name="")
                        & ~models.Q(sender_email="")
                    )
                ),
                name="support_message_visibility_has_actor",
            ),
        ),
    ]
