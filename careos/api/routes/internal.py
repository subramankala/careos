from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from careos.app_context import context

router = APIRouter()


class PersonalizationRuleCreateRequest(BaseModel):
    tenant_id: str
    patient_id: str
    actor_participant_id: str
    rule_type: str
    rule_payload: dict = Field(default_factory=dict)
    expires_at: datetime


class MediationDecisionLogRequest(BaseModel):
    event_id: str
    tenant_id: str
    patient_id: str
    participant_id: str | None = None
    action: str
    reason: str
    policy_snapshot: dict = Field(default_factory=dict)
    personalization_snapshot: dict = Field(default_factory=dict)
    rendered_text: str = ""
    correlation_id: str
    idempotency_key: str


@router.get("/internal/resolve-context")
def resolve_context(phone_number: str = Query(...)) -> dict:
    participant = context.identity_service.resolve_by_phone(phone_number)
    if participant is None:
        raise HTTPException(status_code=404, detail="participant context not found")
    return participant.model_dump(mode="json")


@router.post("/internal/personalization/rules")
def create_personalization_rule(payload: PersonalizationRuleCreateRequest) -> dict:
    try:
        return context.personalization.create_rule(
            tenant_id=payload.tenant_id,
            patient_id=payload.patient_id,
            actor_participant_id=payload.actor_participant_id,
            rule_type=payload.rule_type,
            rule_payload=payload.rule_payload,
            expires_at=payload.expires_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/internal/personalization/rules/active")
def list_active_personalization_rules(tenant_id: str = Query(...), patient_id: str = Query(...)) -> dict:
    rows = context.personalization.active_rules(tenant_id=tenant_id, patient_id=patient_id)
    return {"rules": rows}


@router.post("/internal/mediation/decisions")
def log_mediation_decision(payload: MediationDecisionLogRequest) -> dict:
    inserted = context.store.log_mediation_decision(
        event_id=payload.event_id,
        tenant_id=payload.tenant_id,
        patient_id=payload.patient_id,
        participant_id=payload.participant_id,
        action=payload.action,
        reason=payload.reason,
        policy_snapshot=payload.policy_snapshot,
        personalization_snapshot=payload.personalization_snapshot,
        rendered_text=payload.rendered_text,
        correlation_id=payload.correlation_id,
        idempotency_key=payload.idempotency_key,
    )
    return {"ok": True, "inserted": inserted}
