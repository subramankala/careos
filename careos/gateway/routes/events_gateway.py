from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from careos.gateway.careos_adapter import CareOSAdapter
from careos.gateway.outbound_policy import decide_outbound_action, normalize_policy
from careos.gateway.twilio_sender import build_sender

router = APIRouter()
adapter = CareOSAdapter()


class CareOSEventEnvelope(BaseModel):
    event_id: str
    tenant_id: str
    patient_id: str
    participant_id: str | None = None
    event_type: str
    due_at: datetime
    to_number: str
    suppression_policy: dict[str, Any] = Field(default_factory=dict)
    message_payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str = ""


@router.post("/gateway/careos/events")
def handle_careos_event(payload: CareOSEventEnvelope) -> dict:
    policy = normalize_policy(payload.suppression_policy)
    rules_resp = adapter.list_active_personalization_rules(
        tenant_id=payload.tenant_id,
        patient_id=payload.patient_id,
    )
    active_rules = list(rules_resp.get("rules", []))
    decision = decide_outbound_action(
        event_policy=policy,
        active_rules=active_rules,
        now=datetime.now(UTC),
    )

    rendered_text = str(payload.message_payload.get("body") or payload.message_payload.get("title") or "").strip()
    if not rendered_text:
        rendered_text = f"CareOS reminder: {payload.event_type}"

    decision_key = f"mediation:{payload.event_id}:{decision.action}:{payload.to_number}"
    log_result = adapter.log_mediation_decision(
        event_id=payload.event_id,
        tenant_id=payload.tenant_id,
        patient_id=payload.patient_id,
        participant_id=payload.participant_id,
        action=decision.action,
        reason=decision.reason,
        policy_snapshot=policy,
        personalization_snapshot={"active_rules": active_rules},
        rendered_text=rendered_text if decision.action == "send" else "",
        correlation_id=payload.correlation_id or payload.event_id,
        idempotency_key=decision_key,
    )
    inserted = bool(log_result.get("inserted", False))
    if not inserted:
        return {"ok": True, "deduped": True, "event_id": payload.event_id, "action": decision.action}

    if decision.action == "send":
        sender = build_sender()
        if sender is None:
            return {
                "ok": False,
                "event_id": payload.event_id,
                "action": "send",
                "error": "twilio_sender_not_configured",
            }
        sid = sender.send_text(to_number=payload.to_number, body=rendered_text)
        return {"ok": True, "event_id": payload.event_id, "action": "send", "twilio_message_sid": sid}

    if decision.action == "delay":
        return {
            "ok": True,
            "event_id": payload.event_id,
            "action": "delay",
            "delay_until": decision.delay_until.isoformat() if decision.delay_until else None,
        }

    return {"ok": True, "event_id": payload.event_id, "action": "suppress"}
