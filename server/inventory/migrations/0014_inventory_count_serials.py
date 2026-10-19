import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("inventory", "0013_inventory_counts")]

    operations = [
        migrations.AddField(
            model_name="inventorycountline", name="expected_serials",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="inventorycountline", name="counted_serials",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="inventorycountline", name="adjustment_in_key",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AddField(
            model_name="inventorycountline", name="adjustment_out_key",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AddField(
            model_name="inventorycountline", name="adjustment_in_movement",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="inventory_count_in_lines", to="inventory.stockmovement"),
        ),
        migrations.AddField(
            model_name="inventorycountline", name="adjustment_out_movement",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="inventory_count_out_lines", to="inventory.stockmovement"),
        ),
    ]
