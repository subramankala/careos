from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from careos.app_context import context
from careos.domain.enums.core import Criticality, Flexibility, WinState

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


def _criticality_enum_for_dashboard(*, category: str, criticality: str, flexibility: str) -> str:
    category_normalized = str(category).strip().lower()
    criticality_normalized = str(criticality).strip().lower()
    flexibility_normalized = str(flexibility).strip().lower()
    if category_normalized == "medication":
        return "NON_NEGOTIABLE"
    if criticality_normalized == Criticality.HIGH.value and flexibility_normalized == Flexibility.RIGID.value:
        return "NON_NEGOTIABLE"
    if criticality_normalized in {Criticality.HIGH.value, Criticality.MEDIUM.value}:
        return "FLEXIBLE_CLINICAL"
    return "OPTIONAL_LIFESTYLE"


def _criticality_label(level: str) -> str:
    return {
        "NON_NEGOTIABLE": "Non-negotiable",
        "FLEXIBLE_CLINICAL": "Flexible clinical",
        "OPTIONAL_LIFESTYLE": "Optional lifestyle",
    }[level]


def _today_timeline(patient_id: str) -> list[dict]:
    return [item.model_dump(mode="json") for item in context.win_service.today(patient_id).timeline]


def _derive_escalations(patient_id: str) -> list[dict]:
    rows = []
    for item in _today_timeline(patient_id):
        current_state = str(item.get("current_state", ""))
        if current_state not in {WinState.MISSED.value, WinState.DUE.value, WinState.DELAYED.value}:
            continue
        dashboard_level = _criticality_enum_for_dashboard(
            category=str(item.get("category", "")),
            criticality=str(item.get("criticality", "")),
            flexibility=str(item.get("flexibility", "")),
        )
        severity = "high" if dashboard_level == "NON_NEGOTIABLE" else "medium"
        rows.append(
            {
                "id": str(item.get("win_instance_id", "")),
                "patient_id": patient_id,
                "type": f"{str(item.get('category', 'task')).lower()}_{current_state}",
                "severity": severity,
                "status": "open" if current_state == WinState.MISSED.value else "monitoring",
                "created_at": item.get("scheduled_start"),
                "summary": f"{item.get('title', 'Task')} is currently {current_state.replace('_', ' ')}.",
                "title": str(item.get("title", "Care event")),
            }
        )
    return rows[:10]


def _derive_recent_events(patient_id: str, limit: int) -> list[dict]:
    rows = []
    for item in reversed(_today_timeline(patient_id)):
        current_state = str(item.get("current_state", ""))
        title = str(item.get("title", "Care event"))
        category = str(item.get("category", "task"))
        event_type = f"{category}_{current_state}".strip("_")
        rows.append(
            {
                "id": str(item.get("win_instance_id", "")),
                "patient_id": patient_id,
                "event_type": event_type,
                "title": f"{title} [{current_state}]",
                "timestamp": item.get("scheduled_start"),
                "status": current_state,
            }
        )
    return rows[:limit]


def _derive_medications(patient_id: str) -> list[dict]:
    rows = []
    for item in _today_timeline(patient_id):
        if str(item.get("category", "")).lower() != "medication":
            continue
        rows.append(
            {
                "id": str(item.get("win_instance_id", "")),
                "patient_id": patient_id,
                "name": str(item.get("title", "")),
                "dosage": "",
                "schedule_time": item.get("scheduled_start"),
                "status": str(item.get("current_state", "pending")),
            }
        )
    return rows


def _derive_task_criticality(patient_id: str) -> list[dict]:
    seen: dict[str, dict] = {}
    for item in _today_timeline(patient_id):
        category = str(item.get("category", "task"))
        level = _criticality_enum_for_dashboard(
            category=category,
            criticality=str(item.get("criticality", "")),
            flexibility=str(item.get("flexibility", "")),
        )
        task_type = category.replace("_", " ").title()
        seen[task_type] = {
            "task_type": task_type,
            "criticality_level": level,
            "caregiver_visible_label": _criticality_label(level),
        }
    if seen:
        return list(seen.values())
    return [
        {
            "task_type": "Medication reminder",
            "criticality_level": "NON_NEGOTIABLE",
            "caregiver_visible_label": "Non-negotiable",
        }
    ]


@router.get("/internal/resolve-context")
def resolve_context(phone_number: str = Query(...)) -> dict:
    participant = context.identity_service.resolve_by_phone(phone_number)
    if participant is None:
        raise HTTPException(status_code=404, detail="participant context not found")
    return participant.model_dump(mode="json")


@router.get("/internal/dashboard/access")
def dashboard_access(actor_id: str = Query(...), patient_id: str = Query(...), tenant_id: str = Query(...), view: str = Query(...)) -> dict:
    if view != "caregiver_dashboard":
        raise HTTPException(status_code=400, detail="unsupported view")
    linked_patients = context.identity_service.list_linked_patients(actor_id)
    if not any(item.patient_id == patient_id and item.tenant_id == tenant_id for item in linked_patients):
        raise HTTPException(status_code=404, detail="active caregiver link not found")
    return {
        "authorization_id": f"caregiver-link:{actor_id}:{patient_id}",
        "tenant_id": tenant_id,
        "patient_id": patient_id,
        "actor_id": actor_id,
        "actor_type": "caregiver",
        "granted_by": patient_id,
        "scopes": [
            "view_dashboard",
            "view_escalations",
            "view_medications",
            "view_recent_events",
            "view_criticality",
        ],
        "status": "active",
        "effective_at": datetime.now(UTC).isoformat(),
        "revoked_at": None,
        "authorization_version": 1,
    }


@router.get("/internal/dashboard/patient-summary")
def patient_summary(patient_id: str = Query(...)) -> dict:
    profile = context.store.get_patient_profile(patient_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="patient not found")
    care_plan = context.store.get_active_care_plan_for_patient(patient_id)
    return {
        "id": profile["patient_id"],
        "tenant_id": profile["tenant_id"],
        "full_name": profile.get("display_name") or profile["patient_id"],
        "age": None,
        "sex": None,
        "primary_conditions": [],
        "care_plan_name": str((care_plan or {}).get("id") or "Active care plan"),
        "last_check_in_at": None,
        "timezone": profile["timezone"],
        "primary_language": profile.get("primary_language") or "en",
        "persona_type": profile.get("persona_type") or "caregiver_managed_elder",
        "risk_level": profile.get("risk_level") or "medium",
        "status": profile.get("status") or "active",
    }


@router.get("/internal/dashboard/escalations")
def dashboard_escalations(patient_id: str = Query(...)) -> dict:
    return {"items": _derive_escalations(patient_id)}


@router.get("/internal/dashboard/medications")
def dashboard_medications(patient_id: str = Query(...)) -> dict:
    return {"items": _derive_medications(patient_id)}


@router.get("/internal/dashboard/recent-events")
def dashboard_recent_events(patient_id: str = Query(...), limit: int = Query(default=10)) -> dict:
    return {"items": _derive_recent_events(patient_id, max(limit, 1))}


@router.get("/internal/dashboard/task-criticality")
def dashboard_task_criticality(patient_id: str = Query(...)) -> dict:
    return {"items": _derive_task_criticality(patient_id)}


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
