from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .models import RepairCase
from .permissions import RepairCasePermissions
from .serializers import RepairCaseCustodySerializer, RepairCaseSerializer, RepairCaseTransitionSerializer
from .services import transition_repair_case, update_repair_custody


class RepairCaseViewSet(viewsets.ModelViewSet):
    queryset = RepairCase.objects.select_related("ticket", "customer", "serial_unit__product", "created_by", "authorized_by", "custody_received_by", "custody_returned_by").prefetch_related("events__actor")
    serializer_class = RepairCaseSerializer
    permission_classes = [RepairCasePermissions]
    http_method_names = ["get", "post", "patch", "head", "options"]
    search_fields = ["number", "ticket__number", "customer__name", "serial_unit__serial_number", "reported_issue"]
    ordering_fields = ["number", "created_at", "updated_at", "status"]

    def get_queryset(self):
        queryset = super().get_queryset()
        ticket_id = self.request.query_params.get("ticket")
        return queryset.filter(ticket_id=ticket_id) if ticket_id else queryset

    @action(detail=True, methods=["post"])
    def transition(self, request, pk=None):
        serializer = RepairCaseTransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            case = transition_repair_case(
                pk,
                serializer.validated_data["status"],
                request.user,
                serializer.validated_data.get("authorization_record", ""),
                serializer.validated_data.get("note", ""),
            )
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            raise ValidationError(detail) from exc
        return Response(self.get_serializer(case).data)

    @action(detail=True, methods=["post"])
    def custody(self, request, pk=None):
        serializer = RepairCaseCustodySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            case = update_repair_custody(
                pk,
                serializer.validated_data["action"],
                request.user,
                serializer.validated_data["condition"],
            )
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            raise ValidationError(detail) from exc
        return Response(self.get_serializer(case).data)
