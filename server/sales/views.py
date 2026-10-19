import csv
import hmac
import io
import re
import unicodedata
from datetime import timedelta
from uuid import UUID, uuid4

from django.conf import settings
from django.core import signing
from django.core.mail import EmailMultiAlternatives
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from django.db import transaction
from django.urls import reverse
from django.http import FileResponse
from django.db.models import Count, DecimalField, F, Q, Sum
from django.db.models.expressions import ExpressionWrapper
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.html import escape
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from django.utils.dateparse import parse_date
from urllib.parse import urljoin, urlsplit
from hashlib import sha256
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from billing.serializers import CustomerInvoiceSerializer
from billing.services import create_invoice_from_work_order
from inventory.models import StockLocation, StockMovement, StockReservation, StockUnit
from django.core.exceptions import ValidationError as DjangoValidationError
from .forms import PublicQuoteRequestForm
from .models import AuditEvent, Customer, CustomerContact, CustomerSite, Opportunity, OpportunityActivity, PublicLeadNotification, PublicLeadSubmission, Quote, QuoteAcceptance, QuoteCostSheet, QuoteTemplate, SalesOrder, WorkLog, WorkOrder, WorkOrderChecklistItem, WorkOrderChecklistTemplate, WorkOrderEvidence, WorkOrderMaterialRequirement
from .permissions import CustomerContactPermissions, CustomerPermissions, CustomerSitePermissions, OpportunityActivityPermissions, OpportunityPermissions, QuoteCostSheetPermissions, QuotePermissions, QuoteTemplatePermissions, WorkOrderChecklistTemplatePermissions, WorkOrderEvidencePermissions, WorkOrderPermissions
from .serializers import CustomerContactSerializer, CustomerSerializer, CustomerSiteSerializer, OpportunityActivitySerializer, OpportunityConvertSerializer, OpportunitySerializer, QuoteCostSheetSerializer, QuoteSerializer, QuoteTemplateSerializer, WorkLogInputSerializer, WorkLogSerializer, WorkOrderChecklistItemCreateSerializer, WorkOrderChecklistItemSerializer, WorkOrderChecklistItemUpdateSerializer, WorkOrderChecklistTemplateApplySerializer, WorkOrderChecklistTemplateSerializer, WorkOrderCustomerAcceptanceInputSerializer, WorkOrderEvidenceSerializer, WorkOrderEvidenceUploadSerializer, WorkOrderInvoiceCreateSerializer, WorkOrderMaterialLocationSerializer, WorkOrderMaterialRequirementSerializer, WorkOrderScheduleSerializer, WorkOrderSerializer
from .services import approve_quote, approve_quote_discount, quote_discount_review, record_work_order_customer_acceptance, revise_quote


QUOTE_ACCEPTANCE_SALT = "redmagna.quote.acceptance.v1"
QUOTE_ACCEPTANCE_MAX_AGE = 14 * 24 * 60 * 60
PUBLIC_LEAD_SALT = "redmagna.public-lead.v1"
PUBLIC_LEAD_MAX_AGE = 2 * 60 * 60


@never_cache
@require_http_methods(["GET", "POST"])
def public_quote_request(request):
    template = "sales/public_quote_request.html"
    if not settings.ERP_PUBLIC_LEADS_ENABLED:
        from django.http import Http404
        raise Http404

    if request.method == "GET":
        nonce = uuid4()
        token = signing.dumps({"nonce": str(nonce)}, salt=PUBLIC_LEAD_SALT)
        attribution = {field: request.GET.get(field, "")[:120].strip() for field in ("utm_source", "utm_medium", "utm_campaign")}
        return render(request, template, {"form": PublicQuoteRequestForm(initial=attribution), "token": token, "privacy_url": settings.ERP_PRIVACY_URL})

    # Invalid links and filled honeypots get the same neutral acknowledgement.
    def acknowledged():
        return render(request, template, {"submitted": True}, status=200)

    token = request.POST.get("token", "")
    try:
        payload = signing.loads(token, salt=PUBLIC_LEAD_SALT, max_age=PUBLIC_LEAD_MAX_AGE)
        nonce = UUID(payload.get("nonce", ""))
    except (signing.BadSignature, ValueError, TypeError):
        return acknowledged()
    form = PublicQuoteRequestForm(request.POST)
    if not form.is_valid():
        return render(request, template, {"form": form, "token": token, "privacy_url": settings.ERP_PRIVACY_URL})
    if form.cleaned_data["website"]:
        return acknowledged()

    email = form.cleaned_data["email"].strip().casefold()
    email_digest = hmac.new(settings.SECRET_KEY.encode("utf-8"), email.encode("utf-8"), "sha256").hexdigest()
    cutoff = timezone.now() - timedelta(hours=1)
    with transaction.atomic():
        # Serialize both per-email rate limiting and token use on PostgreSQL.
        lock_key = int(email_digest[:16], 16) - (1 << 63)
        with transaction.get_connection().cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_key])
            nonce_lock_key = int(nonce.hex[:16], 16) - (1 << 63)
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [nonce_lock_key])
        if PublicLeadSubmission.objects.filter(nonce=nonce).exists():
            return acknowledged()
        if PublicLeadSubmission.objects.filter(email_digest=email_digest, created_at__gte=cutoff).count() >= 3:
            return acknowledged()
        data = form.cleaned_data
        opportunity = Opportunity.objects.create(
            name=data["subject"], company_name=data["company_name"], contact_name=data["contact_name"],
            email=email, phone=data["phone"], stage=Opportunity.Stage.NEW, expected_revenue=Decimal("0.00"),
            source="Sitio web", utm_source=data["utm_source"], utm_medium=data["utm_medium"],
            utm_campaign=data["utm_campaign"], description=data["details"], created_by=None,
        )
        submission = PublicLeadSubmission.objects.create(
            nonce=nonce, email_digest=email_digest, opportunity=opportunity, consent_at=timezone.now(),
        )
        notification_email = settings.CRM_LEAD_NOTIFICATION_EMAIL
        if notification_email:
            PublicLeadNotification.objects.create(submission=submission, recipient_email=notification_email)
        AuditEvent.objects.create(entity_type="Opportunity", entity_id=opportunity.id, action="public_web_submission")
    return acknowledged()


def _quote_document_context(quote, *, accepted=False, **extra):
    lines = []
    subtotal = Decimal("0.00")
    tax_total = Decimal("0.00")
    for line in quote.lines.all():
        quantity = line.billable_quantity if accepted else line.quantity
        if accepted and quantity <= 0:
            continue
        line.document_quantity = quantity
        gross = (quantity * line.unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        line.document_discount = (gross * line.discount_percent / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        line.document_subtotal = gross - line.document_discount
        line.document_tax = (line.document_subtotal * line.tax_rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if accepted or not line.is_optional:
            subtotal += line.document_subtotal
            tax_total += line.document_tax
        lines.append(line)
    return {
        "quote": quote,
        "recipient_name": quote.recipient_name_snapshot or quote.customer.name,
        "recipient_email": quote.recipient_email_snapshot or (quote.customer.email if not quote.customer_contact_id else ""),
        "lines": lines,
        "subtotal": subtotal,
        "tax_total": tax_total,
        "total": subtotal + tax_total,
        "company": {
            "name": settings.ERP_COMPANY_NAME,
            "legal_name": settings.ERP_COMPANY_LEGAL_NAME,
            "rfc": settings.ERP_COMPANY_RFC,
            "address": settings.ERP_COMPANY_ADDRESS,
            "phone": settings.ERP_COMPANY_PHONE,
            "email": settings.ERP_COMPANY_EMAIL,
            "website": settings.ERP_COMPANY_WEBSITE,
        },
        **extra,
    }


def _quote_recipient_email(quote):
    if quote.customer_contact_id:
        return quote.recipient_email_snapshot.strip().lower()
    return (quote.recipient_email_snapshot or quote.customer.email).strip().lower()


def quote_acceptance_token(quote):
    return signing.dumps({
        "quote_id": str(quote.id),
        "revision_number": quote.revision_number,
        "customer_email_hash": sha256(_quote_recipient_email(quote).encode("utf-8")).hexdigest(),
    }, salt=QUOTE_ACCEPTANCE_SALT, compress=True)


@never_cache
@require_http_methods(["GET", "POST"])
def accept_quote_public(request, token):
    template = "sales/quote_acceptance.html"
    try:
        payload = signing.loads(token, salt=QUOTE_ACCEPTANCE_SALT, max_age=QUOTE_ACCEPTANCE_MAX_AGE)
    except signing.SignatureExpired:
        return render(request, template, {"unavailable": "Este enlace de aceptación venció."}, status=410)
    except signing.BadSignature:
        return render(request, template, {"unavailable": "El enlace de aceptación no es válido."}, status=404)

    quote = Quote.objects.select_related("customer", "customer_contact").prefetch_related("lines").filter(pk=payload.get("quote_id")).first()
    if not quote:
        return render(request, template, {"unavailable": "No se encontró esta cotización."}, status=404)
    recipient_email = _quote_recipient_email(quote)
    current_email_hash = sha256(recipient_email.encode("utf-8")).hexdigest()
    if payload.get("revision_number") != quote.revision_number or payload.get("customer_email_hash") != current_email_hash:
        return render(request, template, {"unavailable": "Este enlace dejó de ser válido porque cambiaron los datos de la cotización."}, status=410)

    acceptance = QuoteAcceptance.objects.filter(quote=quote).first()
    if quote.status == Quote.Status.APPROVED and acceptance:
        return render(request, template, _quote_document_context(quote, accepted=True, acceptance=acceptance))
    if quote.status != Quote.Status.SENT or (quote.valid_until and quote.valid_until < timezone.localdate()):
        return render(request, template, {"unavailable": "La cotización ya no está disponible para aceptación."}, status=410)
    discount_review = quote_discount_review(quote)
    if discount_review["required"] and not discount_review["approved"]:
        return render(request, template, {"unavailable": "Esta cotización requiere autorización interna de Gerencia antes de que pueda aceptarse. Contacta a Redmagna."}, status=423)

    errors = []
    name = ""
    email = ""
    accepted_quantities = {}
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip().lower()
        accepted_quantities = {
            str(line.id): request.POST.get(f"accepted_quantity_{line.id}", "")
            for line in quote.lines.all()
        }
        if not name or len(name) > 160:
            errors.append("Escribe tu nombre (máximo 160 caracteres).")
        if not recipient_email or email != recipient_email:
            errors.append("Escribe el correo destinatario registrado para esta cotización.")
        if request.POST.get("accept") != "yes":
            errors.append("Confirma que aceptas la propuesta comercial.")
        if not errors:
            try:
                quote, _order = approve_quote(
                    quote.id,
                    customer_acceptance={"name": name, "email": email},
                    accepted_quantities=accepted_quantities,
                )
                acceptance = QuoteAcceptance.objects.get(quote=quote)
                return render(request, template, _quote_document_context(quote, accepted=True, acceptance=acceptance))
            except ValidationError as exc:
                quote.refresh_from_db()
                acceptance = QuoteAcceptance.objects.filter(quote=quote).first()
                if quote.status == Quote.Status.APPROVED and acceptance:
                    return render(request, template, _quote_document_context(quote, accepted=True, acceptance=acceptance))
                detail = exc.detail
                errors.extend(detail if isinstance(detail, list) else [str(detail)])

    context = _quote_document_context(quote)
    accepted_subtotal = Decimal("0.00")
    accepted_tax = Decimal("0.00")
    for line in context["lines"]:
        line.proposed_quantity = line.quantity
        submitted = accepted_quantities.get(str(line.pk))
        line.accepted_quantity_input = submitted if submitted is not None else ("0.000" if line.is_optional else format(line.quantity, ".3f"))
        try:
            display_quantity = Decimal(line.accepted_quantity_input)
            if not display_quantity.is_finite() or display_quantity < 0 or display_quantity > line.quantity:
                display_quantity = Decimal("0.000")
        except (InvalidOperation, TypeError, ValueError):
            display_quantity = Decimal("0.000")
        line.document_quantity = display_quantity
        gross = (display_quantity * line.unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        line.document_discount = (gross * line.discount_percent / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        line.document_subtotal = gross - line.document_discount
        line.document_tax = (line.document_subtotal * line.tax_rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        accepted_subtotal += line.document_subtotal
        accepted_tax += line.document_tax
    context.update({
        "accepted_subtotal": accepted_subtotal,
        "accepted_tax": accepted_tax,
        "accepted_total": accepted_subtotal + accepted_tax,
        "optional_subtotal": quote.optional_subtotal,
        "optional_tax_total": quote.optional_tax_total,
        "optional_total": quote.optional_total,
        "errors": errors,
        "name": name,
        "email": email,
    })
    return render(request, template, context, status=400 if errors else 200)


class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.filter(is_active=True)
    serializer_class = CustomerSerializer
    search_fields = ["name", "legal_name", "rfc", "email"]
    ordering_fields = ["name", "created_at"]
    permission_classes = [CustomerPermissions]

    @action(detail=False, methods=["post"], url_path="import-csv", parser_classes=[MultiPartParser, FormParser])
    def import_csv(self, request):
        uploaded = request.FILES.get("file")
        if uploaded is None:
            raise ValidationError({"file": "Selecciona un archivo CSV."})
        if uploaded.size > 5 * 1024 * 1024:
            raise ValidationError({"file": "El archivo no puede superar 5 MB."})
        try:
            source = uploaded.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ValidationError({"file": "Guarda el CSV como UTF-8 y vuelve a seleccionarlo."}) from None
        if not source.strip():
            raise ValidationError({"file": "El archivo no contiene datos."})

        def normalize_header(value):
            ascii_value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii").casefold()
            return re.sub(r"[^a-z0-9]+", "_", ascii_value).strip("_")

        aliases = {
            "name": {"name", "nombre", "customer", "contact"},
            "legal_name": {"legal_name", "razon_social", "company_name", "nombre_fiscal"},
            "rfc": {"rfc", "tax_id", "vat"},
            "email": {"email", "correo", "e_mail"},
            "phone": {"phone", "telefono", "telephone", "mobile"},
            "fiscal_regime": {"fiscal_regime", "regimen_fiscal", "tax_regime"},
            "fiscal_postal_code": {"fiscal_postal_code", "codigo_postal_fiscal", "zip", "zip_code", "postal_code"},
        }
        try:
            sample = source[:4096]
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            reader = csv.DictReader(io.StringIO(source), dialect=dialect)
            header_map = {}
            for header in reader.fieldnames or []:
                normalized = normalize_header(header)
                matching = [field for field, names in aliases.items() if normalized in names]
                if matching:
                    if matching[0] in header_map.values():
                        raise ValidationError({"file": f"Hay más de una columna para {matching[0]}. Deja solo una."})
                    header_map[header] = matching[0]
            if "name" not in header_map.values():
                raise ValidationError({"file": "Incluye una columna Nombre o Name."})
            raw_rows = list(reader)
        except csv.Error as error:
            raise ValidationError({"file": f"No se pudo leer el CSV: {error}"}) from None
        if len(raw_rows) > 1000:
            raise ValidationError({"file": "Importa como máximo 1,000 clientes por archivo."})

        existing_rfc = {}
        existing_name_email = set()
        for customer in Customer.objects.all().only("rfc", "name", "email", "is_active"):
            if customer.rfc.strip():
                existing_rfc.setdefault(customer.rfc.strip().upper(), customer.is_active)
            if customer.email.strip():
                existing_name_email.add((customer.name.strip().casefold(), customer.email.strip().casefold()))

        seen_rfc, seen_name_email = set(), set()
        results, to_create = [], []
        for row_number, raw in enumerate(raw_rows, start=2):
            payload = {"is_active": True}
            for header, value in raw.items():
                field = header_map.get(header)
                if field:
                    payload[field] = (value or "").strip()
            payload["rfc"] = payload.get("rfc", "").upper()
            serializer = CustomerSerializer(data=payload)
            if not serializer.is_valid():
                errors = "; ".join(f"{field}: {', '.join(str(item) for item in messages)}" for field, messages in serializer.errors.items())
                results.append({"row": row_number, "name": payload.get("name", ""), "status": "error", "detail": errors})
                continue
            clean = serializer.validated_data
            rfc = clean.get("rfc", "").strip().upper()
            name_email = (clean["name"].strip().casefold(), clean.get("email", "").strip().casefold())
            duplicate = bool(rfc and (rfc in existing_rfc or rfc in seen_rfc)) or bool(clean.get("email") and (name_email in existing_name_email or name_email in seen_name_email))
            if duplicate:
                results.append({"row": row_number, "name": clean["name"], "status": "duplicate", "detail": "Coincide por RFC o por nombre y correo; no se modificará ningún registro."})
                if rfc:
                    seen_rfc.add(rfc)
                if clean.get("email"):
                    seen_name_email.add(name_email)
                continue
            results.append({"row": row_number, "name": clean["name"], "status": "create", "detail": "Listo para importar."})
            to_create.append((row_number, clean))
            if rfc:
                seen_rfc.add(rfc)
            if clean.get("email"):
                seen_name_email.add(name_email)

        commit = str(request.data.get("commit", "false")).casefold() in {"1", "true", "yes", "si", "sí"}
        created_count = 0
        if commit and to_create:
            with transaction.atomic():
                for _, data in to_create:
                    Customer.objects.create(**data)
            created_count = len(to_create)
        return Response({
            "committed": commit,
            "created": created_count,
            "skipped": sum(item["status"] == "duplicate" for item in results),
            "errors": sum(item["status"] == "error" for item in results),
            "rows": results,
        })

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=["is_active", "updated_at"])


class CustomerSiteViewSet(viewsets.ModelViewSet):
    queryset = CustomerSite.objects.select_related("customer").filter(customer__is_active=True)
    serializer_class = CustomerSiteSerializer
    permission_classes = [CustomerSitePermissions]
    http_method_names = ["get", "post", "patch", "head", "options"]
    search_fields = ["name", "address", "customer__name"]
    ordering_fields = ["name", "created_at"]

    def get_queryset(self):
        queryset = super().get_queryset()
        customer_id = self.request.query_params.get("customer")
        if customer_id:
            try:
                customer_id = UUID(customer_id)
            except (TypeError, ValueError, AttributeError) as error:
                raise ValidationError({"customer": "El identificador del cliente no es válido."}) from error
            queryset = queryset.filter(customer_id=customer_id)
        if self.request.query_params.get("active", "true").lower() in {"1", "true", "yes"}:
            queryset = queryset.filter(is_active=True)
        return queryset


class CustomerContactViewSet(viewsets.ModelViewSet):
    queryset = CustomerContact.objects.select_related("customer").filter(customer__is_active=True)
    serializer_class = CustomerContactSerializer
    permission_classes = [CustomerContactPermissions]
    http_method_names = ["get", "post", "patch", "head", "options"]
    search_fields = ["name", "role", "email", "phone", "customer__name"]
    ordering_fields = ["name", "role", "created_at"]

    def get_queryset(self):
        queryset = super().get_queryset()
        customer_id = self.request.query_params.get("customer")
        if customer_id:
            try:
                customer_id = UUID(customer_id)
            except (TypeError, ValueError, AttributeError) as error:
                raise ValidationError({"customer": "El identificador del cliente no es válido."}) from error
            queryset = queryset.filter(customer_id=customer_id)
        active_filter = self.request.query_params.get("active", "true").lower()
        if active_filter in {"1", "true", "yes"}:
            queryset = queryset.filter(is_active=True)
        elif active_filter in {"0", "false", "no"}:
            queryset = queryset.filter(is_active=False)
        return queryset

    @transaction.atomic
    def perform_create(self, serializer):
        customer = Customer.objects.select_for_update().get(pk=serializer.validated_data["customer"].pk)
        if serializer.validated_data.get("is_primary", False):
            CustomerContact.objects.filter(customer=customer, is_active=True, is_primary=True).update(is_primary=False)
        serializer.save(customer=customer)

    @transaction.atomic
    def perform_update(self, serializer):
        current = CustomerContact.objects.select_for_update().get(pk=serializer.instance.pk)
        Customer.objects.select_for_update().get(pk=current.customer_id)
        will_be_active = serializer.validated_data.get("is_active", current.is_active)
        will_be_primary = serializer.validated_data.get("is_primary", current.is_primary)
        if will_be_active and will_be_primary:
            CustomerContact.objects.filter(customer_id=current.customer_id, is_active=True, is_primary=True).exclude(pk=current.pk).update(is_primary=False)
        serializer.save(customer=current.customer)


class WorkOrderChecklistTemplateViewSet(viewsets.ModelViewSet):
    queryset = WorkOrderChecklistTemplate.objects.select_related("created_by")
    serializer_class = WorkOrderChecklistTemplateSerializer
    permission_classes = [WorkOrderChecklistTemplatePermissions]
    http_method_names = ["get", "post", "patch", "head", "options"]
    search_fields = ["name"]
    ordering_fields = ["name", "created_at"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get("active", "true").lower() in {"1", "true", "yes"}:
            queryset = queryset.filter(is_active=True)
        return queryset

    def perform_create(self, serializer):
        template = serializer.save(created_by=self.request.user)
        AuditEvent.objects.create(entity_type="work_order_checklist_template", entity_id=template.id, action="created", to_value="active", actor=self.request.user)

    def perform_update(self, serializer):
        previous_active = serializer.instance.is_active
        template = serializer.save()
        if previous_active != template.is_active:
            AuditEvent.objects.create(entity_type="work_order_checklist_template", entity_id=template.id, action="activated" if template.is_active else "deactivated", actor=self.request.user)
        else:
            AuditEvent.objects.create(entity_type="work_order_checklist_template", entity_id=template.id, action="updated", to_value="updated", actor=self.request.user)


class OpportunityViewSet(viewsets.ModelViewSet):
    queryset = Opportunity.objects.select_related("customer", "assigned_to", "created_by")
    serializer_class = OpportunitySerializer
    search_fields = ["name", "company_name", "contact_name", "email", "customer__name"]
    ordering_fields = ["name", "stage", "expected_revenue", "expected_close_date", "updated_at"]
    permission_classes = [OpportunityPermissions]

    def perform_create(self, serializer):
        opportunity = serializer.save(created_by=self.request.user)
        AuditEvent.objects.create(entity_type="opportunity", entity_id=opportunity.id, action="created", to_value=opportunity.stage, actor=self.request.user)

    def perform_update(self, serializer):
        changed_fields = sorted(serializer.validated_data.keys())
        opportunity = serializer.save()
        AuditEvent.objects.create(entity_type="opportunity", entity_id=opportunity.id, action="updated", from_value=",".join(changed_fields)[:32], to_value="commercial_fields", actor=self.request.user)

    @action(detail=False, methods=["get"])
    def report(self, request):
        raw_from = request.query_params.get("date_from", "").strip()
        raw_to = request.query_params.get("date_to", "").strip()
        date_from = parse_date(raw_from) if raw_from else None
        date_to = parse_date(raw_to) if raw_to else None
        if raw_from and date_from is None:
            raise ValidationError({"date_from": "Usa una fecha válida con formato AAAA-MM-DD."})
        if raw_to and date_to is None:
            raise ValidationError({"date_to": "Usa una fecha válida con formato AAAA-MM-DD."})
        if date_from and date_to and date_from > date_to:
            raise ValidationError({"date_to": "La fecha final debe ser igual o posterior a la inicial."})

        opportunities = Opportunity.objects.all()
        if date_from:
            opportunities = opportunities.filter(created_at__date__gte=date_from)
        if date_to:
            opportunities = opportunities.filter(created_at__date__lte=date_to)
        open_stages = [Opportunity.Stage.NEW, Opportunity.Stage.QUALIFIED, Opportunity.Stage.PROPOSAL]
        weighted = ExpressionWrapper(
            F("expected_revenue") * F("probability") / 100,
            output_field=DecimalField(max_digits=24, decimal_places=4),
        )
        totals = opportunities.aggregate(total=Count("id"))
        open_totals = opportunities.filter(stage__in=open_stages).aggregate(
            count=Count("id"), revenue=Sum("expected_revenue"), weighted_revenue=Sum(weighted),
        )
        won_totals = opportunities.filter(stage=Opportunity.Stage.WON).aggregate(
            count=Count("id"), revenue=Sum("expected_revenue"),
        )
        lost_count = opportunities.filter(stage=Opportunity.Stage.LOST).count()
        closed_count = won_totals["count"] + lost_count
        by_source = opportunities.values("source").annotate(
            count=Count("id"),
            won=Count("id", filter=Q(stage=Opportunity.Stage.WON)),
            lost=Count("id", filter=Q(stage=Opportunity.Stage.LOST)),
            weighted_revenue=Sum(weighted, filter=Q(stage__in=open_stages)),
        ).order_by("source")
        sources = []
        for row in by_source:
            closed = row["won"] + row["lost"]
            sources.append({
                "source": row["source"] or "",
                "count": row["count"],
                "won": row["won"],
                "lost": row["lost"],
                "closed": closed,
                "win_rate": round(row["won"] * 100 / closed, 2) if closed else None,
                "weighted_revenue": row["weighted_revenue"] or 0,
            })
        by_campaign = opportunities.values("utm_source", "utm_medium", "utm_campaign").annotate(
            count=Count("id"),
            won=Count("id", filter=Q(stage=Opportunity.Stage.WON)),
            lost=Count("id", filter=Q(stage=Opportunity.Stage.LOST)),
            weighted_revenue=Sum(weighted, filter=Q(stage__in=open_stages)),
        ).order_by("utm_source", "utm_medium", "utm_campaign")
        campaigns = []
        for row in by_campaign:
            if not (row["utm_source"] or row["utm_medium"] or row["utm_campaign"]):
                continue
            closed = row["won"] + row["lost"]
            campaigns.append({
                "utm_source": row["utm_source"],
                "utm_medium": row["utm_medium"],
                "utm_campaign": row["utm_campaign"],
                "count": row["count"],
                "won": row["won"],
                "lost": row["lost"],
                "win_rate": round(row["won"] * 100 / closed, 2) if closed else None,
                "weighted_revenue": row["weighted_revenue"] or 0,
            })
        return Response({
            "date_from": date_from,
            "date_to": date_to,
            "total": totals["total"],
            "open_count": open_totals["count"],
            "open_revenue": open_totals["revenue"] or 0,
            "weighted_revenue": open_totals["weighted_revenue"] or 0,
            "won_count": won_totals["count"],
            "won_revenue": won_totals["revenue"] or 0,
            "lost_count": lost_count,
            "closed_count": closed_count,
            "win_rate": round(won_totals["count"] * 100 / closed_count, 2) if closed_count else None,
            "by_source": sources,
            "by_campaign": campaigns,
        })

    @action(detail=True, methods=["post"])
    def convert(self, request, pk=None):
        serializer = OpportunityConvertSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target = serializer.validated_data
        with transaction.atomic():
            opportunity = Opportunity.objects.select_for_update().select_related("customer").get(pk=pk)
            if opportunity.customer_id:
                if target.get("customer_id") and target["customer_id"].pk != opportunity.customer_id:
                    raise ValidationError({"customer_id": "Esta oportunidad ya está vinculada a otro cliente."})
                if target.get("new_customer"):
                    raise ValidationError("Esta oportunidad ya está vinculada a un cliente.")
                customer = opportunity.customer
                created = False
            else:
                if not target.get("customer_id") and not target.get("new_customer"):
                    raise ValidationError("Selecciona un cliente existente o captura los datos para crear uno.")
                if opportunity.stage == Opportunity.Stage.LOST:
                    raise ValidationError("Reabre la oportunidad perdida antes de convertirla en cliente.")
                customer = target.get("customer_id")
                created = False
                if not customer:
                    customer_data = dict(target["new_customer"])
                    rfc = customer_data.get("rfc", "").strip().upper().replace(" ", "")
                    customer_data["rfc"] = rfc
                    matches = Customer.objects.select_for_update().filter(rfc__iexact=rfc) if rfc else Customer.objects.none()
                    if not rfc and customer_data.get("email"):
                        matches = Customer.objects.select_for_update().filter(name__iexact=customer_data["name"].strip(), email__iexact=customer_data["email"].strip())
                    matching_customers = list(matches.order_by("name")[:2])
                    if len(matching_customers) > 1:
                        raise ValidationError({"new_customer": "Hay varios clientes con esos datos. Selecciona el cliente correcto desde la opción de cliente existente."})
                    if matching_customers:
                        customer = matching_customers[0]
                        if not customer.is_active:
                            raise ValidationError({"new_customer": "Ya existe un cliente inactivo con esos datos. Solicita que Administración lo reactive antes de continuar."})
                    else:
                        if not request.user.has_perm("sales.add_customer"):
                            raise ValidationError("Tu usuario puede relacionar clientes existentes, pero no crear uno nuevo.")
                        customer = Customer.objects.create(**customer_data)
                        created = True
                opportunity.customer = customer
                opportunity.company_name = customer.name
                opportunity.save(update_fields=["customer", "company_name", "updated_at"])
                AuditEvent.objects.create(entity_type="opportunity", entity_id=opportunity.id, action="converted_to_customer", from_value="", to_value=str(customer.id), actor=request.user)
                if created:
                    AuditEvent.objects.create(entity_type="customer", entity_id=customer.id, action="created_from_opportunity", from_value="", to_value=customer.name[:120], actor=request.user)
        return Response({"opportunity": self.get_serializer(opportunity).data, "customer": CustomerSerializer(customer).data, "created": created})

    @action(detail=False, methods=["get"])
    def assignees(self, request):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        users = User.objects.filter(is_active=True).order_by("first_name", "username")
        return Response([
            {"id": user.pk, "username": user.get_username(), "name": user.get_full_name() or user.get_username()}
            for user in users
        ])

    @action(detail=True, methods=["post"])
    def qualify(self, request, pk=None):
        with transaction.atomic():
            opportunity = Opportunity.objects.select_for_update().get(pk=pk)
            if opportunity.stage != Opportunity.Stage.NEW:
                raise ValidationError("Solo una oportunidad nueva puede calificarse.")
            opportunity.stage = Opportunity.Stage.QUALIFIED
            opportunity.probability = max(opportunity.probability, 20)
            opportunity.save(update_fields=["stage", "probability", "updated_at"])
            AuditEvent.objects.create(entity_type="opportunity", entity_id=opportunity.id, action="qualified", from_value=Opportunity.Stage.NEW, to_value=opportunity.stage, actor=request.user)
        return Response(self.get_serializer(opportunity).data)

    @action(detail=True, methods=["post"])
    def reopen(self, request, pk=None):
        with transaction.atomic():
            opportunity = Opportunity.objects.select_for_update().get(pk=pk)
            if opportunity.stage != Opportunity.Stage.LOST:
                raise ValidationError("Solo una oportunidad perdida puede reabrirse.")
            opportunity.stage = Opportunity.Stage.QUALIFIED
            opportunity.probability = max(opportunity.probability, 20)
            opportunity.lost_reason = ""
            opportunity.closing_note = ""
            opportunity.save(update_fields=["stage", "probability", "lost_reason", "closing_note", "updated_at"])
            AuditEvent.objects.create(entity_type="opportunity", entity_id=opportunity.id, action="reopened", from_value=Opportunity.Stage.LOST, to_value=opportunity.stage, actor=request.user)
        return Response(self.get_serializer(opportunity).data)

    @action(detail=True, methods=["post"], url_path="mark-lost")
    def mark_lost(self, request, pk=None):
        reason = str(request.data.get("reason", "")).strip()
        note = str(request.data.get("note", "")).strip()
        if not reason:
            raise ValidationError({"reason": "Indica el motivo de pérdida para cerrar la oportunidad."})
        if len(reason) > 120 or len(note) > 5000:
            raise ValidationError("El motivo o la nota exceden la longitud permitida.")
        with transaction.atomic():
            opportunity = Opportunity.objects.select_for_update().get(pk=pk)
            if opportunity.stage in {Opportunity.Stage.WON, Opportunity.Stage.LOST}:
                raise ValidationError("La oportunidad ya está cerrada.")
            previous = opportunity.stage
            opportunity.stage = Opportunity.Stage.LOST
            opportunity.probability = 0
            opportunity.lost_reason = reason
            opportunity.closing_note = note
            opportunity.save(update_fields=["stage", "probability", "lost_reason", "closing_note", "updated_at"])
            AuditEvent.objects.create(entity_type="opportunity", entity_id=opportunity.id, action="marked_lost", from_value=previous, to_value=Opportunity.Stage.LOST, actor=request.user)
        return Response(self.get_serializer(opportunity).data)


class OpportunityActivityViewSet(viewsets.ModelViewSet):
    queryset = OpportunityActivity.objects.select_related("opportunity", "assigned_to", "created_by", "completed_by")
    serializer_class = OpportunityActivitySerializer
    search_fields = ["title", "note", "opportunity__name", "opportunity__company_name"]
    ordering_fields = ["due_at", "status", "created_at"]
    permission_classes = [OpportunityActivityPermissions]

    def get_queryset(self):
        queryset = super().get_queryset()
        opportunity_id = self.request.query_params.get("opportunity")
        if opportunity_id:
            try:
                opportunity_id = UUID(opportunity_id)
            except (TypeError, ValueError):
                return queryset.none()
            queryset = queryset.filter(opportunity_id=opportunity_id)
        return queryset

    def perform_create(self, serializer):
        activity = serializer.save(created_by=self.request.user)
        AuditEvent.objects.create(entity_type="opportunity_activity", entity_id=activity.id, action="scheduled", to_value=activity.status, actor=self.request.user)

    def perform_update(self, serializer):
        changed_fields = sorted(serializer.validated_data.keys())
        activity = serializer.save()
        AuditEvent.objects.create(entity_type="opportunity_activity", entity_id=activity.id, action="updated", from_value=",".join(changed_fields)[:32], to_value="activity_fields", actor=self.request.user)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        with transaction.atomic():
            activity = OpportunityActivity.objects.select_for_update().get(pk=pk)
            if activity.status != OpportunityActivity.Status.PLANNED:
                raise ValidationError("Solo una actividad pendiente puede completarse.")
            activity.status = OpportunityActivity.Status.DONE
            activity.completed_at = timezone.now()
            activity.completed_by = request.user
            activity.save(update_fields=["status", "completed_at", "completed_by"])
            AuditEvent.objects.create(entity_type="opportunity_activity", entity_id=activity.id, action="completed", from_value=OpportunityActivity.Status.PLANNED, to_value=activity.status, actor=request.user)
        return Response(self.get_serializer(activity).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        with transaction.atomic():
            activity = OpportunityActivity.objects.select_for_update().get(pk=pk)
            if activity.status != OpportunityActivity.Status.PLANNED:
                raise ValidationError("Solo una actividad pendiente puede cancelarse.")
            activity.status = OpportunityActivity.Status.CANCELLED
            activity.save(update_fields=["status"])
            AuditEvent.objects.create(entity_type="opportunity_activity", entity_id=activity.id, action="cancelled", from_value=OpportunityActivity.Status.PLANNED, to_value=activity.status, actor=request.user)
        return Response(self.get_serializer(activity).data)


class QuoteViewSet(viewsets.ModelViewSet):
    queryset = Quote.objects.select_related("customer", "customer_contact", "opportunity", "created_by", "revision_of").prefetch_related("lines__catalog_product")
    serializer_class = QuoteSerializer
    search_fields = ["number", "title", "customer__name", "customer__rfc"]
    ordering_fields = ["number", "issue_date", "created_at", "status"]
    http_method_names = ["get", "post", "put", "patch", "head", "options"]
    permission_classes = [QuotePermissions]

    def get_permissions(self):
        if getattr(self, "action", None) == "cost_sheet":
            return [QuoteCostSheetPermissions()]
        return super().get_permissions()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["get", "put"], url_path="cost-sheet")
    def cost_sheet(self, request, pk=None):
        with transaction.atomic():
            quote = get_object_or_404(Quote.objects.select_for_update(), pk=pk)
            sheet, _ = QuoteCostSheet.objects.get_or_create(
                quote=quote,
                defaults={"created_by": request.user, "updated_by": request.user},
            )
            if request.method == "GET":
                sheet = QuoteCostSheet.objects.select_related("quote").prefetch_related("items").get(pk=sheet.pk)
                return Response(QuoteCostSheetSerializer(sheet).data)
            if quote.status != Quote.Status.DRAFT:
                raise ValidationError("El costeo solo se puede modificar mientras la cotización está en borrador.")
            previous_item_count = sheet.items.count()
            serializer = QuoteCostSheetSerializer(sheet, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            sheet = serializer.save(updated_by=request.user)
            AuditEvent.objects.create(
                entity_type="quote_cost_sheet",
                entity_id=sheet.id,
                action="updated",
                from_value=str(previous_item_count),
                to_value=str(sheet.items.count()),
                actor=request.user,
            )
            sheet = QuoteCostSheet.objects.select_related("quote").prefetch_related("items").get(pk=sheet.pk)
            return Response(QuoteCostSheetSerializer(sheet).data)


    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        with transaction.atomic():
            quote = Quote.objects.select_for_update().get(pk=pk)
            if quote.status != Quote.Status.DRAFT:
                raise ValidationError("Solo un borrador puede enviarse.")
            if not quote.lines.exists():
                raise ValidationError("Agrega al menos un concepto antes de enviar.")
            if quote.valid_until and quote.valid_until < timezone.localdate():
                raise ValidationError("La vigencia de la cotización ya terminó.")
            opportunity = Opportunity.objects.select_for_update().get(pk=quote.opportunity_id) if quote.opportunity_id else None
            if opportunity and opportunity.stage in {Opportunity.Stage.WON, Opportunity.Stage.LOST}:
                raise ValidationError("No se puede enviar una cotización ligada a una oportunidad cerrada.")
            quote.status = Quote.Status.SENT
            quote.save(update_fields=["status", "updated_at"])
            AuditEvent.objects.create(entity_type="quote", entity_id=quote.id, action="sent", from_value=Quote.Status.DRAFT, to_value=Quote.Status.SENT, actor=request.user)
            if opportunity and opportunity.stage in {Opportunity.Stage.NEW, Opportunity.Stage.QUALIFIED}:
                previous_stage = opportunity.stage
                opportunity.stage = Opportunity.Stage.PROPOSAL
                opportunity.probability = max(opportunity.probability, 50)
                opportunity.save(update_fields=["stage", "probability", "updated_at"])
                AuditEvent.objects.create(entity_type="opportunity", entity_id=quote.opportunity_id, action="quote_sent", from_value=previous_stage, to_value=Opportunity.Stage.PROPOSAL, actor=request.user)
        return Response(self.get_serializer(quote).data)

    @action(detail=True, methods=["post"], url_path="send-email")
    def send_email(self, request, pk=None):
        quote = self.get_queryset().filter(pk=pk).first()
        if quote is None:
            raise NotFound("No se encontró la cotización.")
        quote = Quote.objects.select_related("customer", "customer_contact").prefetch_related("lines").get(pk=quote.pk)
        if quote.status != Quote.Status.SENT:
            raise ValidationError("Marca la cotización como enviada antes de mandarla por correo.")
        recipient = _quote_recipient_email(quote)
        if not recipient:
            raise ValidationError("El destinatario seleccionado no tiene un correo registrado.")
        if not quote.lines.exists():
            raise ValidationError("La cotización no tiene conceptos.")
        public_url = settings.ERP_PUBLIC_URL.strip()
        parsed_public_url = urlsplit(public_url)
        if parsed_public_url.scheme not in {"http", "https"} or not parsed_public_url.netloc:
            raise ValidationError("Configura ERP_PUBLIC_URL con la dirección que recibirá el cliente.")
        token = quote_acceptance_token(quote)
        acceptance_path = reverse("quote-accept", kwargs={"token": token})
        acceptance_url = urljoin(public_url.rstrip("/") + "/", acceptance_path.lstrip("/"))

        subject = f"Cotización {quote.number} · Redmagna"
        rows_text = []
        rows_html = []
        for line in quote.lines.all():
            optional_label = " [Opcional]" if line.is_optional else ""
            rows_text.append(f"• {line.description}{optional_label} — {line.quantity} × ${line.unit_price:,.2f} · descuento {line.discount_percent:.2f}% · IVA {line.tax_rate:.2f}% = ${line.line_subtotal:,.2f}")
            rows_html.append(
                "<tr><td style=\"padding:8px;border-bottom:1px solid #e5e9ef\">"
                f"{escape(line.description)}{(' · Opcional' if line.is_optional else '')}</td><td style=\"padding:8px;text-align:right;border-bottom:1px solid #e5e9ef\">"
                f"{line.quantity}</td><td style=\"padding:8px;text-align:right;border-bottom:1px solid #e5e9ef\">"
                f"${line.unit_price:,.2f}</td><td style=\"padding:8px;text-align:right;border-bottom:1px solid #e5e9ef\">"
                f"{line.discount_percent:.2f}%</td><td style=\"padding:8px;text-align:right;border-bottom:1px solid #e5e9ef\">"
                f"{line.tax_rate:.2f}%</td><td style=\"padding:8px;text-align:right;border-bottom:1px solid #e5e9ef\">"
                f"${line.line_subtotal:,.2f}</td></tr>"
            )
        expiry = quote.valid_until.strftime("%d/%m/%Y") if quote.valid_until else "No especificada"
        payment_term_text = f"{quote.payment_term_days} días naturales desde la emisión de factura" if quote.payment_term_days is not None else "Sin plazo de pago predeterminado"
        payment_term_html = f"<br>Plazo de pago: {quote.payment_term_days} días naturales desde la emisión de factura" if quote.payment_term_days is not None else ""
        site_text = ""
        site_html = ""
        if quote.service_address:
            site_label = quote.service_site_name or "Domicilio acordado"
            site_text = f"\n\nSitio de servicio: {site_label} · {quote.service_address}"
            site_html = f"<p><strong>Sitio de servicio:</strong> {escape(site_label)} · {escape(quote.service_address)}"
            if quote.service_contact_name:
                site_text += f"\nContacto: {quote.service_contact_name}"
                site_html += f"<br>Contacto: {escape(quote.service_contact_name)}"
            if quote.service_contact_phone:
                site_text += f"\nTeléfono: {quote.service_contact_phone}"
                site_html += f"<br>Teléfono: {escape(quote.service_contact_phone)}"
            if quote.service_contact_email:
                site_text += f"\nCorreo: {quote.service_contact_email}"
                site_html += f"<br>Correo: {escape(quote.service_contact_email)}"
            site_html += "</p>"
        text_body = (
            f"Hola {quote.recipient_name_snapshot or quote.customer.name},\n\nTe compartimos el resumen de la cotización {quote.number}: {quote.title}.\n\n"
            + "\n".join(rows_text)
            + f"\n\nSubtotal: ${quote.subtotal:,.2f}\nImpuestos estimados: ${quote.tax_total:,.2f}"
            + f"\nTotal base: ${quote.total:,.2f}\nOpciones adicionales a elegir: ${quote.optional_total:,.2f}"
            + f"\nTotal con todas las opciones: ${quote.total + quote.optional_total:,.2f}\nVigencia: {expiry}\nPlazo de pago: {payment_term_text}{site_text}\n\n{quote.notes}\n\n"
            + f"Para revisar y aceptar esta propuesta: {acceptance_url}\n\n"
            "Esta propuesta no es un CFDI. Para revisar el documento completo, contacta a Redmagna."
        )
        html_body = (
            f"<p>Hola {escape(quote.recipient_name_snapshot or quote.customer.name)},</p><p>Te compartimos el resumen de la cotización "
            f"<strong>{escape(quote.number)}</strong>: {escape(quote.title)}.</p>"
            "<table style=\"border-collapse:collapse;width:100%;font-family:Arial,sans-serif\"><thead><tr>"
            "<th style=\"text-align:left;padding:8px\">Concepto</th><th style=\"text-align:right;padding:8px\">Cantidad</th>"
            "<th style=\"text-align:right;padding:8px\">Precio unitario</th><th style=\"text-align:right;padding:8px\">Descuento</th><th style=\"text-align:right;padding:8px\">IVA</th><th style=\"text-align:right;padding:8px\">Importe</th>"
            "</tr></thead><tbody>" + "".join(rows_html) + "</tbody></table>"
            f"<p>Subtotal: ${quote.subtotal:,.2f}<br>Impuestos estimados: ${quote.tax_total:,.2f}"
            f"<br><strong>Total base: ${quote.total:,.2f}</strong><br>Opciones adicionales a elegir: ${quote.optional_total:,.2f}"
            f"<br>Total con todas las opciones: ${quote.total + quote.optional_total:,.2f}<br>Vigencia: {expiry}{payment_term_html}</p>"
            + site_html
            + f"<p>{escape(quote.notes).replace(chr(10), '<br>')}</p>"
            f"<p><a href=\"{escape(acceptance_url)}\">Revisar y aceptar la propuesta</a></p>"
            "<p>Esta propuesta no es un CFDI. Para revisar el documento completo, contacta a Redmagna.</p>"
        )
        message = EmailMultiAlternatives(subject, text_body, to=[recipient])
        message.attach_alternative(html_body, "text/html")
        try:
            sent_count = message.send(fail_silently=False)
        except Exception as exc:
            raise ValidationError("No se pudo enviar el correo. Revisa la configuración SMTP e inténtalo de nuevo.") from exc
        if sent_count != 1:
            raise ValidationError("El servidor de correo no confirmó el envío.")
        AuditEvent.objects.create(
            entity_type="quote", entity_id=quote.id, action="emailed",
            from_value=Quote.Status.SENT, to_value=recipient[:32], actor=request.user,
        )
        return Response({"detail": "Cotización y enlace de aceptación enviados.", "recipient": recipient})

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        quote, _order = approve_quote(pk, actor=request.user)
        return Response(self.get_serializer(quote).data)

    @action(detail=True, methods=["post"], url_path="approve-discount")
    def approve_discount(self, request, pk=None):
        try:
            quote, created = approve_quote_discount(pk, request.user)
        except DjangoValidationError as error:
            detail = error.message_dict if hasattr(error, "message_dict") else error.messages
            raise ValidationError(detail) from error
        return Response({**self.get_serializer(quote).data, "discount_approval_created": created})

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        with transaction.atomic():
            quote = Quote.objects.select_for_update().get(pk=pk)
            if quote.status not in [Quote.Status.DRAFT, Quote.Status.SENT]:
                raise ValidationError("Solo un borrador o una cotización enviada pueden cancelarse aquí.")
            previous = quote.status
            quote.status = Quote.Status.CANCELLED
            quote.save(update_fields=["status", "updated_at"])
            AuditEvent.objects.create(entity_type="quote", entity_id=quote.id, action="cancelled", from_value=previous, to_value=Quote.Status.CANCELLED, actor=request.user)
        return Response(self.get_serializer(quote).data)

    @action(detail=True, methods=["post"])
    def revise(self, request, pk=None):
        quote = self.get_object()
        try:
            revision, created = revise_quote(quote.pk, request.user)
        except DjangoValidationError as error:
            detail = error.message_dict if hasattr(error, "message_dict") else error.messages
            raise ValidationError(detail) from error
        revision = self.get_queryset().get(pk=revision.pk)
        return Response(self.get_serializer(revision).data, status=201 if created else 200)


class QuoteTemplateViewSet(viewsets.ModelViewSet):
    queryset = QuoteTemplate.objects.select_related("created_by")
    serializer_class = QuoteTemplateSerializer
    permission_classes = [QuoteTemplatePermissions]
    http_method_names = ["get", "post", "patch", "head", "options"]
    search_fields = ["name", "title"]
    ordering_fields = ["name", "created_at"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get("active", "true").lower() in {"1", "true", "yes"}:
            queryset = queryset.filter(is_active=True)
        return queryset

    def perform_create(self, serializer):
        template = serializer.save(created_by=self.request.user)
        AuditEvent.objects.create(entity_type="quote_template", entity_id=template.id, action="created", to_value="active", actor=self.request.user)

    def perform_update(self, serializer):
        previous_active = serializer.instance.is_active
        template = serializer.save()
        action = "activated" if previous_active != template.is_active and template.is_active else "deactivated" if previous_active != template.is_active else "updated"
        AuditEvent.objects.create(entity_type="quote_template", entity_id=template.id, action=action, to_value="updated", actor=self.request.user)


class WorkLogReportQuerySerializer(serializers.Serializer):
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)

    def validate(self, attrs):
        today = timezone.localdate()
        attrs.setdefault("date_to", today)
        attrs.setdefault("date_from", today.replace(day=1))
        if attrs["date_from"] > attrs["date_to"]:
            raise serializers.ValidationError({"date_from": "La fecha inicial no puede ser posterior a la fecha final."})
        if (attrs["date_to"] - attrs["date_from"]).days > 365:
            raise serializers.ValidationError({"date_from": "Consulta un periodo máximo de un año."})
        return attrs


class WorkOrderViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = WorkOrder.objects.select_related("sales_order__quote__customer", "customer_site", "assigned_to", "customer_acceptance__captured_by").prefetch_related("sales_order__quote__lines", "time_logs__created_by", "checklist_items__completed_by", "material_requirements__product", "material_requirements__supply_location", "material_requirements__source_quote_line")
    serializer_class = WorkOrderSerializer
    search_fields = ["title", "sales_order__quote__number", "sales_order__quote__customer__name"]
    ordering_fields = ["created_at", "scheduled_start", "status"]
    permission_classes = [WorkOrderPermissions]

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if (not user.is_superuser and user.has_perm("sales.change_workorder")
                and not user.has_perm("sales.schedule_workorder")):
            queryset = queryset.filter(assigned_to=user)
        return queryset

    @action(detail=False, methods=["get"], url_path="hours-report")
    def hours_report(self, request):
        query = WorkLogReportQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        date_from = query.validated_data["date_from"]
        date_to = query.validated_data["date_to"]
        visible_work_orders = self.get_queryset().values("pk")
        logs = WorkLog.objects.filter(work_order_id__in=visible_work_orders, work_date__range=(date_from, date_to))
        by_order = logs.values(
            "work_order_id", "work_order__sales_order__quote__number", "work_order__title",
            "work_order__status", "work_order__sales_order__quote__customer__name",
        ).annotate(hours=Sum("hours"), entries=Count("id"), people=Count("created_by_id", distinct=True)).order_by(
            "work_order__sales_order__quote__customer__name", "work_order__sales_order__quote__number",
        )
        by_person = logs.values(
            "created_by_id", "created_by__first_name", "created_by__last_name", "created_by__username",
        ).annotate(hours=Sum("hours"), entries=Count("id"), work_orders=Count("work_order_id", distinct=True)).order_by(
            "created_by__last_name", "created_by__first_name", "created_by__username",
        )
        totals = logs.aggregate(
            hours=Sum("hours"), entries=Count("id"),
            work_orders=Count("work_order_id", distinct=True), people=Count("created_by_id", distinct=True),
        )
        return Response({
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "totals": {key: value or 0 for key, value in totals.items()},
            "by_work_order": [{
                "work_order_id": str(row["work_order_id"]),
                "number": row["work_order__sales_order__quote__number"],
                "title": row["work_order__title"],
                "status": row["work_order__status"],
                "customer_name": row["work_order__sales_order__quote__customer__name"],
                "hours": row["hours"],
                "entries": row["entries"],
                "people": row["people"],
            } for row in by_order],
            "by_person": [{
                "user_id": str(row["created_by_id"]),
                "name": " ".join(part for part in (row["created_by__first_name"], row["created_by__last_name"]) if part) or row["created_by__username"],
                "hours": row["hours"],
                "entries": row["entries"],
                "work_orders": row["work_orders"],
            } for row in by_person],
        })

    @action(detail=True, methods=["patch"], url_path=r"material-requirements/(?P<requirement_id>[^/.]+)/location")
    def assign_material_location(self, request, pk=None, requirement_id=None):
        with transaction.atomic():
            work_order = get_object_or_404(self.get_queryset().select_for_update(), pk=pk)
            if work_order.status not in {WorkOrder.Status.PLANNED, WorkOrder.Status.IN_PROGRESS, WorkOrder.Status.BLOCKED}:
                raise ValidationError("Solo se puede cambiar el destino de surtido de una orden activa.")
            requirement = get_object_or_404(
                WorkOrderMaterialRequirement.objects.select_for_update().select_related("supply_location"),
                pk=requirement_id,
                work_order=work_order,
            )
            location_input = WorkOrderMaterialLocationSerializer(data=request.data)
            location_input.is_valid(raise_exception=True)
            location = location_input.validated_data["supply_location"]
            has_allocations = StockMovement.objects.filter(
                work_order=work_order, product=requirement.product,
                kind__in=[StockMovement.Kind.ISSUE, StockMovement.Kind.RETURN],
            ).exists() or StockReservation.objects.filter(
                work_order=work_order, product=requirement.product, state=StockReservation.State.ACTIVE,
            ).exists() or StockUnit.objects.filter(
                work_order=work_order, product=requirement.product,
            ).exists()
            if has_allocations and requirement.supply_location_id != location.pk:
                raise ValidationError("Libera las reservas y resuelve los materiales ya surtidos antes de cambiar el destino.")
            previous = requirement.supply_location
            if previous.pk != location.pk:
                WorkOrderMaterialRequirement.objects.filter(pk=requirement.pk).update(supply_location=location)
                AuditEvent.objects.create(
                    entity_type="work_order", entity_id=work_order.id,
                    action="material_supply_location_updated", from_value=previous.code[:32],
                    to_value=location.code[:32], actor=request.user,
                )
                requirement.supply_location = location
        return Response(WorkOrderMaterialRequirementSerializer(requirement).data)

    @action(detail=True, methods=["get", "post"], parser_classes=[MultiPartParser, FormParser], permission_classes=[WorkOrderEvidencePermissions])
    def evidence(self, request, pk=None):
        work_order = self.get_object()
        if request.method == "GET":
            items = work_order.evidence.select_related("uploaded_by").all()
            return Response(WorkOrderEvidenceSerializer(items, many=True).data)
        try:
            content_length = int(request.META.get("CONTENT_LENGTH", "0"))
        except (TypeError, ValueError):
            content_length = 0
        if content_length > WorkOrderEvidence.MAX_BYTES + 64 * 1024:
            raise ValidationError({"file": "El archivo supera el límite de 10 MB."})
        serializer = WorkOrderEvidenceUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                evidence = serializer.save(work_order=work_order, uploaded_by=request.user)
                AuditEvent.objects.create(entity_type="work_order", entity_id=work_order.id, action="evidence_uploaded", to_value=str(evidence.id)[:32], actor=request.user)
        except DjangoValidationError as error:
            detail = error.message_dict if hasattr(error, "message_dict") else error.messages
            raise ValidationError(detail) from error
        return Response(WorkOrderEvidenceSerializer(evidence).data, status=201)

    @action(detail=True, methods=["get"], url_path=r"evidence/(?P<evidence_id>[^/.]+)/download", permission_classes=[WorkOrderEvidencePermissions])
    def evidence_download(self, request, pk=None, evidence_id=None):
        work_order = self.get_object()
        evidence = get_object_or_404(WorkOrderEvidence, pk=evidence_id, work_order=work_order)
        try:
            response = FileResponse(evidence.file.open("rb"), as_attachment=True, filename=evidence.original_name, content_type=evidence.content_type)
        except FileNotFoundError as error:
            raise NotFound("El archivo de evidencia no está disponible en el almacenamiento.") from error
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    @action(detail=True, methods=["get"])
    def checklist(self, request, pk=None):
        work_order = self.get_object()
        return Response(WorkOrderChecklistItemSerializer(work_order.checklist_items.all(), many=True).data)

    @action(detail=True, methods=["post"], url_path="checklist/add")
    def add_checklist_item(self, request, pk=None):
        serializer = WorkOrderChecklistItemCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            work_order = get_object_or_404(self.get_queryset().select_for_update(), pk=pk)
            if work_order.status in {WorkOrder.Status.DONE, WorkOrder.Status.CANCELLED}:
                raise ValidationError("No se puede agregar un punto a una orden terminada o cancelada.")
            if hasattr(work_order, "customer_acceptance"):
                raise ValidationError("La lista de una orden con conformidad del cliente ya no se puede cambiar.")
            item = WorkOrderChecklistItem.objects.create(work_order=work_order, created_by=request.user, **serializer.validated_data)
            AuditEvent.objects.create(entity_type="work_order", entity_id=work_order.id, action="checklist_item_added", to_value=str(item.id)[:32], actor=request.user)
        return Response(WorkOrderChecklistItemSerializer(item).data, status=201)

    @action(detail=True, methods=["patch"], url_path=r"checklist/(?P<item_id>[0-9a-fA-F-]{36})")
    def update_checklist_item(self, request, pk=None, item_id=None):
        serializer = WorkOrderChecklistItemUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            item_uuid = UUID(item_id)
        except (ValueError, TypeError, AttributeError) as error:
            raise ValidationError("El identificador del punto no es válido.") from error
        with transaction.atomic():
            work_order = get_object_or_404(self.get_queryset().select_for_update(), pk=pk)
            item = get_object_or_404(WorkOrderChecklistItem.objects.select_for_update(), pk=item_uuid, work_order=work_order)
            if work_order.status in {WorkOrder.Status.DONE, WorkOrder.Status.CANCELLED}:
                raise ValidationError("No se puede cambiar la lista de una orden terminada o cancelada.")
            if hasattr(work_order, "customer_acceptance"):
                raise ValidationError("La lista de una orden con conformidad del cliente ya no se puede cambiar.")
            completed = serializer.validated_data["is_completed"]
            if completed != item.is_completed:
                item.is_completed = completed
                item.completed_at = timezone.now() if completed else None
                item.completed_by = request.user if completed else None
                item.save(update_fields=["is_completed", "completed_at", "completed_by"])
                AuditEvent.objects.create(entity_type="work_order", entity_id=work_order.id, action="checklist_item_completed" if completed else "checklist_item_reopened", from_value=str(item.id)[:32], to_value="completed" if completed else "pending", actor=request.user)
        return Response(WorkOrderChecklistItemSerializer(item).data)

    @action(detail=True, methods=["post"], url_path="checklist/apply-template")
    def apply_checklist_template(self, request, pk=None):
        serializer = WorkOrderChecklistTemplateApplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        template_id = serializer.validated_data["template"].pk
        with transaction.atomic():
            work_order = get_object_or_404(self.get_queryset().select_for_update(), pk=pk)
            template = get_object_or_404(WorkOrderChecklistTemplate.objects.select_for_update(), pk=template_id, is_active=True)
            if work_order.status in {WorkOrder.Status.DONE, WorkOrder.Status.CANCELLED}:
                raise ValidationError("No se puede aplicar una plantilla a una orden terminada o cancelada.")
            if hasattr(work_order, "customer_acceptance"):
                raise ValidationError("La lista de una orden con conformidad del cliente ya no se puede cambiar.")
            if work_order.checklist_items.exists():
                raise ValidationError("La plantilla solo se puede aplicar cuando la lista de la orden está vacía.")
            WorkOrderChecklistItem.objects.bulk_create([
                WorkOrderChecklistItem(work_order=work_order, label=label, created_by=request.user)
                for label in template.items
            ])
            AuditEvent.objects.create(entity_type="work_order", entity_id=work_order.id, action="checklist_template_applied", to_value=str(template.id)[:32], actor=request.user)
        items = work_order.checklist_items.select_related("completed_by").all()
        return Response(WorkOrderChecklistItemSerializer(items, many=True).data, status=201)

    @action(detail=True, methods=["post"], url_path="customer-acceptance")
    def customer_acceptance(self, request, pk=None):
        serializer = WorkOrderCustomerAcceptanceInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        values.pop("customer_confirmed")
        try:
            with transaction.atomic():
                get_object_or_404(self.get_queryset().select_for_update(), pk=pk)
                acceptance = record_work_order_customer_acceptance(pk, request.user, **values)
        except DjangoValidationError as error:
            detail = error.message_dict if hasattr(error, "message_dict") else error.messages
            raise ValidationError(detail) from error
        return Response(self.get_serializer(self.get_queryset().get(pk=pk)).data, status=201)

    @action(detail=True, methods=["patch"])
    def schedule(self, request, pk=None):
        with transaction.atomic():
            work_order = get_object_or_404(self.get_queryset().select_for_update().select_related("assigned_to"), pk=pk)
            can_schedule = request.user.has_perm("sales.schedule_workorder")
            if not can_schedule:
                if work_order.status != WorkOrder.Status.IN_PROGRESS:
                    raise ValidationError("Solo se puede registrar una nota de cierre en una orden asignada que esté en curso.")
                if set(request.data.keys()) != {"completion_notes"}:
                    raise ValidationError("El perfil de Técnico solo puede guardar la nota de cierre de la orden asignada.")
            if work_order.status in [WorkOrder.Status.DONE, WorkOrder.Status.CANCELLED]:
                raise ValidationError("Una orden terminada o cancelada ya no se puede reprogramar ni editar.")
            serializer = WorkOrderScheduleSerializer(work_order, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            assignee = serializer.validated_data.get("assigned_to", work_order.assigned_to)
            scheduled_start = serializer.validated_data.get("scheduled_start", work_order.scheduled_start)
            scheduled_end = serializer.validated_data.get("scheduled_end", work_order.scheduled_end)
            if can_schedule and assignee and scheduled_start and scheduled_end:
                from django.contrib.auth import get_user_model

                User = get_user_model()
                User.objects.select_for_update().get(pk=assignee.pk)
                conflict = WorkOrder.objects.filter(
                    assigned_to_id=assignee.pk,
                    status__in=[WorkOrder.Status.PLANNED, WorkOrder.Status.IN_PROGRESS, WorkOrder.Status.BLOCKED],
                    scheduled_start__lt=scheduled_end,
                    scheduled_end__gt=scheduled_start,
                ).exclude(pk=work_order.pk).exists()
                if conflict:
                    raise ValidationError({"scheduled_start": "La persona asignada ya tiene otra orden activa en ese horario."})
            old_assignee = str(work_order.assigned_to_id or "")
            old_notes = work_order.completion_notes
            site_fields = ("service_site_name", "service_address", "service_contact_name", "service_contact_phone", "service_contact_email")
            old_site = (work_order.customer_site_id, *(getattr(work_order, field) for field in site_fields))
            serializer.save()
            if hasattr(work_order, "customer_acceptance") and old_notes != work_order.completion_notes:
                raise ValidationError("La nota de cierre no se puede editar después de registrar la conformidad del cliente.")
            new_site = (work_order.customer_site_id, *(getattr(work_order, field) for field in site_fields))
            site_changed = old_site != new_site
            if site_changed and hasattr(work_order, "customer_acceptance"):
                raise ValidationError("La ubicación y el contacto de servicio no se pueden cambiar después de registrar la conformidad del cliente.")
            if old_assignee != str(work_order.assigned_to_id or "") or old_notes != work_order.completion_notes or "scheduled_start" in serializer.validated_data or "scheduled_end" in serializer.validated_data:
                AuditEvent.objects.create(
                    entity_type="work_order",
                    entity_id=work_order.id,
                    action="schedule_updated",
                    from_value=old_assignee[:32],
                    to_value=str(work_order.assigned_to_id or "")[:32],
                    actor=request.user,
                )
            if site_changed:
                AuditEvent.objects.create(
                    entity_type="work_order",
                    entity_id=work_order.id,
                    action="service_site_updated",
                    from_value="ubicación/contacto",
                    to_value="actualizado",
                    actor=request.user,
                )
        return Response(self.get_serializer(work_order).data)

    @action(detail=False, methods=["get"], url_path="assignees")
    def assignees(self, request):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        users = User.objects.filter(is_active=True).order_by("first_name", "username")
        return Response([
            {"id": user.pk, "username": user.get_username(), "name": user.get_full_name() or user.get_username()}
            for user in users
        ])

    @action(detail=True, methods=["post"], url_path="log-hours")
    def log_hours(self, request, pk=None):
        with transaction.atomic():
            work_order = get_object_or_404(self.get_queryset().select_for_update(), pk=pk)
            if work_order.status != WorkOrder.Status.IN_PROGRESS:
                raise ValidationError("Solo se pueden registrar horas mientras la orden está en curso.")
            serializer = WorkLogInputSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            from django.contrib.auth import get_user_model

            actor = get_user_model().objects.select_for_update().get(pk=request.user.pk)
            work_date = serializer.validated_data.get("work_date") or timezone.localdate()
            day_total = WorkLog.objects.filter(created_by=actor, work_date=work_date).aggregate(total=Sum("hours"))["total"] or 0
            if day_total + serializer.validated_data["hours"] > 24:
                raise ValidationError("La suma de horas registradas por una persona no puede superar 24 en el mismo día.")
            log = WorkLog.objects.create(work_order=work_order, created_by=actor, **serializer.validated_data)
            AuditEvent.objects.create(
                entity_type="work_order",
                entity_id=work_order.id,
                action="work_hours_added",
                to_value=str(log.hours)[:32],
                actor=request.user,
            )
        return Response(WorkLogSerializer(log).data, status=201)

    @action(detail=True, methods=["post"])
    def transition(self, request, pk=None):
        target = request.data.get("status")
        allowed = {
            WorkOrder.Status.PLANNED: {WorkOrder.Status.IN_PROGRESS, WorkOrder.Status.CANCELLED},
            WorkOrder.Status.IN_PROGRESS: {WorkOrder.Status.BLOCKED, WorkOrder.Status.DONE},
            WorkOrder.Status.BLOCKED: {WorkOrder.Status.IN_PROGRESS, WorkOrder.Status.CANCELLED},
            WorkOrder.Status.DONE: set(),
            WorkOrder.Status.CANCELLED: set(),
        }
        with transaction.atomic():
            work_order = get_object_or_404(self.get_queryset().select_for_update(), pk=pk)
            if target not in allowed.get(work_order.status, set()):
                raise ValidationError("La transición solicitada no está permitida.")
            if target == WorkOrder.Status.CANCELLED and not request.user.has_perm("sales.schedule_workorder"):
                raise ValidationError("Solo Gerencia u Operaciones pueden cancelar una orden de trabajo.")
            if hasattr(work_order, "customer_acceptance") and target != WorkOrder.Status.DONE:
                raise ValidationError("La orden con conformidad del cliente solo puede pasar a terminada.")
            if target == WorkOrder.Status.DONE and not work_order.completion_notes.strip():
                raise ValidationError("Agrega una nota de cierre antes de terminar la orden de trabajo.")
            if target == WorkOrder.Status.DONE:
                checklist = list(work_order.checklist_items.values_list("is_completed", flat=True))
                if not checklist:
                    raise ValidationError("Agrega al menos un punto a la lista de verificación antes de cerrar la orden.")
                if not all(checklist):
                    raise ValidationError("Completa todos los puntos de la lista de verificación antes de cerrar la orden.")
            previous = work_order.status
            work_order.status = target
            work_order.save(update_fields=["status"])
            AuditEvent.objects.create(entity_type="work_order", entity_id=work_order.id, action="status_changed", from_value=previous, to_value=target, actor=request.user)
        return Response(self.get_serializer(work_order).data)

    @action(detail=True, methods=["post"], url_path="create-invoice")
    def create_invoice(self, request, pk=None):
        work_order = self.get_object()
        serializer = WorkOrderInvoiceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            invoice = create_invoice_from_work_order(work_order.pk, request.user, serializer.validated_data["lines"])
        except DjangoValidationError as error:
            raise ValidationError(error.messages) from error
        return Response(CustomerInvoiceSerializer(invoice, context=self.get_serializer_context()).data, status=201)
