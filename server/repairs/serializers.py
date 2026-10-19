from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from inventory.models import StockUnit
from support.models import SupportTicket
from .models import RepairCase, RepairCaseEvent


class RepairCaseEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = RepairCaseEvent
        fields = ["action", "from_status", "to_status", "detail", "actor_name", "occurred_at"]
        read_only_fields = fields

    def get_actor_name(self, obj):
        return obj.actor.get_full_name() or obj.actor.get_username()


class RepairCaseSerializer(serializers.ModelSerializer):
    ticket = serializers.PrimaryKeyRelatedField(queryset=SupportTicket.objects.select_related("serial_unit", "customer"), write_only=True)
    ticket_number = serializers.CharField(source="ticket.number", read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    serial_number = serializers.CharField(source="serial_unit.serial_number", read_only=True)
    product_name = serializers.CharField(source="serial_unit.product.name", read_only=True)
    warranty_until = serializers.DateField(source="serial_unit.warranty_until", read_only=True, allow_null=True)
    created_by_name = serializers.SerializerMethodField()
    authorized_by_name = serializers.SerializerMethodField()
    custody_received_by_name = serializers.SerializerMethodField()
    custody_returned_by_name = serializers.SerializerMethodField()
    events = RepairCaseEventSerializer(many=True, read_only=True)

    class Meta:
        model = RepairCase
        fields = ["id", "number", "ticket", "ticket_number", "customer", "customer_name", "serial_unit", "serial_number", "product_name", "warranty_until", "status", "warranty_review", "custody_status", "intake_condition", "custody_received_at", "custody_received_by_name", "return_condition", "custody_returned_at", "custody_returned_by_name", "reported_issue", "diagnosis", "proposed_work", "authorization_record", "authorized_by_name", "authorized_at", "created_by_name", "created_at", "updated_at", "events"]
        read_only_fields = ["id", "number", "customer", "serial_unit", "status", "custody_status", "intake_condition", "custody_received_at", "custody_received_by_name", "return_condition", "custody_returned_at", "custody_returned_by_name", "reported_issue", "authorization_record", "authorized_by_name", "authorized_at", "created_by_name", "created_at", "updated_at", "events"]

    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() or obj.created_by.get_username()

    def get_authorized_by_name(self, obj):
        return (obj.authorized_by.get_full_name() or obj.authorized_by.get_username()) if obj.authorized_by_id else ""

    def get_custody_received_by_name(self, obj):
        return (obj.custody_received_by.get_full_name() or obj.custody_received_by.get_username()) if obj.custody_received_by_id else ""

    def get_custody_returned_by_name(self, obj):
        return (obj.custody_returned_by.get_full_name() or obj.custody_returned_by.get_username()) if obj.custody_returned_by_id else ""

    def validate_ticket(self, ticket):
        if not ticket.serial_unit_id:
            raise serializers.ValidationError("Vincula primero un equipo instalado al ticket.")
        if ticket.status == SupportTicket.Status.CANCELLED:
            raise serializers.ValidationError("No se puede abrir una reparación desde un ticket cancelado.")
        if ticket.serial_unit.state != StockUnit.State.INSTALLED or ticket.serial_unit.customer_id != ticket.customer_id:
            raise serializers.ValidationError("El ticket debe referir a un equipo instalado del mismo cliente.")
        if RepairCase.objects.filter(ticket=ticket).exists():
            raise serializers.ValidationError("Este ticket ya tiene un expediente de reparación.")
        return ticket

    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        ticket = validated_data.pop("ticket")
        ticket = SupportTicket.objects.select_for_update().select_related("serial_unit", "customer").get(pk=ticket.pk)
        if RepairCase.objects.filter(ticket=ticket).exists():
            raise serializers.ValidationError({"ticket": "Este ticket ya tiene un expediente de reparación."})
        try:
            case = RepairCase.objects.create(
                ticket=ticket,
                customer=ticket.customer,
                serial_unit=ticket.serial_unit,
                reported_issue=ticket.description,
                created_by=request.user,
                **validated_data,
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages) from exc
        RepairCaseEvent.objects.create(repair_case=case, action="created", to_status=case.status, detail=f"Expediente creado desde {ticket.number}.", actor=request.user)
        return case

    @transaction.atomic
    def update(self, instance, validated_data):
        validated_data.pop("ticket", None)
        changed = []
        for field in ("diagnosis", "proposed_work", "warranty_review"):
            if field in validated_data and getattr(instance, field) != validated_data[field]:
                setattr(instance, field, validated_data[field])
                changed.append(field)
        if not changed:
            return instance
        try:
            instance.save(update_fields=["diagnosis", "proposed_work", "warranty_review", "updated_at"])
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages) from exc
        RepairCaseEvent.objects.create(
            repair_case=instance,
            action="details_updated",
            detail="Campos actualizados: " + ", ".join(changed),
            actor=self.context["request"].user,
        )
        return instance


class RepairCaseTransitionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=RepairCase.Status.choices)
    authorization_record = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")
    note = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


class RepairCaseCustodySerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=[("receive", "Recibir físicamente"), ("return", "Devolver al cliente")])
    condition = serializers.CharField(min_length=10, max_length=1000, trim_whitespace=True)


