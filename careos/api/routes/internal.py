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


class PatientClinicalFactCreateRequest(BaseModel):
    tenant_id: str
    patient_id: str
    actor_participant_id: str
    fact_key: str
    fact_value: dict = Field(default_factory=dict)
    summary: str
    source: str = "caregiver_reported"
    effective_at: datetime | None = None


class PatientObservationCreateRequest(BaseModel):
    tenant_id: str
    patient_id: str
    actor_participant_id: str
    observation_key: str
    observation_value: dict = Field(default_factory=dict)
    summary: str
    source: str = "caregiver_reported"
    observed_at: datetime | None = None
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


class GatewayPendingActionRequest(BaseModel):
    pending_key: str
    plan: dict = Field(default_factory=dict)
    expires_at: datetime


class CaregiverPresetUpdateRequest(BaseModel):
    actor_id: str
    patient_id: str
    caregiver_participant_id: str
    preset: str


class CaregiverNotificationPreferencesUpdateRequest(BaseModel):
    actor_id: str
    patient_id: str
    caregiver_participant_id: str
    notification_preferences: dict = Field(default_factory=dict)


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
    link = context.store.get_caregiver_link(actor_id, patient_id)
    if link is None:
        raise HTTPException(status_code=404, detail="caregiver link metadata not found")
    return {
        "authorization_id": f"caregiver-link:{actor_id}:{patient_id}",
        "tenant_id": tenant_id,
        "patient_id": patient_id,
        "actor_id": actor_id,
        "actor_type": "caregiver",
        "granted_by": patient_id,
        "preset": str(link.get("preset", "primary_caregiver")),
        "scopes": list(link.get("scopes", [])),
        "status": "active",
        "effective_at": datetime.now(UTC).isoformat(),
        "revoked_at": None,
        "authorization_version": int(link.get("authorization_version", 1) or 1),
    }


@router.get("/internal/caregiver-links")
def caregiver_links(patient_id: str = Query(...)) -> dict:
    links = context.store.list_caregiver_links_for_patient(patient_id)
    return {
        "patient_id": patient_id,
        "links": [
            {
                "caregiver_participant_id": str(link.get("caregiver_participant_id", "")),
                "display_name": str(link.get("display_name", link.get("caregiver_participant_id", ""))),
                "phone_number": str(link.get("phone_number", "")),
                "preset": str(link.get("preset", "primary_caregiver")),
                "scopes": list(link.get("scopes", [])),
                "notification_preferences": dict(link.get("notification_preferences", {})),
                "authorization_version": int(link.get("authorization_version", 1) or 1),
                "active": bool(link.get("active", True)),
            }
            for link in links
        ],
    }


@router.post("/internal/caregiver-links/preset")
def update_caregiver_link_preset(payload: CaregiverPresetUpdateRequest) -> dict:
    actor_link = context.store.get_caregiver_link(payload.actor_id, payload.patient_id)
    if actor_link is None or not bool(actor_link.get("can_edit_plan", False)):
        raise HTTPException(status_code=403, detail="actor is not allowed to manage caregiver presets")
    updated = context.store.update_caregiver_link_preset(
        payload.caregiver_participant_id,
        payload.patient_id,
        payload.preset,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="caregiver link not found")
    return {
        "caregiver_participant_id": str(updated.get("caregiver_participant_id", "")),
        "patient_id": str(updated.get("patient_id", "")),
        "preset": str(updated.get("preset", "primary_caregiver")),
        "scopes": list(updated.get("scopes", [])),
        "notification_preferences": dict(updated.get("notification_preferences", {})),
        "authorization_version": int(updated.get("authorization_version", 1) or 1),
        "can_edit_plan": bool(updated.get("can_edit_plan", False)),
    }


@router.post("/internal/caregiver-links/notification-preferences")
def update_caregiver_link_notification_preferences(payload: CaregiverNotificationPreferencesUpdateRequest) -> dict:
    actor_link = context.store.get_caregiver_link(payload.actor_id, payload.patient_id)
    if actor_link is None or not bool(actor_link.get("can_edit_plan", False)):
        raise HTTPException(status_code=403, detail="actor is not allowed to manage caregiver notification preferences")
    updated = context.store.update_caregiver_link_notification_preferences(
        payload.caregiver_participant_id,
        payload.patient_id,
        payload.notification_preferences,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="caregiver link not found")
    return {
        "caregiver_participant_id": str(updated.get("caregiver_participant_id", "")),
        "patient_id": str(updated.get("patient_id", "")),
        "preset": str(updated.get("preset", "primary_caregiver")),
        "scopes": list(updated.get("scopes", [])),
        "notification_preferences": dict(updated.get("notification_preferences", {})),
        "authorization_version": int(updated.get("authorization_version", 1) or 1),
        "can_edit_plan": bool(updated.get("can_edit_plan", False)),
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


@router.get("/internal/care-plans/active")
def active_care_plan(patient_id: str = Query(...)) -> dict:
    care_plan = context.store.get_active_care_plan_for_patient(patient_id)
    if care_plan is None:
        raise HTTPException(status_code=404, detail="active care plan not found")
    return {
        "id": str(care_plan["id"]),
        "patient_id": str(care_plan["patient_id"]),
        "status": str(care_plan.get("status", "active")),
        "version": int(care_plan.get("version", 1) or 1),
    }


@router.get("/internal/wins/binding")
def win_binding(win_instance_id: str = Query(...)) -> dict:
    binding = context.store.get_win_binding(win_instance_id)
    if binding is None:
        raise HTTPException(status_code=404, detail="win binding not found")
    return {
        "win_instance_id": str(binding["win_instance_id"]),
        "win_definition_id": str(binding["win_definition_id"]),
        "care_plan_id": str(binding["care_plan_id"]),
        "patient_id": str(binding["patient_id"]),
        "title": str(binding.get("title", "")),
        "category": str(binding.get("category", "")),
        "instructions": str(binding.get("instructions", "")),
        "criticality": str(binding.get("criticality", "medium")),
        "flexibility": str(binding.get("flexibility", "flexible")),
        "recurrence_type": str(binding.get("recurrence_type", "one_off")),
        "recurrence_interval": int(binding.get("recurrence_interval", 1) or 1),
        "recurrence_days_of_week": list(binding.get("recurrence_days_of_week", []) or []),
        "recurrence_until": binding.get("recurrence_until"),
    }


@router.get("/internal/reminders/latest-context")
def latest_reminder_context(participant_id: str = Query(...), patient_id: str = Query(...)) -> dict:
    reminder = context.store.get_latest_scheduled_reminder_context(participant_id, patient_id)
    if reminder is None:
        raise HTTPException(status_code=404, detail="scheduled reminder context not found")
    return reminder


@router.get("/internal/gateway/pending-action")
def get_gateway_pending_action(pending_key: str = Query(...)) -> dict:
    synthetic_phone = f"gateway_pending:{pending_key}"
    session = context.store.get_onboarding_session(synthetic_phone)
    if session is None or session.status != "active" or session.expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=404, detail="pending action not found")
    return {
        "pending_key": pending_key,
        "plan": dict(session.data.get("plan") or {}),
        "expires_at": session.expires_at.isoformat(),
    }


@router.post("/internal/gateway/pending-action")
def save_gateway_pending_action(payload: GatewayPendingActionRequest) -> dict:
    synthetic_phone = f"gateway_pending:{payload.pending_key}"
    session = context.store.save_onboarding_session(
        phone_number=synthetic_phone,
        state="gateway_pending_action",
        status="active",
        data={"plan": payload.plan},
        expires_at=payload.expires_at,
        completion_note="",
    )
    return {
        "pending_key": payload.pending_key,
        "expires_at": session.expires_at.isoformat(),
    }


@router.delete("/internal/gateway/pending-action")
def clear_gateway_pending_action(pending_key: str = Query(...)) -> dict:
    synthetic_phone = f"gateway_pending:{pending_key}"
    session = context.store.get_onboarding_session(synthetic_phone)
    if session is not None:
        context.store.save_onboarding_session(
            phone_number=synthetic_phone,
            state="gateway_pending_action",
            status="completed",
            data=dict(session.data),
            expires_at=session.expires_at,
            completion_note="gateway_pending_cleared",
        )
    return {"ok": True}


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


@router.post("/internal/patient-context/clinical-facts")
def create_patient_clinical_fact(payload: PatientClinicalFactCreateRequest) -> dict:
    try:
        return context.patient_context.upsert_clinical_fact(
            tenant_id=payload.tenant_id,
            patient_id=payload.patient_id,
            actor_participant_id=payload.actor_participant_id,
            fact_key=payload.fact_key,
            fact_value=payload.fact_value,
            summary=payload.summary,
            source=payload.source,
            effective_at=payload.effective_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/internal/patient-context/clinical-facts/active")
def list_active_patient_clinical_facts(tenant_id: str = Query(...), patient_id: str = Query(...)) -> dict:
    return {"facts": context.patient_context.active_clinical_facts(tenant_id=tenant_id, patient_id=patient_id)}


@router.delete("/internal/patient-context/clinical-facts")
def forget_patient_clinical_fact(tenant_id: str = Query(...), patient_id: str = Query(...), fact_key: str = Query(...)) -> dict:
    try:
        row = context.patient_context.forget_clinical_fact(
            tenant_id=tenant_id,
            patient_id=patient_id,
            fact_key=fact_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"fact": row}


@router.post("/internal/patient-context/observations")
def create_patient_observation(payload: PatientObservationCreateRequest) -> dict:
    try:
        return context.patient_context.add_observation(
            tenant_id=payload.tenant_id,
            patient_id=payload.patient_id,
            actor_participant_id=payload.actor_participant_id,
            observation_key=payload.observation_key,
            observation_value=payload.observation_value,
            summary=payload.summary,
            source=payload.source,
            observed_at=payload.observed_at,
            expires_at=payload.expires_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/internal/patient-context/observations/active")
def list_active_patient_observations(tenant_id: str = Query(...), patient_id: str = Query(...)) -> dict:
    return {"observations": context.patient_context.active_observations(tenant_id=tenant_id, patient_id=patient_id)}


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
