from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("support", "0003_support_ticket_portal"),
    ]

    operations = [
        migrations.AddField(
            model_name="supportticketmessage",
            name="sender_name",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="supportticketmessage",
            name="sender_email",
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name="supportticketmessage",
            name="is_public",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AlterField(
            model_name="supportticketmessage",
            name="author",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="support_ticket_messages", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="supportticketevent",
            name="actor_label",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AlterField(
            model_name="supportticketevent",
            name="actor",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="support_ticket_events", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddConstraint(
            model_name="supportticketmessage",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(is_public=True, author__isnull=True)
                    & ~models.Q(sender_name="")
                    & ~models.Q(sender_email="")
                ) | models.Q(is_public=False, author__isnull=False),
                name="support_message_visibility_has_actor",
            ),
        ),
        migrations.AddConstraint(
            model_name="supportticketevent",
            constraint=models.CheckConstraint(
                condition=models.Q(actor__isnull=False) | ~models.Q(actor_label=""),
                name="support_event_has_actor_label",
            ),
        ),
    ]
