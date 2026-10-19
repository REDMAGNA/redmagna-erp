import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("sales", "0027_customer_quote_payment_terms")]

    operations = [
        migrations.CreateModel(
            name="CustomerContact",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=160)),
                ("role", models.CharField(blank=True, max_length=120)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("phone", models.CharField(blank=True, max_length=40)),
                ("is_primary", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="contacts", to="sales.customer")),
            ],
            options={"ordering": ["customer__name", "-is_primary", "name"]},
        ),
        migrations.AddConstraint(
            model_name="customercontact",
            constraint=models.UniqueConstraint(condition=models.Q(is_active=True, is_primary=True), fields=("customer",), name="sales_customer_contact_primary_uniq"),
        ),
    ]
