from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import RepairCase, RepairCaseEvent


ALLOWED_TRANSITIONS = {
    RepairCase.Status.RECEIVED: {RepairCase.Status.DIAGNOSIS, RepairCase.Status.CANCELLED},
    RepairCase.Status.DIAGNOSIS: {RepairCase.Status.WAITING_AUTHORIZATION, RepairCase.Status.UNREPAIRABLE, RepairCase.Status.CANCELLED},
    RepairCase.Status.WAITING_AUTHORIZATION: {RepairCase.Status.AUTHORIZED, RepairCase.Status.CANCELLED},
    RepairCase.Status.AUTHORIZED: {RepairCase.Status.IN_REPAIR, RepairCase.Status.CANCELLED},
    RepairCase.Status.IN_REPAIR: {RepairCase.Status.READY, RepairCase.Status.UNREPAIRABLE},
    RepairCase.Status.READY: {RepairCase.Status.CLOSED},
    RepairCase.Status.UNREPAIRABLE: {RepairCase.Status.CLOSED},
    RepairCase.Status.CLOSED: set(),
    RepairCase.Status.CANCELLED: set(),
}


@transaction.atomic
def transition_repair_case(case_id, target, actor, authorization_record="", note=""):
    case = RepairCase.objects.select_for_update().get(pk=case_id)
    if target not in ALLOWED_TRANSITIONS.get(case.status, set()):
        raise ValidationError(f"No se permite pasar de {case.get_status_display()} a {dict(RepairCase.Status.choices)[target]}.")
    if target == RepairCase.Status.WAITING_AUTHORIZATION and not (case.diagnosis.strip() and case.proposed_work.strip()):
        raise ValidationError("Registra diagnóstico y trabajo propuesto antes de solicitar autorización.")
    if target == RepairCase.Status.AUTHORIZED:
        record = (authorization_record or "").strip()
        if len(record) < 10:
            raise ValidationError({"authorization_record": "Registra la evidencia de autorización del cliente (mínimo 10 caracteres)."})
        case.authorization_record = record
        case.authorized_by = actor
        case.authorized_at = timezone.now()
    if target in {RepairCase.Status.CLOSED, RepairCase.Status.UNREPAIRABLE, RepairCase.Status.CANCELLED} and len((note or "").strip()) < 10:
        raise ValidationError({"note": "Agrega una nota de al menos 10 caracteres para dejar constancia del cierre, rechazo o cancelación."})
    if target == RepairCase.Status.CLOSED and case.custody_status == RepairCase.CustodyStatus.IN_CUSTODY:
        raise ValidationError({"status": "Registra la devolución física del equipo antes de cerrar el expediente."})
    before = case.status
    now = timezone.now()
    RepairCase.objects.filter(pk=case.pk).update(
        status=target,
        authorization_record=case.authorization_record,
        authorized_by=case.authorized_by,
        authorized_at=case.authorized_at,
        updated_at=now,
    )
    case.status = target
    case.updated_at = now
    RepairCaseEvent.objects.create(
        repair_case=case,
        action="status_changed",
        from_status=before,
        to_status=target,
        detail=(authorization_record.strip() if target == RepairCase.Status.AUTHORIZED else (note or "").strip())[:1000],
        actor=actor,
    )
    return case


@transaction.atomic
def update_repair_custody(case_id, action, actor, condition):
    case = RepairCase.objects.select_for_update().get(pk=case_id)
    observation = (condition or "").strip()
    if len(observation) < 10:
        raise ValidationError({"condition": "Describe la condición física y accesorios con al menos 10 caracteres."})
    before = case.custody_status
    now = timezone.now()
    if action == "receive":
        if before != RepairCase.CustodyStatus.NOT_RECEIVED:
            raise ValidationError({"action": "Este equipo ya fue recibido físicamente o su devolución ya quedó registrada."})
        if case.status in {RepairCase.Status.CLOSED, RepairCase.Status.CANCELLED}:
            raise ValidationError({"action": "No se puede recibir equipo en un expediente cerrado o cancelado."})
        new_status = RepairCase.CustodyStatus.IN_CUSTODY
        changes = {
            "custody_status": new_status,
            "intake_condition": observation,
            "custody_received_at": now,
            "custody_received_by": actor,
        }
        event_detail = f"Condición y accesorios al recibir: {observation}"
        event_action = "custody_received"
    elif action == "return":
        if before != RepairCase.CustodyStatus.IN_CUSTODY:
            raise ValidationError({"action": "El expediente no registra el equipo bajo custodia de Redmagna."})
        if case.status not in {RepairCase.Status.READY, RepairCase.Status.UNREPAIRABLE, RepairCase.Status.CANCELLED}:
            raise ValidationError({"action": "Para devolverlo, primero marca el equipo como listo, no reparable o cancela el expediente."})
        new_status = RepairCase.CustodyStatus.RETURNED
        changes = {
            "custody_status": new_status,
            "return_condition": observation,
            "custody_returned_at": now,
            "custody_returned_by": actor,
        }
        event_detail = f"Condición y accesorios al devolver: {observation}"
        event_action = "custody_returned"
    else:
        raise ValidationError({"action": "Acción de custodia no reconocida."})

    RepairCase.objects.filter(pk=case.pk).update(**changes, updated_at=now)
    case.refresh_from_db()
    RepairCaseEvent.objects.create(
        repair_case=case,
        action=event_action,
        from_status=before,
        to_status=new_status,
        detail=event_detail[:1000],
        actor=actor,
        occurred_at=now,
    )
    return case
