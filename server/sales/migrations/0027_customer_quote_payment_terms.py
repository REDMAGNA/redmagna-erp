from django.core.validators import MaxValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sales", "0026_public_lead_notification_manual_retry")]

    operations = [
        migrations.AddField(
            model_name="customer",
            name="payment_term_days",
            field=models.PositiveSmallIntegerField(blank=True, help_text="Días naturales de crédito sugeridos al crear cotizaciones; vacío significa sin plazo predeterminado.", null=True, validators=[MaxValueValidator(3650)]),
        ),
        migrations.AddField(
            model_name="quote",
            name="payment_term_days",
            field=models.PositiveSmallIntegerField(blank=True, null=True, validators=[MaxValueValidator(3650)]),
        ),
    ]
