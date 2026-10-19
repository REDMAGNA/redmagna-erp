from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("purchasing", "0016_partial_sourcing_awards"),
    ]

    operations = [
        migrations.AddField(
            model_name="purchaseorderline",
            name="award_reason",
            field=models.CharField(blank=True, default="", max_length=300),
            preserve_default=False,
        ),
    ]
