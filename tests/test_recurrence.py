from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from careos.app_context import context
from careos.main import app


client = TestClient(app)


def _seed_base(name: str) -> dict:
    tenant = client.post(
        "/tenants",
        json={"name": f"tenant-{name}", "type": "family", "timezone": "Asia/Kolkata", "status": "active"},
    ).json()
    patient = client.post(
        "/patients",
        json={
            "tenant_id": tenant["id"],
            "display_name": f"patient-{name}",
            "timezone": "Asia/Kolkata",
            "persona_type": "caregiver_managed_elder",
        },
    ).json()
    caregiver = client.post(
        "/participants",
        json={
            "tenant_id": tenant["id"],
            "role": "caregiver",
            "display_name": f"caregiver-{name}",
            "phone_number": f"+1557{name[-4:]}",
        },
    ).json()
    client.post(
        "/caregiver-links",
        json={"caregiver_participant_id": caregiver["id"], "patient_id": patient["id"]},
    )
    plan = client.post(
        "/care-plans",
        json={
            "patient_id": patient["id"],
            "created_by_participant_id": caregiver["id"],
            "status": "active",
            "version": 1,
            "source_type": "manual",
        },
    ).json()
    return {"tenant": tenant, "patient": patient, "caregiver": caregiver, "plan": plan}


def _definition_id(plan_id: str, title: str) -> str:
    for definition_id, definition in context.store.win_definitions.items():
        if str(definition.get("care_plan_id")) == plan_id and definition.get("title") == title:
            return str(definition_id)
    raise AssertionError("definition not found")


def test_daily_recurrence_auto_generates_future_instances() -> None:
    setup = _seed_base("recur001")
    now = datetime.now(UTC).replace(second=0, microsecond=0)

    client.post(
        f"/care-plans/{setup['plan']['id']}/wins",
        json={
            "patient_id": setup["patient"]["id"],
            "definitions": [
                {
                    "category": "medication",
                    "title": "Daily med",
                    "instructions": "Take daily",
                    "criticality": "high",
                    "flexibility": "windowed",
                    "recurrence_type": "daily",
                    "recurrence_interval": 1,
                }
            ],
            "instances": [
                {
                    "scheduled_start": (now + timedelta(hours=1)).isoformat(),
                    "scheduled_end": (now + timedelta(hours=1, minutes=30)).isoformat(),
                }
            ],
        },
    )

    context.store.ensure_recurrence_instances(setup["patient"]["id"], now, horizon_days=5)
    total = len(
        [
            instance
            for instance in context.store.win_instances.values()
            if str(instance["patient_id"]) == setup["patient"]["id"]
        ]
    )
    assert total >= 5


def test_weekly_recurrence_respects_until_and_single_stop_change() -> None:
    setup = _seed_base("recur002")
    now = datetime.now(UTC).replace(second=0, microsecond=0)

    client.post(
        f"/care-plans/{setup['plan']['id']}/wins",
        json={
            "patient_id": setup["patient"]["id"],
            "definitions": [
                {
                    "category": "appointment",
                    "title": "Weekly follow-up",
                    "instructions": "Attend weekly",
                    "criticality": "medium",
                    "flexibility": "windowed",
                    "recurrence_type": "weekly",
                    "recurrence_interval": 1,
                    "recurrence_until": (now + timedelta(days=21)).isoformat(),
                }
            ],
            "instances": [
                {
                    "scheduled_start": (now + timedelta(days=7)).isoformat(),
                    "scheduled_end": (now + timedelta(days=7, hours=1)).isoformat(),
                }
            ],
        },
    )

    context.store.ensure_recurrence_instances(setup["patient"]["id"], now, horizon_days=30)
    definition_id = _definition_id(setup["plan"]["id"], "Weekly follow-up")

    removed = client.request(
        "DELETE",
        f"/care-plans/{setup['plan']['id']}/wins/{definition_id}",
        json={
            "actor_participant_id": setup["caregiver"]["id"],
            "reason": "doctor stopped this",
        },
    )
    assert removed.status_code == 200
    assert removed.json()["superseded_instance_ids"]
