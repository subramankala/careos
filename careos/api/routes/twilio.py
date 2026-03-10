from __future__ import annotations

import hashlib
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request, Response

from careos.app_context import context
from careos.integrations.twilio.twiml import message_response
from careos.integrations.twilio.validator import validate_signature

router = APIRouter()


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

    participant = context.identity_service.resolve_by_phone(sender)
    if participant is None:
        unknown = "We could not match this number to a CareOS profile. Ask your caregiver to complete onboarding."
        return Response(content=message_response(unknown), media_type="text/xml")

    is_new_inbound = context.messaging.log_inbound(
        tenant_id=participant.tenant_id,
        patient_id=participant.patient_id,
        participant_id=participant.participant_id,
        body=body,
        correlation_id=correlation_id,
    )
    if not is_new_inbound:
        return Response(content=message_response("Duplicate message received. No action taken."), media_type="text/xml")

    result = context.router.handle(body, participant)
    context.messaging.log_outbound(
        tenant_id=participant.tenant_id,
        patient_id=participant.patient_id,
        participant_id=participant.participant_id,
        body=result.text,
        correlation_id=correlation_id,
    )
    return Response(content=message_response(result.text), media_type="text/xml")
