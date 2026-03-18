from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from careos.app_context import context
from careos.domain.enums.core import Criticality, Flexibility, RecurrenceType, Role
from careos.domain.models.api import (
    AddWinsRequest,
    CarePlanCreate,
    CarePlanWinUpdateRequest,
    ParticipantCreate,
    PatientCreate,
    TenantCreate,
    WinDefinitionCreate,
    WinInstanceCreate,
)
from careos.main import app


client = TestClient(app)


def _seed_patient_with_plan(name: str) -> dict:
    tenant = client.post(
        "/tenants",
        json={"name": f"tenant-{name}", "type": "family", "timezone": "UTC", "status": "active"},
    ).json()
    patient = client.post(
        "/patients",
        json={
            "tenant_id": tenant["id"],
            "display_name": f"patient-{name}",
            "timezone": "UTC",
            "persona_type": "caregiver_managed_elder",
        },
    ).json()
    caregiver = client.post(
        "/participants",
        json={
            "tenant_id": tenant["id"],
            "role": "caregiver",
            "display_name": f"caregiver-{name}",
            "phone_number": f"+1555000{name[-4:]}",
        },
    ).json()
    client.post(
        "/caregiver-links",
        json={"caregiver_participant_id": caregiver["id"], "patient_id": patient["id"]},
    )
    care_plan = client.post(
        "/care-plans",
        json={
            "patient_id": patient["id"],
            "created_by_participant_id": caregiver["id"],
            "status": "active",
            "version": 1,
            "source_type": "manual",
        },
    ).json()
    return {
        "tenant": tenant,
        "patient": patient,
        "caregiver": caregiver,
        "care_plan": care_plan,
    }


def _definition_id_for_plan(care_plan_id: str, title: str) -> str:
    if not hasattr(context.store, "win_definitions"):
        raise RuntimeError("test requires in-memory store")
    for definition_id, definition in context.store.win_definitions.items():
        if str(definition.get("care_plan_id")) == care_plan_id and definition.get("title") == title:
            return str(definition_id)
    raise AssertionError("definition not found")


def test_temporary_medication_add_and_version_audit() -> None:
    setup = _seed_patient_with_plan("tempmed001")
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    response = client.post(
        f"/care-plans/{setup['care_plan']['id']}/wins/add",
        json={
            "actor_participant_id": setup["caregiver"]["id"],
            "reason": "temporary ortho med",
            "patient_id": setup["patient"]["id"],
            "definition": {
                "category": "medication",
                "title": "Ortho pain med",
                "instructions": "Take after dinner",
                "why_it_matters": "post-op pain control",
                "criticality": "medium",
                "flexibility": "windowed",
                "temporary_start": (now + timedelta(days=1)).isoformat(),
                "temporary_end": (now + timedelta(days=5)).isoformat(),
            },
            "future_instances": [
                {
                    "scheduled_start": (now + timedelta(days=1, hours=1)).isoformat(),
                    "scheduled_end": (now + timedelta(days=1, hours=2)).isoformat(),
                }
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "add"
    versions = client.get(f"/care-plans/{setup['care_plan']['id']}/versions").json()
    changes = client.get(f"/care-plans/{setup['care_plan']['id']}/changes").json()
    assert versions[-1]["version"] == body["new_version"]
    assert changes[-1]["reason"] == "temporary ortho med"


def test_move_medication_future_only_preserves_completed_history() -> None:
    setup = _seed_patient_with_plan("movemed001")
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    client.post(
        f"/care-plans/{setup['care_plan']['id']}/wins",
        json={
            "patient_id": setup["patient"]["id"],
            "definitions": [
                {
                    "category": "medication",
                    "title": "Cardiac med",
                    "instructions": "Take with water",
                    "criticality": "high",
                    "flexibility": "rigid",
                }
            ],
            "instances": [
                {
                    "scheduled_start": (now - timedelta(hours=2)).isoformat(),
                    "scheduled_end": (now - timedelta(hours=1, minutes=30)).isoformat(),
                },
                {
                    "scheduled_start": (now + timedelta(days=1, hours=8)).isoformat(),
                    "scheduled_end": (now + timedelta(days=1, hours=8, minutes=30)).isoformat(),
                },
            ],
        },
    )
    timeline = client.get(f"/patients/{setup['patient']['id']}/timeline").json()
    old_past = min(timeline, key=lambda i: i["scheduled_start"])
    client.post(
        f"/wins/{old_past['win_instance_id']}/complete",
        json={"actor_participant_id": setup["caregiver"]["id"]},
    )

    definition_id = _definition_id_for_plan(setup["care_plan"]["id"], "Cardiac med")
    moved = client.patch(
        f"/care-plans/{setup['care_plan']['id']}/wins/{definition_id}",
        json={
            "actor_participant_id": setup["caregiver"]["id"],
            "reason": "move slot to 9 AM",
            "future_instances": [
                {
                    "scheduled_start": (now + timedelta(days=1, hours=9)).isoformat(),
                    "scheduled_end": (now + timedelta(days=1, hours=9, minutes=30)).isoformat(),
                }
            ],
        },
    )
    assert moved.status_code == 200
    assert moved.json()["superseded_instance_ids"]
    created_ids = set(moved.json()["created_instance_ids"])
    assert len(created_ids) == 1

    assert any(
        win_id in context.store.win_instances
        and context.store.win_instances[win_id]["current_state"] != "superseded"
        for win_id in created_ids
    )


def test_change_instruction_without_duplication() -> None:
    setup = _seed_patient_with_plan("instr001")
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    client.post(
        f"/care-plans/{setup['care_plan']['id']}/wins",
        json={
            "patient_id": setup["patient"]["id"],
            "definitions": [
                {
                    "category": "therapy",
                    "title": "Breathing exercise",
                    "instructions": "10 mins",
                    "criticality": "low",
                    "flexibility": "flexible",
                }
            ],
            "instances": [
                {
                    "scheduled_start": (now + timedelta(days=1)).isoformat(),
                    "scheduled_end": (now + timedelta(days=1, minutes=30)).isoformat(),
                }
            ],
        },
    )
    definition_id = _definition_id_for_plan(setup["care_plan"]["id"], "Breathing exercise")
    before = client.get(f"/patients/{setup['patient']['id']}/timeline").json()

    update = client.patch(
        f"/care-plans/{setup['care_plan']['id']}/wins/{definition_id}",
        json={
            "actor_participant_id": setup["caregiver"]["id"],
            "reason": "clarify instruction",
            "instructions": "15 mins slow breathing",
            "why_it_matters": "reduce anxiety",
        },
    )
    assert update.status_code == 200
    assert update.json()["superseded_instance_ids"] == []
    assert update.json()["created_instance_ids"] == []

    after = client.get(f"/patients/{setup['patient']['id']}/timeline").json()
    assert len(before) == len(after)


def test_cancel_future_appointment_and_pause_activity_window() -> None:
    setup = _seed_patient_with_plan("appt001")
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    client.post(
        f"/care-plans/{setup['care_plan']['id']}/wins",
        json={
            "patient_id": setup["patient"]["id"],
            "definitions": [
                {
                    "category": "appointment",
                    "title": "Follow-up visit",
                    "instructions": "Visit clinic",
                    "criticality": "high",
                    "flexibility": "windowed",
                },
                {
                    "category": "movement",
                    "title": "Daily walk",
                    "instructions": "20 mins",
                    "criticality": "low",
                    "flexibility": "flexible",
                },
            ],
            "instances": [
                {
                    "scheduled_start": (now + timedelta(days=2)).isoformat(),
                    "scheduled_end": (now + timedelta(days=2, hours=1)).isoformat(),
                }
            ],
        },
    )
    appointment_id = _definition_id_for_plan(setup["care_plan"]["id"], "Follow-up visit")
    walk_id = _definition_id_for_plan(setup["care_plan"]["id"], "Daily walk")

    remove = client.request(
        "DELETE",
        f"/care-plans/{setup['care_plan']['id']}/wins/{appointment_id}",
        json={
            "actor_participant_id": setup["caregiver"]["id"],
            "reason": "appointment cancelled",
        },
    )
    assert remove.status_code == 200

    pause = client.patch(
        f"/care-plans/{setup['care_plan']['id']}/wins/{walk_id}",
        json={
            "actor_participant_id": setup["caregiver"]["id"],
            "reason": "pause walking for 2 days",
            "temporary_start": (now + timedelta(days=3)).isoformat(),
            "temporary_end": (now + timedelta(days=30)).isoformat(),
            "future_instances": [
                {
                    "scheduled_start": (now + timedelta(days=3)).isoformat(),
                    "scheduled_end": (now + timedelta(days=3, minutes=30)).isoformat(),
                }
            ],
        },
    )
    assert pause.status_code == 200


def test_unauthorized_caregiver_cannot_edit_other_patient() -> None:
    setup_a = _seed_patient_with_plan("authA01")
    setup_b = _seed_patient_with_plan("authB01")
    now = datetime.now(UTC).replace(second=0, microsecond=0)

    client.post(
        f"/care-plans/{setup_a['care_plan']['id']}/wins",
        json={
            "patient_id": setup_a["patient"]["id"],
            "definitions": [
                {
                    "category": "medication",
                    "title": "Tenant A med",
                    "instructions": "Take",
                    "criticality": "medium",
                    "flexibility": "windowed",
                }
            ],
            "instances": [
                {
                    "scheduled_start": (now + timedelta(days=1)).isoformat(),
                    "scheduled_end": (now + timedelta(days=1, minutes=30)).isoformat(),
                }
            ],
        },
    )
    definition_id = _definition_id_for_plan(setup_a["care_plan"]["id"], "Tenant A med")

    blocked = client.patch(
        f"/care-plans/{setup_a['care_plan']['id']}/wins/{definition_id}",
        json={
            "actor_participant_id": setup_b["caregiver"]["id"],
            "reason": "unauthorized edit",
            "instructions": "malicious",
        },
    )
    assert blocked.status_code == 403


def test_recurrence_patch_can_change_daily_medication_to_specific_weekdays() -> None:
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    tenant = context.store.create_tenant(TenantCreate(name="tenant-recur001", timezone="UTC"))
    patient = context.store.create_patient(PatientCreate(tenant_id=tenant["id"], display_name="patient-recur001"))
    caregiver = context.store.create_participant(
        ParticipantCreate(
            tenant_id=tenant["id"],
            role=Role.CAREGIVER,
            display_name="caregiver-recur001",
            phone_number="+15550009999",
        )
    )
    context.store.link_caregiver(caregiver["id"], patient["id"])
    care_plan = context.store.create_care_plan(
        CarePlanCreate(patient_id=patient["id"], created_by_participant_id=caregiver["id"])
    )

    context.store.add_wins(
        care_plan["id"],
        AddWinsRequest(
            patient_id=patient["id"],
            definitions=[
                WinDefinitionCreate(
                    category="medication",
                    title="Rhythm med",
                    instructions="Take after breakfast",
                    criticality=Criticality.HIGH,
                    flexibility=Flexibility.RIGID,
                    recurrence_type=RecurrenceType.DAILY,
                    recurrence_interval=1,
                    recurrence_days_of_week=[],
                )
            ],
            instances=[
                WinInstanceCreate(
                    scheduled_start=now + timedelta(days=1, hours=8),
                    scheduled_end=now + timedelta(days=1, hours=8, minutes=30),
                )
            ],
        ),
    )
    context.store.ensure_recurrence_instances(patient["id"], now, horizon_days=10)
    definition_id = _definition_id_for_plan(care_plan["id"], "Rhythm med")

    result = context.care_plan_edits.update_win(
        care_plan["id"],
        definition_id,
        CarePlanWinUpdateRequest(
            actor_participant_id=caregiver["id"],
            reason="switch to weekdays",
            recurrence_type=RecurrenceType.WEEKLY,
            recurrence_interval=1,
            recurrence_days_of_week=[0, 2, 4],
        ),
    )
    assert result.superseded_instance_ids

    future_active = [
        instance
        for instance in context.store.win_instances.values()
        if str(instance.get("patient_id")) == patient["id"]
        and str(instance.get("win_definition_id")) == definition_id
        and str(instance.get("current_state")) != "superseded"
        and instance["scheduled_start"] > now
    ]
    assert future_active
    assert {item["scheduled_start"].weekday() for item in future_active}.issubset({0, 2, 4})
