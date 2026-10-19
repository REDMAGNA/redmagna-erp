import decimal
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0005_quote_revisions"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Opportunity",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=240)),
                ("company_name", models.CharField(blank=True, max_length=200)),
                ("contact_name", models.CharField(blank=True, max_length=160)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("phone", models.CharField(blank=True, max_length=40)),
                ("stage", models.CharField(choices=[("new", "Nueva"), ("qualified", "Calificada"), ("proposal", "Cotización enviada"), ("won", "Ganada"), ("lost", "Perdida")], db_index=True, default="new", max_length=16)),
                ("expected_revenue", models.DecimalField(decimal_places=2, default=decimal.Decimal("0.00"), max_digits=14)),
                ("probability", models.PositiveSmallIntegerField(default=10)),
                ("expected_close_date", models.DateField(blank=True, null=True)),
                ("source", models.CharField(blank=True, max_length=120)),
                ("description", models.TextField(blank=True)),
                ("lost_reason", models.CharField(blank=True, max_length=120)),
                ("closing_note", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("assigned_to", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="redmagna_opportunities", to=settings.AUTH_USER_MODEL)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_redmagna_opportunities", to=settings.AUTH_USER_MODEL)),
                ("customer", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="opportunities", to="sales.customer")),
            ],
            options={
                "ordering": ["-updated_at"],
                "permissions": [("transition_opportunity", "Puede cambiar etapa y cerrar oportunidades")],
            },
        ),
        migrations.AddConstraint(
            model_name="opportunity",
            constraint=models.CheckConstraint(condition=models.Q(("probability__gte", 0), ("probability__lte", 100)), name="sales_opportunity_probability_valid"),
        ),
        migrations.AddConstraint(
            model_name="opportunity",
            constraint=models.CheckConstraint(condition=models.Q(("expected_revenue__gte", 0)), name="sales_opportunity_revenue_nonnegative"),
        ),
        migrations.AddField(
            model_name="quote",
            name="opportunity",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="quotes", to="sales.opportunity"),
        ),
    ]
