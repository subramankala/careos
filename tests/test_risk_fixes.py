from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from careos.app_context import context
from careos.db.repositories.store import InMemoryStore
from careos.domain.enums.core import Criticality, Flexibility, PersonaType, Role
from careos.domain.models.api import (
    AddWinsRequest,
    CarePlanCreate,
    ParticipantCreate,
    PatientCreate,
    TenantCreate,
    WinDefinitionCreate,
    WinInstanceCreate,
)
from careos.main import app
from careos.settings import settings
from careos.workers.scheduler_worker import run_once


client = TestClient(app)


def _seed_patient_for_webhook(phone_number: str, title: str) -> tuple[str, str]:
    tenant = client.post(
        "/tenants",
        json={"name": f"Tenant {title}", "type": "family", "timezone": "UTC", "status": "active"},
    ).json()

    patient = client.post(
        "/patients",
        json={
            "tenant_id": tenant["id"],
            "display_name": title,
            "timezone": "UTC",
            "primary_language": "en",
            "persona_type": "caregiver_managed_elder",
            "risk_level": "medium",
            "status": "active",
        },
    ).json()

    participant = client.post(
        "/participants",
        json={
            "tenant_id": tenant["id"],
            "role": "patient",
            "display_name": f"{title} user",
            "phone_number": phone_number,
            "preferred_channel": "whatsapp",
            "preferred_language": "en",
            "active": True,
        },
    ).json()

    client.post(
        "/caregiver-links",
        json={"caregiver_participant_id": participant["id"], "patient_id": patient["id"]},
    )

    plan = client.post(
        "/care-plans",
        json={
            "patient_id": patient["id"],
            "created_by_participant_id": participant["id"],
            "status": "active",
            "version": 1,
            "source_type": "manual",
        },
    ).json()

    start = datetime.now(UTC).replace(second=0, microsecond=0)
    end = start + timedelta(minutes=30)
    client.post(
        f"/care-plans/{plan['id']}/wins",
        json={
            "patient_id": patient["id"],
            "definitions": [
                {
                    "category": "medication",
                    "title": title,
                    "instructions": "Take medication",
                    "why_it_matters": "recovery",
                    "criticality": "high",
                    "flexibility": "windowed",
                }
            ],
            "instances": [{"scheduled_start": start.isoformat(), "scheduled_end": end.isoformat()}],
        },
    )

    timeline = client.get(f"/patients/{patient['id']}/timeline").json()
    return patient["id"], timeline[0]["win_instance_id"]


def test_twilio_signature_rejects_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    import careos.api.routes.twilio as twilio_route

    settings.validate_twilio_signature = True
    monkeypatch.setattr(twilio_route, "validate_signature", lambda request, payload: False)

    response = client.post(
        "/twilio/webhook",
        data={
            "From": "whatsapp:+15559990001",
            "To": "whatsapp:+15558889999",
            "Body": "schedule",
            "MessageSid": "SM_invalid_sig",
        },
    )
    assert response.status_code == 403


def test_duplicate_webhook_message_sid_does_not_repeat_delay_side_effect() -> None:
    settings.validate_twilio_signature = False
    patient_id, win_id = _seed_patient_for_webhook("whatsapp:+15559990002", "Idempotency Med")

    timeline_before = client.get(f"/patients/{patient_id}/timeline").json()
    original_start = datetime.fromisoformat(timeline_before[0]["scheduled_start"])

    payload = {
        "From": "whatsapp:+15559990002",
        "To": "whatsapp:+15558889999",
        "Body": f"delay {win_id} 15",
        "MessageSid": "SM_duplicate_delay",
    }
    first = client.post("/twilio/webhook", data=payload)
    second = client.post("/twilio/webhook", data=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert "Duplicate message received" in second.text

    timeline_after = client.get(f"/patients/{patient_id}/timeline").json()
    updated_start = datetime.fromisoformat(timeline_after[0]["scheduled_start"])
    assert updated_start - original_start == timedelta(minutes=15)


def test_inmemory_timezone_day_boundary_uses_patient_timezone() -> None:
    store = InMemoryStore()
    tenant = store.create_tenant(TenantCreate(name="TZ", timezone="Asia/Kolkata"))
    patient = store.create_patient(
        PatientCreate(
            tenant_id=tenant["id"],
            display_name="TZ Patient",
            timezone="Asia/Kolkata",
            persona_type=PersonaType.CAREGIVER_MANAGED_ELDER,
        )
    )
    participant = store.create_participant(
        ParticipantCreate(
            tenant_id=tenant["id"],
            role=Role.CAREGIVER,
            display_name="Caregiver",
            phone_number="+15551230000",
        )
    )
    store.link_caregiver(participant["id"], patient["id"])
    plan = store.create_care_plan(
        CarePlanCreate(
            patient_id=patient["id"],
            created_by_participant_id=participant["id"],
        )
    )

    local_tz = ZoneInfo("Asia/Kolkata")
    start_local = datetime(2026, 3, 8, 0, 10, tzinfo=local_tz)
    end_local = datetime(2026, 3, 8, 0, 40, tzinfo=local_tz)

    store.add_wins(
        plan["id"],
        AddWinsRequest(
            patient_id=patient["id"],
            definitions=[
                WinDefinitionCreate(
                    category="medication",
                    title="Midnight med",
                    instructions="Take tablet",
                    criticality=Criticality.MEDIUM,
                    flexibility=Flexibility.WINDOWED,
                )
            ],
            instances=[
                WinInstanceCreate(
                    scheduled_start=start_local,
                    scheduled_end=end_local,
                )
            ],
        ),
    )

    now_utc = datetime(2026, 3, 7, 19, 0, tzinfo=UTC)  # 00:30 Asia/Kolkata on Mar 8
    items = store.list_today(patient["id"], now_utc)
    assert len(items) == 1
    assert items[0].title == "Midnight med"


def test_identity_resolution_ambiguous_caregiver_mapping_returns_none() -> None:
    store = InMemoryStore()
    tenant = store.create_tenant(TenantCreate(name="Identity", timezone="UTC"))

    caregiver = store.create_participant(
        ParticipantCreate(
            tenant_id=tenant["id"],
            role=Role.CAREGIVER,
            display_name="Shared caregiver",
            phone_number="whatsapp:+15550101010",
        )
    )
    patient_one = store.create_patient(PatientCreate(tenant_id=tenant["id"], display_name="P1"))
    patient_two = store.create_patient(PatientCreate(tenant_id=tenant["id"], display_name="P2"))

    store.link_caregiver(caregiver["id"], patient_one["id"])
    store.link_caregiver(caregiver["id"], patient_two["id"])

    resolved = store.resolve_participant_context("whatsapp:+15550101010")
    assert resolved is None


def test_scheduler_run_once_idempotent_for_same_due_slot() -> None:
    original_store = context.store
    original_setting = settings.scheduler_patient_ids

    try:
        store = InMemoryStore()
        context.store = store

        tenant = store.create_tenant(TenantCreate(name="Sched", timezone="UTC"))
        patient = store.create_patient(PatientCreate(tenant_id=tenant["id"], display_name="Scheduler patient"))
        participant = store.create_participant(
            ParticipantCreate(
                tenant_id=tenant["id"],
                role=Role.CAREGIVER,
                display_name="Scheduler caregiver",
                phone_number="+15550002222",
            )
        )
        store.link_caregiver(participant["id"], patient["id"])
        plan = store.create_care_plan(
            CarePlanCreate(
                patient_id=patient["id"],
                created_by_participant_id=participant["id"],
            )
        )

        now = datetime(2026, 3, 10, 10, 0, tzinfo=UTC)
        store.add_wins(
            plan["id"],
            AddWinsRequest(
                patient_id=patient["id"],
                definitions=[
                    WinDefinitionCreate(
                        category="medication",
                        title="Due now med",
                        instructions="Take",
                        criticality=Criticality.HIGH,
                        flexibility=Flexibility.RIGID,
                    )
                ],
                instances=[
                    WinInstanceCreate(
                        scheduled_start=now - timedelta(minutes=5),
                        scheduled_end=now + timedelta(minutes=10),
                    )
                ],
            ),
        )

        settings.scheduler_patient_ids = patient["id"]

        first_sent = run_once(now=now)
        second_sent = run_once(now=now)

        assert first_sent == 1
        assert second_sent == 0
    finally:
        context.store = original_store
        settings.scheduler_patient_ids = original_setting
