from django.contrib.auth import get_user_model
from copy import deepcopy
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from inventory.models import StockUnit
from sales.models import Customer, WorkOrder
from .models import SupportSlaPolicy, SupportTicket, SupportTicketEvent, SupportTicketMessage, SupportTicketNotification


class TicketMessageSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    staff_notification_status = serializers.SerializerMethodField()

    class Meta:
        model = SupportTicketMessage
        fields = ["id", "author", "author_name", "sender_name", "is_public", "body", "created_at", "staff_notification_status"]
        read_only_fields = fields

    def get_author_name(self, obj):
        if obj.author_id:
            return obj.author.get_full_name() or obj.author.get_username()
        return obj.sender_name or "Cliente"

    def get_staff_notification_status(self, obj):
        if obj.author_id:
            return "not_applicable"
        try:
            return obj.staff_notification.status
        except SupportTicketNotification.DoesNotExist:
            return "not_created"


class TicketEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = SupportTicketEvent
        fields = ["action", "from_status", "to_status", "detail", "actor_name", "actor_label", "occurred_at"]
        read_only_fields = fields

    def get_actor_name(self, obj):
        if obj.actor_id:
            return obj.actor.get_full_name() or obj.actor.get_username()
        return obj.actor_label or "Actor externo"


class SupportTicketSerializer(serializers.ModelSerializer):
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.filter(is_active=True))
    work_order = serializers.PrimaryKeyRelatedField(queryset=WorkOrder.objects.select_related("sales_order__quote"), allow_null=True, required=False)
    serial_unit = serializers.PrimaryKeyRelatedField(queryset=StockUnit.objects.filter(state=StockUnit.State.INSTALLED), allow_null=True, required=False)
    assigned_to = serializers.PrimaryKeyRelatedField(queryset=get_user_model().objects.filter(is_active=True), allow_null=True, required=False)
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    work_order_number = serializers.CharField(source="work_order.sales_order.quote.number", read_only=True, default="")
    serial_number = serializers.CharField(source="serial_unit.serial_number", read_only=True, default="")
    serial_product_name = serializers.CharField(source="serial_unit.product.name", read_only=True, default="")
    serial_warranty_until = serializers.DateField(source="serial_unit.warranty_until", read_only=True, allow_null=True, default=None)
    warranty_window_status = serializers.SerializerMethodField()
    sla_response_due_at = serializers.DateTimeField(read_only=True)
    sla_resolution_due_at = serializers.DateTimeField(read_only=True)
    sla_response_status = serializers.CharField(read_only=True)
    sla_resolution_status = serializers.CharField(read_only=True)
    assigned_to_name = serializers.CharField(source="assigned_to.get_full_name", read_only=True, default="Sin asignar")
    created_by_name = serializers.CharField(source="created_by.get_full_name", read_only=True)
    messages = TicketMessageSerializer(many=True, read_only=True)
    events = TicketEventSerializer(many=True, read_only=True)

    class Meta:
        model = SupportTicket
        fields = ["id", "number", "customer", "customer_name", "work_order", "work_order_number", "serial_unit", "serial_number", "serial_product_name", "serial_warranty_until", "warranty_window_status", "title", "description", "status", "priority", "channel", "assigned_to", "assigned_to_name", "created_by", "created_by_name", "created_at", "updated_at", "resolved_at", "closed_at", "sla_response_target_minutes", "sla_resolution_target_minutes", "sla_response_due_at", "sla_resolution_due_at", "sla_response_status", "sla_resolution_status", "first_response_at", "messages", "events"]
        read_only_fields = ["id", "number", "status", "created_by", "created_at", "updated_at", "resolved_at", "closed_at", "sla_response_target_minutes", "sla_resolution_target_minutes", "sla_response_due_at", "sla_resolution_due_at", "sla_response_status", "sla_resolution_status", "first_response_at", "messages", "events"]

    def get_warranty_window_status(self, obj):
        if not obj.serial_unit_id:
            return "not_applicable"
        warranty_until = obj.serial_unit.warranty_until
        if not warranty_until:
            return "unknown"
        reported_on = timezone.localtime(obj.created_at).date()
        return "recorded_date_valid" if warranty_until >= reported_on else "recorded_date_expired"

    def validate(self, attrs):
        work_order = attrs.get("work_order", getattr(self.instance, "work_order", None))
        customer = attrs.get("customer", getattr(self.instance, "customer", None))
        if work_order and customer and work_order.sales_order.quote.customer_id != customer.id:
            raise serializers.ValidationError({"work_order": "La orden de trabajo debe pertenecer al cliente del ticket."})
        serial_unit = attrs.get("serial_unit", getattr(self.instance, "serial_unit", None))
        if serial_unit and customer and (serial_unit.state != StockUnit.State.INSTALLED or serial_unit.customer_id != customer.id):
            raise serializers.ValidationError({"serial_unit": "Selecciona un equipo instalado que pertenezca al cliente del ticket."})
        if self.instance:
            try:
                repair_case = self.instance.repair_case
            except ObjectDoesNotExist:
                repair_case = None
            if repair_case and (
                getattr(customer, "pk", self.instance.customer_id) != repair_case.customer_id
                or getattr(serial_unit, "pk", self.instance.serial_unit_id) != repair_case.serial_unit_id
            ):
                raise serializers.ValidationError("No cambies el cliente o equipo de un ticket con expediente de reparación; conserva el vínculo histórico.")
        if "assigned_to" in attrs and not self.context["request"].user.has_perm("support.assign_supportticket"):
            raise serializers.ValidationError({"assigned_to": "No tienes permiso para asignar tickets de soporte."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        policy = SupportSlaPolicy.objects.filter(priority=validated_data.get("priority", SupportTicket.Priority.NORMAL)).first()
        snapshot = _sla_policy_snapshot(policy)
        ticket = SupportTicket.objects.create(
            created_by=request.user,
            **snapshot,
            **validated_data,
        )
        SupportTicketEvent.objects.create(ticket=ticket, action="created", to_status=ticket.status, actor=request.user)
        return ticket

    @transaction.atomic
    def update(self, instance, validated_data):
        previous_assignee = instance.assigned_to_id
        previous_priority = instance.priority
        previous_assignee_name = instance.assigned_to.get_full_name() or instance.assigned_to.get_username() if instance.assigned_to_id else "Sin asignar"
        new_assignee = validated_data.get("assigned_to")
        changed_assignment = "assigned_to" in validated_data and getattr(new_assignee, "pk", None) != previous_assignee
        ticket = super().update(instance, validated_data)
        if ticket.priority != previous_priority:
            policy = SupportSlaPolicy.objects.filter(priority=ticket.priority).first()
            snapshot = _sla_policy_snapshot(policy)
            for name, value in snapshot.items():
                setattr(ticket, name, value)
            ticket.save(update_fields=[*snapshot.keys(), "updated_at"])
            SupportTicketEvent.objects.create(
                ticket=ticket,
                action="sla_priority_changed",
                detail=f"Prioridad {previous_priority} → {ticket.priority}; se actualizaron los objetivos SLA configurados.",
                actor=self.context["request"].user,
            )
        if changed_assignment:
            new_assignee_name = ticket.assigned_to.get_full_name() or ticket.assigned_to.get_username() if ticket.assigned_to_id else "Sin asignar"
            SupportTicketEvent.objects.create(ticket=ticket, action="assignment_changed", detail=f"{previous_assignee_name} → {new_assignee_name}", actor=self.context["request"].user)
        SupportTicketEvent.objects.create(ticket=ticket, action="details_updated", actor=self.context["request"].user)
        return ticket


def _sla_policy_snapshot(policy):
    if not policy:
        return {
            "sla_response_target_minutes": None,
            "sla_resolution_target_minutes": None,
            "sla_weekly_schedule": {},
            "sla_calendar_timezone": "America/Mexico_City",
        }
    return {
        "sla_response_target_minutes": policy.first_response_minutes,
        "sla_resolution_target_minutes": policy.resolution_minutes,
        "sla_weekly_schedule": deepcopy(policy.weekly_schedule),
        "sla_calendar_timezone": policy.calendar_timezone,
    }


class TicketTransitionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=SupportTicket.Status.choices)


class TicketMessageInputSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=4000, trim_whitespace=True)
    is_public = serializers.BooleanField(required=False, default=False)

    def validate_body(self, value):
        if not value.strip():
            raise serializers.ValidationError("La nota no puede estar vacía.")
        return value

    def validate(self, attrs):
        if attrs.get("is_public") and not self.context["request"].user.has_perm("support.publish_supportticketmessage"):
            raise serializers.ValidationError({"is_public": "No tienes permiso para compartir respuestas con el cliente."})
        return attrs


class SupportAssetSerializer(serializers.ModelSerializer):
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    work_order_number = serializers.CharField(source="work_order.sales_order.quote.number", read_only=True, default="")

    class Meta:
        model = StockUnit
        fields = ["id", "serial_number", "product_sku", "product_name", "work_order_number", "installed_at", "warranty_until"]
        read_only_fields = fields
