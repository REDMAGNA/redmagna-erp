from django.core.exceptions import ValidationError as DjangoValidationError
from django.contrib.auth import get_user_model
from django.http import HttpResponseRedirect
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from inventory.models import StockUnit
from .models import SupportTicket
from .permissions import SupportTicketPermissions
from .serializers import SupportAssetSerializer, SupportTicketSerializer, TicketMessageInputSerializer, TicketMessageSerializer, TicketTransitionSerializer
from .services import add_portal_ticket_reply, add_ticket_message, send_ticket_portal_link, support_ticket_from_portal_token, transition_ticket


@never_cache
@require_http_methods(["GET", "POST"])
def support_ticket_portal(request, token):
    try:
        ticket = support_ticket_from_portal_token(token)
    except DjangoValidationError as error:
        status = 410 if "venció" in " ".join(error.messages).lower() or "ya no está vigente" in " ".join(error.messages).lower() else 404
        response = render(request, "support/portal_unavailable.html", {"message": error.messages[0]}, status=status)
    else:
        reply_error = ""
        form_values = {"sender_name": "", "sender_email": "", "body": ""}
        if request.method == "POST":
            form_values = {
                "sender_name": request.POST.get("sender_name", "").strip(),
                "sender_email": request.POST.get("sender_email", "").strip(),
                "body": request.POST.get("body", "").strip(),
            }
            try:
                add_portal_ticket_reply(ticket.pk, **form_values)
            except DjangoValidationError as error:
                reply_error = error.messages[0]
            else:
                return HttpResponseRedirect(reverse("support-ticket-portal", kwargs={"token": token}) + "?enviado=1")
        response = render(request, "support/ticket_portal.html", {
            "ticket": ticket,
            "public_messages": ticket.portal_messages,
            "reply_error": reply_error,
            "form_values": form_values,
            "reply_sent": request.GET.get("enviado") == "1",
            "can_reply": ticket.status in {SupportTicket.Status.NEW, SupportTicket.Status.IN_PROGRESS, SupportTicket.Status.WAITING_CUSTOMER},
        }, status=400 if reply_error else 200)
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    response["Cache-Control"] = "no-store, private"
    return response


class SupportTicketViewSet(viewsets.ModelViewSet):
    queryset = SupportTicket.objects.select_related("customer", "work_order__sales_order__quote", "serial_unit__product", "serial_unit__customer", "assigned_to", "created_by").prefetch_related("messages__author", "messages__staff_notification", "events__actor")
    serializer_class = SupportTicketSerializer
    permission_classes = [SupportTicketPermissions]
    http_method_names = ["get", "post", "patch", "head", "options"]
    search_fields = ["number", "title", "description", "customer__name"]
    ordering_fields = ["number", "created_at", "updated_at", "status", "priority"]

    @action(detail=True, methods=["post"])
    def transition(self, request, pk=None):
        serializer = TicketTransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            ticket = transition_ticket(pk, serializer.validated_data["status"], request.user)
        except DjangoValidationError as error:
            raise ValidationError(error.messages) from error
        return Response(self.get_serializer(ticket).data)

    @action(detail=True, methods=["post"], url_path="add-note")
    def add_message(self, request, pk=None):
        serializer = TicketMessageInputSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        try:
            message = add_ticket_message(pk, request.user, serializer.validated_data["body"], is_public=serializer.validated_data.get("is_public", False))
        except DjangoValidationError as error:
            raise ValidationError(error.messages) from error
        return Response(TicketMessageSerializer(message).data, status=201)

    @action(detail=False, methods=["get"])
    def assignees(self, request):
        users = get_user_model().objects.filter(is_active=True).order_by("first_name", "last_name", "username")
        return Response([{"id": user.pk, "name": user.get_full_name() or user.get_username()} for user in users])

    @action(detail=False, methods=["get"])
    def assets(self, request):
        customer_id = serializers.UUIDField().run_validation(request.query_params.get("customer"))
        units = StockUnit.objects.select_related("product", "work_order__sales_order__quote").filter(
            customer_id=customer_id, state=StockUnit.State.INSTALLED,
        ).order_by("product__sku", "serial_number")
        return Response(SupportAssetSerializer(units, many=True).data)

    @action(detail=True, methods=["post"], url_path="send-portal-link")
    def send_portal_link(self, request, pk=None):
        try:
            result = send_ticket_portal_link(self.get_object().pk, request.user)
        except DjangoValidationError as error:
            raise ValidationError(error.messages) from error
        return Response(result)
