from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("billing", "0001_initial")]
    operations = [
        migrations.AddConstraint(
            model_name="customerinvoice",
            constraint=models.CheckConstraint(condition=models.Q(currency="MXN"), name="billing_invoice_currency_mxn"),
        ),
        migrations.AddConstraint(
            model_name="payment",
            constraint=models.CheckConstraint(condition=models.Q(currency="MXN"), name="billing_payment_currency_mxn"),
        ),
    ]
