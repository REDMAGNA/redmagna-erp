from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("purchasing", "0014_alter_supplierbill_invoice_number"),
    ]

    operations = [
        migrations.AddField(
            model_name="supplierbillcfdi",
            name="issuer_seal_verified",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="supplierbillcfdi",
            name="issuer_seal_verified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
