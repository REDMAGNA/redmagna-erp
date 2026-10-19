from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from sales.models import AuditEvent, Quote


class Command(BaseCommand):
    help = "Marca como vencidas las cotizaciones enviadas cuya vigencia ya terminó."

    def handle(self, *args, **options):
        today = timezone.localdate()
        candidates = Quote.objects.filter(
            status=Quote.Status.SENT,
            valid_until__lt=today,
        ).order_by("valid_until", "id").values_list("id", flat=True)

        expired = 0
        for quote_id in candidates.iterator(chunk_size=200):
            with transaction.atomic():
                quote = Quote.objects.select_for_update().filter(pk=quote_id).first()
                if (
                    quote is None
                    or quote.status != Quote.Status.SENT
                    or quote.valid_until is None
                    or quote.valid_until >= timezone.localdate()
                ):
                    continue
                quote.status = Quote.Status.EXPIRED
                quote.save(update_fields=["status", "updated_at"])
                AuditEvent.objects.create(
                    entity_type="quote",
                    entity_id=quote.id,
                    action="expired",
                    from_value=Quote.Status.SENT,
                    to_value=Quote.Status.EXPIRED,
                )
                expired += 1

        self.stdout.write(f"Cotizaciones marcadas como vencidas: {expired}.")
