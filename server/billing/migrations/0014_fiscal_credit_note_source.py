from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("billing", "0013_customer_credit_note_reversal")]

    operations = [
        migrations.RemoveConstraint(model_name="fiscaldocument", name="billing_fiscal_one_source"),
        migrations.AddField(
            model_name="fiscaldocument",
            name="credit_note",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="fiscal_documents", to="billing.customercreditnote"),
        ),
        migrations.AddConstraint(
            model_name="fiscaldocument",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("credit_note__isnull", True), ("invoice__isnull", False), ("payment__isnull", True))
                    | models.Q(("credit_note__isnull", True), ("invoice__isnull", True), ("payment__isnull", False))
                    | models.Q(("credit_note__isnull", False), ("invoice__isnull", True), ("payment__isnull", True))
                ),
                name="billing_fiscal_one_source",
            ),
        ),
    ]
