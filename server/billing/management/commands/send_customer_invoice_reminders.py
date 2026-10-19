from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from billing.models import CustomerInvoice, CustomerInvoiceReminder


RETRY_DELAYS_MINUTES = [5, 30, 120, 360]
MAX_ATTEMPTS = len(RETRY_DELAYS_MINUTES) + 1


class Command(BaseCommand):
    help = "Envía recordatorios administrativos de cuentas por cobrar próximas a vencer o vencidas."

    def add_arguments(self, parser):
        parser.add_argument(
            "--upcoming-days",
            type=int,
            default=getattr(settings, "BILLING_REMINDER_DAYS_AHEAD", 3),
            help="Días naturales de anticipación para avisar sobre una factura (predeterminado: 3).",
        )
        parser.add_argument("--limit", type=int, default=200, help="Máximo de facturas por ejecución.")

    def handle(self, *args, **options):
        if not settings.BILLING_REMINDERS_ENABLED:
            self.stdout.write("Recordatorios de cobranza desactivados; no se envió correo.")
            return
        if options["upcoming_days"] < 0 or options["limit"] < 1:
            raise CommandError("--upcoming-days debe ser cero o mayor y --limit debe ser positivo.")
        if not settings.EMAIL_HOST or not settings.DEFAULT_FROM_EMAIL:
            raise CommandError("Configura EMAIL_HOST y EMAIL_FROM para enviar recordatorios.")
        if settings.EMAIL_USE_TLS and settings.EMAIL_USE_SSL:
            raise CommandError("Activa solo una opción entre EMAIL_USE_TLS y EMAIL_USE_SSL.")

        now = timezone.now()
        today = timezone.localdate()
        horizon = today + timedelta(days=options["upcoming_days"])
        related_reminders = CustomerInvoiceReminder.objects.filter(invoice_id=OuterRef("pk"))
        terminal_statuses = [
            CustomerInvoiceReminder.Status.SENT,
            CustomerInvoiceReminder.Status.FAILED,
            CustomerInvoiceReminder.Status.SKIPPED,
        ]
        invoices = CustomerInvoice.objects.filter(
            state__in=[CustomerInvoice.State.OPEN, CustomerInvoice.State.PARTIAL],
            due_date__isnull=False,
            due_date__lte=horizon,
        ).annotate(
            upcoming_reminder_exists=Exists(related_reminders.filter(kind=CustomerInvoiceReminder.Kind.UPCOMING)),
            upcoming_reminder_terminal=Exists(related_reminders.filter(
                kind=CustomerInvoiceReminder.Kind.UPCOMING, status__in=terminal_statuses,
            )),
            upcoming_reminder_ready=Exists(related_reminders.filter(
                kind=CustomerInvoiceReminder.Kind.UPCOMING,
                status=CustomerInvoiceReminder.Status.PENDING,
                next_attempt_at__lte=now,
            )),
            overdue_reminder_exists=Exists(related_reminders.filter(kind=CustomerInvoiceReminder.Kind.OVERDUE)),
            overdue_reminder_terminal=Exists(related_reminders.filter(
                kind=CustomerInvoiceReminder.Kind.OVERDUE, status__in=terminal_statuses,
            )),
            overdue_reminder_ready=Exists(related_reminders.filter(
                kind=CustomerInvoiceReminder.Kind.OVERDUE,
                status=CustomerInvoiceReminder.Status.PENDING,
                next_attempt_at__lte=now,
            )),
        ).filter(
            (
                Q(due_date__gte=today)
                & (Q(upcoming_reminder_exists=False) | (Q(upcoming_reminder_terminal=False) & Q(upcoming_reminder_ready=True)))
            )
            | (
                Q(due_date__lt=today)
                & (Q(overdue_reminder_exists=False) | (Q(overdue_reminder_terminal=False) & Q(overdue_reminder_ready=True)))
            )
        ).select_related("customer").order_by("due_date", "number")[:options["limit"]]

        sent = no_email = failed = unchanged = 0
        for invoice in invoices:
            kind = CustomerInvoiceReminder.Kind.OVERDUE if invoice.due_date < today else CustomerInvoiceReminder.Kind.UPCOMING
            result = self._send_one(invoice, kind, now)
            if result == "sent":
                sent += 1
            elif result == "failed":
                failed += 1
            elif result == "skipped":
                no_email += 1
            else:
                unchanged += 1

        self.stdout.write(
            f"Recordatorios enviados: {sent}; sin correo de cliente: {no_email}; "
            f"con error: {failed}; sin cambio: {unchanged}."
        )
        if failed:
            raise CommandError("Algunos recordatorios fallaron; los reintentos pendientes continuarán en la siguiente ejecución.")

    def _send_one(self, invoice, kind, now):
        try:
            with transaction.atomic():
                invoice = CustomerInvoice.objects.select_for_update().select_related("customer").get(pk=invoice.pk)
                if invoice.state not in [CustomerInvoice.State.OPEN, CustomerInvoice.State.PARTIAL]:
                    return "unchanged"
                balance = invoice.balance_due
                if balance <= Decimal("0.00"):
                    return "unchanged"
                recipient = invoice.customer.email.strip()
                reminder, _ = CustomerInvoiceReminder.objects.get_or_create(
                    invoice=invoice,
                    kind=kind,
                    defaults={
                        "recipient_email": recipient,
                        "balance_snapshot": balance,
                        "due_date_snapshot": invoice.due_date,
                    },
                )
                reminder = CustomerInvoiceReminder.objects.select_for_update().select_related(
                    "invoice", "invoice__customer"
                ).get(pk=reminder.pk)
                if reminder.status in [
                    CustomerInvoiceReminder.Status.SENT,
                    CustomerInvoiceReminder.Status.FAILED,
                    CustomerInvoiceReminder.Status.SKIPPED,
                ] or reminder.next_attempt_at > now:
                    return "unchanged"

                if not recipient:
                    reminder.status = CustomerInvoiceReminder.Status.SKIPPED
                    reminder.balance_snapshot = balance
                    reminder.due_date_snapshot = invoice.due_date
                    reminder.last_error = "customer_email_missing"
                    reminder.save(update_fields=["status", "balance_snapshot", "due_date_snapshot", "last_error"])
                    return "skipped"

                reminder.attempt_count += 1
                reminder.last_attempt_at = now
                reminder.recipient_email = recipient
                reminder.balance_snapshot = balance
                reminder.due_date_snapshot = invoice.due_date
                label = "vencida" if kind == CustomerInvoiceReminder.Kind.OVERDUE else "próxima a vencer"
                amount = f"${balance:,.2f} MXN"
                subject = f"Recordatorio administrativo de pago · {invoice.number}"[:250]
                message = (
                    f"Hola {invoice.customer.name},\n\n"
                    f"Te compartimos un recordatorio administrativo sobre la factura {invoice.number}, {label}.\n"
                    f"Fecha de vencimiento registrada: {invoice.due_date:%d/%m/%Y}.\n"
                    f"Saldo pendiente registrado: {amount}.\n\n"
                    "Si ya realizaste el pago, puedes ignorar este mensaje o responder a tu contacto de Redmagna. "
                    "Este correo no es un CFDI ni modifica el estado fiscal o contable de la factura.\n"
                )
                try:
                    delivered = send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [recipient], fail_silently=False)
                    if delivered != 1:
                        raise RuntimeError("El servidor de correo no confirmó la entrega.")
                except Exception as error:
                    reminder.last_error = type(error).__name__[:120]
                    if reminder.attempt_count >= MAX_ATTEMPTS:
                        reminder.status = CustomerInvoiceReminder.Status.FAILED
                    else:
                        reminder.status = CustomerInvoiceReminder.Status.PENDING
                        delay = RETRY_DELAYS_MINUTES[reminder.attempt_count - 1]
                        reminder.next_attempt_at = now + timedelta(minutes=delay)
                    reminder.save(update_fields=[
                        "attempt_count", "last_attempt_at", "recipient_email", "balance_snapshot",
                        "due_date_snapshot", "last_error", "status", "next_attempt_at",
                    ])
                    self.stderr.write(f"No se pudo enviar el recordatorio de cobranza {reminder.pk} ({reminder.last_error}).")
                    return "failed"

                reminder.status = CustomerInvoiceReminder.Status.SENT
                reminder.sent_at = timezone.now()
                reminder.last_error = ""
                reminder.save(update_fields=[
                    "attempt_count", "last_attempt_at", "recipient_email", "balance_snapshot",
                    "due_date_snapshot", "status", "sent_at", "last_error",
                ])
            return "sent"
        except Exception:
            self.stderr.write(f"No se pudo registrar el recordatorio de cobranza para {invoice.number}.")
            return "failed"
