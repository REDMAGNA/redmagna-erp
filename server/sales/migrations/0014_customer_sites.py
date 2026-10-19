import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sales", "0013_workorder_service_site")]

    operations = [
        migrations.CreateModel(
            name="CustomerSite",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=160)),
                ("address", models.CharField(max_length=500)),
                ("contact_name", models.CharField(blank=True, max_length=160)),
                ("phone", models.CharField(blank=True, max_length=40)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("notes", models.CharField(blank=True, max_length=500)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sites", to="sales.customer")),
            ],
            options={"ordering": ["customer__name", "name"]},
        ),
        migrations.AddConstraint(
            model_name="customersite",
            constraint=models.UniqueConstraint(fields=("customer", "name"), name="sales_customer_site_name_uniq"),
        ),
        migrations.AddField(
            model_name="workorder",
            name="customer_site",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="work_orders", to="sales.customersite"),
        ),
    ]
