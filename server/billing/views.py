from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.storage import default_storage
from django.http import FileResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from django.utils.dateparse import parse_date

from sales.models import Customer

from .models import CustomerCreditNote, CustomerInvoice, FiscalDocument, Payment
from .permissions import BillingPermissions
from .providers.fel import FELConfigurationError, FELTransportError
from .reports import customer_statement, issued_cfdi_register, receivables_aging
from .serializers import CancelFiscalDocumentSerializer, CustomerCreditNoteSerializer, CustomerInvoiceSerializer, FiscalDocumentSerializer, PaymentSerializer, PrepareCreditNoteCFDISerializer, PrepareInvoiceCFDISerializer, PreparePaymentCFDISerializer, ReverseCustomerCreditNoteSerializer, ReversePaymentSerializer
from .services import CustomerCopyDeliveryError, cancel_fiscal_document, generate_fiscal_document_xml, open_invoice, post_customer_credit_note, post_payment, prepare_credit_note_cfdi, prepare_invoice_cfdi, prepare_payment_cfdi, query_fiscal_document, reverse_customer_credit_note, reverse_payment, send_fiscal_copy_to_customer, send_fiscal_document


class InvoiceViewSet(viewsets.ModelViewSet):
    queryset = CustomerInvoice.objects.select_related("customer", "sales_order", "created_by", "opened_by").prefetch_related("lines__catalog_product", "allocations", "reminders")
    serializer_class = CustomerInvoiceSerializer
    permission_classes = [BillingPermissions]
    http_method_names = ["get", "post", "put", "patch", "head", "options"]
    search_fields = ["number", "customer__name", "customer__rfc"]
    ordering_fields = ["number", "issue_date", "due_date", "state"]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=["get"], url_path="receivables-aging")
    def receivables_aging(self, request):
        raw_date = request.query_params.get("as_of")
        as_of = parse_date(raw_date) if raw_date else None
        if raw_date and as_of is None:
            raise ValidationError({"as_of": "Usa una fecha válida con formato AAAA-MM-DD."})
        return Response(receivables_aging(as_of))

    @action(detail=False, methods=["get"], url_path="customer-statement")
    def customer_statement(self, request):
        customer_id = request.query_params.get("customer_id")
        if not customer_id:
            raise ValidationError({"customer_id": "Selecciona un cliente para consultar su estado de cuenta."})
        raw_date = request.query_params.get("as_of")
        as_of = parse_date(raw_date) if raw_date else None
        if raw_date and as_of is None:
            raise ValidationError({"as_of": "Usa una fecha válida con formato AAAA-MM-DD."})
        try:
            customer = Customer.objects.get(pk=customer_id)
        except (Customer.DoesNotExist, ValueError, DjangoValidationError):
            raise ValidationError({"customer_id": "No se encontró el cliente seleccionado."})
        return Response(customer_statement(customer, as_of))

    @action(detail=True, methods=["post"])
    def open(self, request, pk=None):
        invoice = self.get_object()
        try:
            invoice = open_invoice(invoice.pk, request.user)
        except DjangoValidationError as error:
            raise ValidationError(error.messages)
        return Response(self.get_serializer(invoice).data)

    @action(detail=True, methods=["post"], url_path="prepare-cfdi")
    def prepare_cfdi(self, request, pk=None):
        invoice = self.get_object()
        input_serializer = PrepareInvoiceCFDISerializer(data=request.data, context={"invoice": invoice})
        input_serializer.is_valid(raise_exception=True)
        try:
            document, created = prepare_invoice_cfdi(invoice.pk, request.user, **input_serializer.validated_data)
        except DjangoValidationError as error:
            raise ValidationError(error.messages) from error
        return Response(FiscalDocumentSerializer(document).data, status=201 if created else 200)


class PaymentViewSet(viewsets.ModelViewSet):
    queryset = Payment.objects.select_related("customer", "created_by", "posted_by").prefetch_related("allocations__invoice")
    serializer_class = PaymentSerializer
    permission_classes = [BillingPermissions]
    http_method_names = ["get", "post", "put", "patch", "head", "options"]
    search_fields = ["number", "reference", "customer__name"]
    ordering_fields = ["number", "received_at", "state"]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"])
    def post(self, request, pk=None):
        payment = self.get_object()
        try:
            payment = post_payment(payment.pk, request.user)
        except DjangoValidationError as error:
            raise ValidationError(error.messages)
        return Response(self.get_serializer(payment).data)

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        serializer = ReversePaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payment = reverse_payment(pk, request.user, **serializer.validated_data)
        except DjangoValidationError as error:
            raise ValidationError(error.message_dict if hasattr(error, "message_dict") else error.messages) from error
        return Response(self.get_serializer(payment).data)

    @action(detail=True, methods=["post"], url_path="prepare-payment-cfdi")
    def prepare_payment_cfdi(self, request, pk=None):
        payment = self.get_object()
        input_serializer = PreparePaymentCFDISerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        try:
            document, created = prepare_payment_cfdi(payment.pk, request.user, **input_serializer.validated_data)
        except DjangoValidationError as error:
            raise ValidationError(error.messages) from error
        return Response(FiscalDocumentSerializer(document).data, status=201 if created else 200)


class CustomerCreditNoteViewSet(viewsets.ModelViewSet):
    queryset = CustomerCreditNote.objects.select_related("invoice", "invoice__customer", "created_by", "posted_by").prefetch_related("lines__invoice_line")
    serializer_class = CustomerCreditNoteSerializer
    permission_classes = [BillingPermissions]
    http_method_names = ["get", "post", "put", "patch", "head", "options"]
    search_fields = ["number", "invoice__number", "invoice__customer__name"]
    ordering_fields = ["number", "issue_date", "state"]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"])
    def post(self, request, pk=None):
        try:
            note = post_customer_credit_note(pk, request.user)
        except DjangoValidationError as error:
            raise ValidationError(error.message_dict if hasattr(error, "message_dict") else error.messages) from error
        return Response(self.get_serializer(note).data)

    @action(detail=True, methods=["post"], url_path="prepare-cfdi")
    def prepare_cfdi(self, request, pk=None):
        note = self.get_object()
        input_serializer = PrepareCreditNoteCFDISerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        try:
            document, created = prepare_credit_note_cfdi(note.pk, request.user, **input_serializer.validated_data)
        except DjangoValidationError as error:
            raise ValidationError(error.message_dict if hasattr(error, "message_dict") else error.messages) from error
        return Response(FiscalDocumentSerializer(document).data, status=201 if created else 200)

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        serializer = ReverseCustomerCreditNoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            note = reverse_customer_credit_note(pk, request.user, **serializer.validated_data)
        except DjangoValidationError as error:
            raise ValidationError(error.message_dict if hasattr(error, "message_dict") else error.messages) from error
        return Response(self.get_serializer(note).data)


class FiscalDocumentViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = FiscalDocument.objects.select_related("invoice", "credit_note", "payment").prefetch_related("events")
    serializer_class = FiscalDocumentSerializer
    permission_classes = [BillingPermissions]
    search_fields = ["cfdi_uuid", "provider_code", "recipient_rfc"]
    ordering_fields = ["created_at", "stamped_at", "state"]

    @action(detail=False, methods=["get"], url_path="issued-register")
    def issued_register(self, request):
        raw_from = request.query_params.get("date_from")
        raw_to = request.query_params.get("date_to")
        date_from = parse_date(raw_from) if raw_from else None
        date_to = parse_date(raw_to) if raw_to else None
        if raw_from and date_from is None:
            raise ValidationError({"date_from": "Usa una fecha válida con formato AAAA-MM-DD."})
        if raw_to and date_to is None:
            raise ValidationError({"date_to": "Usa una fecha válida con formato AAAA-MM-DD."})
        if date_from and date_to and date_from > date_to:
            raise ValidationError({"date_to": "La fecha final no puede ser anterior a la inicial."})
        try:
            return Response(issued_cfdi_register(date_from, date_to))
        except DjangoValidationError as error:
            detail = error.message_dict if hasattr(error, "message_dict") else error.messages
            raise ValidationError(detail) from error

    @action(detail=True, methods=["get"], url_path="pdf")
    def download_pdf(self, request, pk=None):
        document = self.get_object()
        expected_key = f"fiscal_documents/{document.pk}/{document.pk}.pdf"
        if not document.pdf_storage_key or document.pdf_storage_key != expected_key:
            raise ValidationError("Este CFDI timbrado no tiene una representación PDF disponible.")
        try:
            stream = default_storage.open(expected_key, "rb")
        except FileNotFoundError as error:
            raise ValidationError("El PDF no está disponible en el almacenamiento privado del servidor.") from error
        filename = f"CFDI-{document.cfdi_uuid or document.pk}.pdf"
        response = FileResponse(stream, as_attachment=True, filename=filename, content_type="application/pdf")
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    @action(detail=True, methods=["post"], url_path="generate-xml")
    def generate_xml(self, request, pk=None):
        document = self.get_object()
        if document.document_type == FiscalDocument.DocumentType.PAYMENT and request.data.get("confirm_payment_snapshot") is not True:
            raise ValidationError({"confirm_payment_snapshot": "Revisa impuestos, importes y CFDI relacionados; envía true para confirmar antes de firmar el complemento."})
        if document.document_type == FiscalDocument.DocumentType.CREDIT_NOTE and request.data.get("confirm_credit_note_snapshot") is not True:
            raise ValidationError({"confirm_credit_note_snapshot": "Revisa receptor, CFDI ingreso relacionado, forma e impuestos; envía true para confirmar antes de firmar el egreso."})
        try:
            document = generate_fiscal_document_xml(
                document.pk, request.user,
                confirm_payment_snapshot=request.data.get("confirm_payment_snapshot") is True,
                confirm_credit_note_snapshot=request.data.get("confirm_credit_note_snapshot") is True,
            )
        except DjangoValidationError as error:
            raise ValidationError(error.messages) from error
        return Response(self.get_serializer(document).data)

    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        document = self.get_object()
        try:
            document = send_fiscal_document(document.pk, request.user)
        except DjangoValidationError as error:
            raise ValidationError(error.messages) from error
        except (FELConfigurationError, FELTransportError) as error:
            service_error = APIException(str(error))
            service_error.status_code = 503
            raise service_error from error
        return Response(self.get_serializer(document).data)

    @action(detail=True, methods=["post"], url_path="send-customer-copy")
    def send_customer_copy(self, request, pk=None):
        document = self.get_object()
        try:
            document = send_fiscal_copy_to_customer(document.pk, request.user)
        except DjangoValidationError as error:
            raise ValidationError(error.messages) from error
        except CustomerCopyDeliveryError as error:
            service_error = APIException(str(error))
            service_error.status_code = 503
            raise service_error from error
        return Response(self.get_serializer(document).data)

    @action(detail=True, methods=["post"])
    def query(self, request, pk=None):
        document = self.get_object()
        try:
            document = query_fiscal_document(document.pk, request.user)
        except DjangoValidationError as error:
            raise ValidationError(error.messages) from error
        except (FELConfigurationError, FELTransportError) as error:
            service_error = APIException(str(error))
            service_error.status_code = 503
            raise service_error from error
        return Response(self.get_serializer(document).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        document = self.get_object()
        input_serializer = CancelFiscalDocumentSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        try:
            document = cancel_fiscal_document(document.pk, request.user, **input_serializer.validated_data)
        except DjangoValidationError as error:
            raise ValidationError(error.messages) from error
        except (FELConfigurationError, FELTransportError) as error:
            if isinstance(error, FELConfigurationError):
                service_error = APIException(str(error))
                service_error.status_code = 503
                raise service_error from error
            service_error = APIException("FEL no confirmó el resultado de la cancelación. El estado queda pendiente; verifica SAT/FEL antes de volver a intentar.")
            service_error.status_code = 503
            raise service_error from error
        return Response(self.get_serializer(document).data)
