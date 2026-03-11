from __future__ import annotations

import hashlib
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request, Response

from careos.app_context import context
from careos.domain.models.api import LinkedPatientSummary, ParticipantIdentity
from careos.integrations.twilio.twiml import message_response
from careos.integrations.twilio.validator import validate_signature

router = APIRouter()


def _patients_prompt(patients: list[LinkedPatientSummary], active_patient_id: str | None = None) -> str:
    lines = ["Multiple patients are linked to this number."]
    for index, patient in enumerate(patients, start=1):
        marker = " *" if active_patient_id and patient.patient_id == active_patient_id else ""
        lines.append(f"{index}. {patient.display_name} ({patient.timezone}){marker}")
    lines.append("Reply: use <number>")
    return "\n".join(lines)


def _parse_use_target(raw_body: str) -> str | None:
    parts = raw_body.strip().split(maxsplit=1)
    if len(parts) != 2:
        return None
    if parts[0].lower() != "use":
        return None
    return parts[1].strip()


def _resolve_use_target(target: str, linked_patients: list[LinkedPatientSummary]) -> LinkedPatientSummary | None:
    if not target:
        return None
    if target.isdigit():
        index = int(target)
        if index < 1 or index > len(linked_patients):
            return None
        return linked_patients[index - 1]
    for patient in linked_patients:
        if patient.patient_id == target:
            return patient
    return None


def _resolve_context_for_message(
    body: str,
    identity: ParticipantIdentity,
    linked_patients: list[LinkedPatientSummary],
) -> tuple[str, str | None]:
    normalized = body.strip().lower()
    active_patient_id = context.identity_service.get_active_patient_context(identity.participant_id)

    if len(linked_patients) == 0:
        return ("We could not match this number to a CareOS profile. Ask your caregiver to complete onboarding.", None)

    use_target = _parse_use_target(body)
    if use_target is not None:
        selected = _resolve_use_target(use_target, linked_patients)
        if selected is None:
            if len(linked_patients) > 1:
                return ("Invalid selection.\n" + _patients_prompt(linked_patients, active_patient_id), None)
            return ("Invalid selection.", None)
        try:
            context.identity_service.set_active_patient_context(
                identity.participant_id,
                selected.patient_id,
                "whatsapp_use_command",
            )
        except ValueError:
            return ("Could not switch patient context safely. Please try again.", None)
        return (f"Switched to {selected.display_name} ({selected.timezone}).", selected.patient_id)

    if len(linked_patients) == 1:
        only = linked_patients[0]
        if active_patient_id != only.patient_id:
            context.identity_service.set_active_patient_context(identity.participant_id, only.patient_id, "auto_single_link")
        return ("", only.patient_id)

    if normalized in {"patients", "switch"}:
        return (_patients_prompt(linked_patients, active_patient_id), None)

    if normalized in {"whoami", "profile"} and not active_patient_id:
        text = (
            f"You are {identity.participant_role.value}. Active patient: none selected.\n"
            + _patients_prompt(linked_patients, None)
        )
        return (text, None)

    if active_patient_id is None:
        return (_patients_prompt(linked_patients, None), None)

    if active_patient_id not in {item.patient_id for item in linked_patients}:
        context.identity_service.clear_active_patient_context(identity.participant_id)
        return (_patients_prompt(linked_patients, None), None)

    return ("", active_patient_id)


@router.post("/twilio/webhook")
async def twilio_webhook(request: Request) -> Response:
    body_bytes = await request.body()
    try:
        decoded = body_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid request encoding") from exc

    parsed = parse_qs(decoded, keep_blank_values=True)
    payload = {key: values[0] if values else "" for key, values in parsed.items()}

    if not validate_signature(request, payload):
        raise HTTPException(status_code=403, detail="invalid twilio signature")

    sender = payload.get("From", "").strip()
    if not sender:
        raise HTTPException(status_code=400, detail="missing sender")
    body = payload.get("Body", "")
    correlation_id = payload.get("MessageSid")
    if correlation_id is None or not correlation_id.strip():
        correlation_id = f"fallback_{hashlib.sha256(body_bytes).hexdigest()}"

    identity = context.identity_service.resolve_participant_by_phone(sender)
    if identity is None:
        unknown = "We could not match this number to a CareOS profile. Ask your caregiver to complete onboarding."
        return Response(content=message_response(unknown), media_type="text/xml")

    linked_patients = context.identity_service.list_linked_patients(identity.participant_id)
    preflight_text, selected_patient_id = _resolve_context_for_message(body, identity, linked_patients)
    if selected_patient_id is None:
        return Response(content=message_response(preflight_text), media_type="text/xml")

    participant = context.identity_service.resolve_by_phone(sender)
    if participant is None:
        return Response(content=message_response("Could not resolve active patient context."), media_type="text/xml")

    is_new_inbound = context.messaging.log_inbound(
        tenant_id=participant.tenant_id,
        patient_id=participant.patient_id,
        participant_id=participant.participant_id,
        body=body,
        correlation_id=correlation_id,
    )
    if not is_new_inbound:
        return Response(content=message_response("Duplicate message received. No action taken."), media_type="text/xml")

    if preflight_text:
        context.messaging.log_outbound(
            tenant_id=participant.tenant_id,
            patient_id=participant.patient_id,
            participant_id=participant.participant_id,
            body=preflight_text,
            correlation_id=correlation_id,
        )
        return Response(content=message_response(preflight_text), media_type="text/xml")

    result = context.router.handle(body, participant)
    context.messaging.log_outbound(
        tenant_id=participant.tenant_id,
        patient_id=participant.patient_id,
        participant_id=participant.participant_id,
        body=result.text,
        correlation_id=correlation_id,
    )
    return Response(content=message_response(result.text), media_type="text/xml")
