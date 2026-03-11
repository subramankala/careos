from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from careos.app_context import context
from careos.domain.models.api import CommandResult
from careos.main import app
from careos.settings import settings


client = TestClient(app)


def _seed_patient(tenant_id: str, phone_number: str, title: str, timezone: str = "UTC") -> tuple[str, str, str]:
    patient = client.post(
        "/patients",
        json={
            "tenant_id": tenant_id,
            "display_name": title,
            "timezone": timezone,
            "primary_language": "en",
            "persona_type": "caregiver_managed_elder",
            "risk_level": "medium",
            "status": "active",
        },
    ).json()

    participant = client.post(
        "/participants",
        json={
            "tenant_id": tenant_id,
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
                    "flexibility": "rigid",
                    "default_channel_policy": {},
                    "escalation_policy": {},
                }
            ],
            "instances": [{"scheduled_start": start.isoformat(), "scheduled_end": end.isoformat()}],
        },
    )
    return patient["id"], participant["id"], plan["id"]


def test_three_patients_same_business_number_no_crosstalk() -> None:
    settings.validate_twilio_signature = False

    tenant = client.post(
        "/tenants",
        json={"name": "Pilot", "type": "family", "timezone": "UTC", "status": "active"},
    ).json()

    _seed_patient(tenant["id"], "whatsapp:+15550000001", "Aspirin")
    _seed_patient(tenant["id"], "whatsapp:+15550000002", "Metoprolol")
    _seed_patient(tenant["id"], "whatsapp:+15550000003", "Physio Walk")

    cases = [
        ("whatsapp:+15550000001", "Aspirin"),
        ("whatsapp:+15550000002", "Metoprolol"),
        ("whatsapp:+15550000003", "Physio Walk"),
    ]

    for index, (sender, expected_title) in enumerate(cases, start=1):
        response = client.post(
            "/twilio/webhook",
            data={
                "From": sender,
                "To": "whatsapp:+15558889999",
                "Body": "schedule",
                "MessageSid": f"SM_case_{index}",
            },
        )
        assert response.status_code == 200
        xml = response.text
        assert expected_title in xml
        unexpected = {"Aspirin", "Metoprolol", "Physio Walk"} - {expected_title}
        assert all(name not in xml for name in unexpected)


def test_schedule_message_uses_patient_timezone() -> None:
    settings.validate_twilio_signature = False
    tenant = client.post(
        "/tenants",
        json={"name": "TZ", "type": "family", "timezone": "Asia/Kolkata", "status": "active"},
    ).json()
    patient_id, _, _ = _seed_patient(tenant["id"], "whatsapp:+15550009999", "TZ med", timezone="Asia/Kolkata")

    response = client.post(
        "/twilio/webhook",
        data={
            "From": "whatsapp:+15550009999",
            "To": "whatsapp:+15558889999",
            "Body": "schedule",
            "MessageSid": "SM_tz_test",
        },
    )
    assert response.status_code == 200
    xml = response.text
    today = client.get(f"/patients/{patient_id}/today").json()
    start = datetime.fromisoformat(today["timeline"][0]["scheduled_start"].replace("Z", "+00:00"))
    expected_local = start.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%H:%M")
    assert expected_local in xml


def test_schedule_lists_all_items_with_numbers() -> None:
    settings.validate_twilio_signature = False
    tenant = client.post(
        "/tenants",
        json={"name": "Numbered", "type": "family", "timezone": "UTC", "status": "active"},
    ).json()
    patient_id, _, plan_id = _seed_patient(tenant["id"], "whatsapp:+15550008888", "Dose 1")

    start = datetime.now(UTC).replace(second=0, microsecond=0)
    end = start + timedelta(minutes=30)
    definitions = []
    for index in range(2, 13):
        definitions.append(
            {
                "category": "medication",
                "title": f"Dose {index}",
                "instructions": "Take medication",
                "criticality": "medium",
                "flexibility": "windowed",
            }
        )

    client.post(
        f"/care-plans/{plan_id}/wins",
        json={
            "patient_id": patient_id,
            "definitions": definitions,
            "instances": [{"scheduled_start": start.isoformat(), "scheduled_end": end.isoformat()}],
        },
    )

    response = client.post(
        "/twilio/webhook",
        data={
            "From": "whatsapp:+15550008888",
            "To": "whatsapp:+15558889999",
            "Body": "schedule",
            "MessageSid": "SM_numbered",
        },
    )
    assert response.status_code == 200
    xml = response.text
    assert "1. " in xml
    assert "11. " in xml
    assert "12. " in xml


def test_done_command_accepts_schedule_item_number() -> None:
    settings.validate_twilio_signature = False
    tenant = client.post(
        "/tenants",
        json={"name": "DoneNumber", "type": "family", "timezone": "UTC", "status": "active"},
    ).json()
    patient_id, _, _ = _seed_patient(tenant["id"], "whatsapp:+15550007777", "Numbered Done")

    done_response = client.post(
        "/twilio/webhook",
        data={
            "From": "whatsapp:+15550007777",
            "To": "whatsapp:+15558889999",
            "Body": "done 1",
            "MessageSid": "SM_done_number",
        },
    )
    assert done_response.status_code == 200
    assert "Marked 1 as completed." in done_response.text

    status = client.get(f"/patients/{patient_id}/status")
    assert status.status_code == 200
    assert status.json()["completed_count"] >= 1


def test_schedule_includes_prn_section_without_timed_instances() -> None:
    settings.validate_twilio_signature = False
    tenant = client.post(
        "/tenants",
        json={"name": "PrnTenant", "type": "family", "timezone": "UTC", "status": "active"},
    ).json()
    patient = client.post(
        "/patients",
        json={
            "tenant_id": tenant["id"],
            "display_name": "PRN Patient",
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
            "display_name": "PRN User",
            "phone_number": "whatsapp:+15550005555",
            "preferred_channel": "whatsapp",
            "preferred_language": "en",
            "active": True,
        },
    ).json()
    client.post("/caregiver-links", json={"caregiver_participant_id": participant["id"], "patient_id": patient["id"]})
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

    # Insert PRN definition with no scheduled instances.
    client.post(
        f"/care-plans/{plan['id']}/wins",
        json={
            "patient_id": patient["id"],
            "definitions": [
                {
                    "category": "medication",
                    "title": "Sorbitrate 5mg (SOS)",
                    "instructions": "Use only if chest pain occurs",
                    "criticality": "high",
                    "flexibility": "flexible",
                    "recurrence_type": "one_off",
                    "recurrence_interval": 1,
                    "recurrence_days_of_week": [],
                }
            ],
            "instances": [],
        },
    )

    response = client.post(
        "/twilio/webhook",
        data={
            "From": "whatsapp:+15550005555",
            "To": "whatsapp:+15558889999",
            "Body": "schedule",
            "MessageSid": "SM_prn_schedule",
        },
    )
    assert response.status_code == 200
    xml = response.text
    assert "SOS/PRN (as needed):" in xml
    assert "Sorbitrate 5mg (SOS)" in xml


def test_whoami_returns_active_context() -> None:
    settings.validate_twilio_signature = False
    tenant = client.post(
        "/tenants",
        json={"name": "WhoAmI", "type": "family", "timezone": "Asia/Kolkata", "status": "active"},
    ).json()
    patient_id, _, _ = _seed_patient(tenant["id"], "whatsapp:+15550006666", "WhoAmI Dose", timezone="Asia/Kolkata")
    response = client.post(
        "/twilio/webhook",
        data={
            "From": "whatsapp:+15550006666",
            "To": "whatsapp:+15558889999",
            "Body": "whoami",
            "MessageSid": "SM_whoami",
        },
    )
    assert response.status_code == 200
    assert "You are patient." in response.text
    assert f"Active patient: {patient_id}" in response.text


def test_multi_patient_requires_use_selection_then_routes_correctly() -> None:
    settings.validate_twilio_signature = False
    tenant = client.post(
        "/tenants",
        json={"name": "MultiSelect", "type": "family", "timezone": "Asia/Kolkata", "status": "active"},
    ).json()

    caregiver = client.post(
        "/participants",
        json={
            "tenant_id": tenant["id"],
            "role": "caregiver",
            "display_name": "Shared Caregiver",
            "phone_number": "whatsapp:+15550003333",
            "preferred_channel": "whatsapp",
            "preferred_language": "en",
            "active": True,
        },
    ).json()

    patient_a = client.post(
        "/patients",
        json={
            "tenant_id": tenant["id"],
            "display_name": "Father",
            "timezone": "Asia/Kolkata",
            "persona_type": "caregiver_managed_elder",
        },
    ).json()
    patient_b = client.post(
        "/patients",
        json={
            "tenant_id": tenant["id"],
            "display_name": "Mother",
            "timezone": "Asia/Kolkata",
            "persona_type": "caregiver_managed_elder",
        },
    ).json()
    client.post("/caregiver-links", json={"caregiver_participant_id": caregiver["id"], "patient_id": patient_a["id"]})
    client.post("/caregiver-links", json={"caregiver_participant_id": caregiver["id"], "patient_id": patient_b["id"]})

    plan_a = client.post(
        "/care-plans",
        json={
            "patient_id": patient_a["id"],
            "created_by_participant_id": caregiver["id"],
            "status": "active",
            "version": 1,
            "source_type": "manual",
        },
    ).json()
    plan_b = client.post(
        "/care-plans",
        json={
            "patient_id": patient_b["id"],
            "created_by_participant_id": caregiver["id"],
            "status": "active",
            "version": 1,
            "source_type": "manual",
        },
    ).json()

    start = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(minutes=5)
    end = start + timedelta(minutes=20)
    client.post(
        f"/care-plans/{plan_a['id']}/wins",
        json={
            "patient_id": patient_a["id"],
            "definitions": [
                {
                    "category": "medication",
                    "title": "Father Med",
                    "instructions": "Take",
                    "criticality": "high",
                    "flexibility": "rigid",
                }
            ],
            "instances": [{"scheduled_start": start.isoformat(), "scheduled_end": end.isoformat()}],
        },
    )
    client.post(
        f"/care-plans/{plan_b['id']}/wins",
        json={
            "patient_id": patient_b["id"],
            "definitions": [
                {
                    "category": "medication",
                    "title": "Mother Med",
                    "instructions": "Take",
                    "criticality": "high",
                    "flexibility": "rigid",
                }
            ],
            "instances": [{"scheduled_start": start.isoformat(), "scheduled_end": end.isoformat()}],
        },
    )

    no_context = client.post(
        "/twilio/webhook",
        data={"From": "whatsapp:+15550003333", "Body": "schedule", "MessageSid": "SM_multi_1"},
    )
    assert no_context.status_code == 200
    assert "Multiple patients are linked to this number." in no_context.text
    assert "Reply: use" in no_context.text

    select_two = client.post(
        "/twilio/webhook",
        data={"From": "whatsapp:+15550003333", "Body": "use 2", "MessageSid": "SM_multi_2"},
    )
    assert select_two.status_code == 200
    assert "Switched to Mother" in select_two.text

    schedule_b = client.post(
        "/twilio/webhook",
        data={"From": "whatsapp:+15550003333", "Body": "schedule", "MessageSid": "SM_multi_3"},
    )
    assert "Mother Med" in schedule_b.text
    assert "Father Med" not in schedule_b.text

    select_one = client.post(
        "/twilio/webhook",
        data={"From": "whatsapp:+15550003333", "Body": "use 1", "MessageSid": "SM_multi_4"},
    )
    assert select_one.status_code == 200
    assert "Switched to Father" in select_one.text

    schedule_a = client.post(
        "/twilio/webhook",
        data={"From": "whatsapp:+15550003333", "Body": "schedule", "MessageSid": "SM_multi_5"},
    )
    assert "Father Med" in schedule_a.text
    assert "Mother Med" not in schedule_a.text


def test_use_unlinked_patient_id_is_blocked() -> None:
    settings.validate_twilio_signature = False
    tenant_a = client.post(
        "/tenants",
        json={"name": "TenantA", "type": "family", "timezone": "UTC", "status": "active"},
    ).json()
    tenant_b = client.post(
        "/tenants",
        json={"name": "TenantB", "type": "family", "timezone": "UTC", "status": "active"},
    ).json()
    caregiver = client.post(
        "/participants",
        json={
            "tenant_id": tenant_a["id"],
            "role": "caregiver",
            "display_name": "Caregiver A",
            "phone_number": "whatsapp:+15550004444",
            "preferred_channel": "whatsapp",
            "preferred_language": "en",
            "active": True,
        },
    ).json()
    patient_a = client.post(
        "/patients",
        json={
            "tenant_id": tenant_a["id"],
            "display_name": "Patient A",
            "timezone": "UTC",
            "persona_type": "caregiver_managed_elder",
        },
    ).json()
    patient_b = client.post(
        "/patients",
        json={
            "tenant_id": tenant_b["id"],
            "display_name": "Patient B",
            "timezone": "UTC",
            "persona_type": "caregiver_managed_elder",
        },
    ).json()
    client.post("/caregiver-links", json={"caregiver_participant_id": caregiver["id"], "patient_id": patient_a["id"]})

    blocked = client.post(
        "/twilio/webhook",
        data={"From": "whatsapp:+15550004444", "Body": f"use {patient_b['id']}", "MessageSid": "SM_multi_block"},
    )
    assert blocked.status_code == 200
    assert "Invalid selection." in blocked.text


def test_openclaw_fallback_used_for_unknown_command_when_enabled(monkeypatch) -> None:
    settings.validate_twilio_signature = False
    previous_engine = settings.conversation_engine
    try:
        settings.conversation_engine = "openclaw"
        tenant = client.post(
            "/tenants",
            json={"name": "OpenClawFallback", "type": "family", "timezone": "UTC", "status": "active"},
        ).json()
        _seed_patient(tenant["id"], "whatsapp:+15550006601", "Fallback Dose")

        def _fake_handle(text: str, participant_context):
            assert text == "what is pending now?"
            return CommandResult(action="openclaw_fallback", text="You still have 1 pending item at 08:00.")

        monkeypatch.setattr(context.openclaw_router, "handle", _fake_handle)
        response = client.post(
            "/twilio/webhook",
            data={
                "From": "whatsapp:+15550006601",
                "To": "whatsapp:+15558889999",
                "Body": "what is pending now?",
                "MessageSid": "SM_openclaw_fallback",
            },
        )
        assert response.status_code == 200
        assert "You still have 1 pending item at 08:00." in response.text
    finally:
        settings.conversation_engine = previous_engine


def test_openclaw_unavailable_keeps_deterministic_fallback(monkeypatch) -> None:
    settings.validate_twilio_signature = False
    previous_engine = settings.conversation_engine
    try:
        settings.conversation_engine = "openclaw"
        tenant = client.post(
            "/tenants",
            json={"name": "OpenClawUnavailable", "type": "family", "timezone": "UTC", "status": "active"},
        ).json()
        _seed_patient(tenant["id"], "whatsapp:+15550006602", "Fallback Dose 2")

        monkeypatch.setattr(
            context.openclaw_router,
            "handle",
            lambda text, participant_context: CommandResult(action="unavailable", text=""),
        )
        response = client.post(
            "/twilio/webhook",
            data={
                "From": "whatsapp:+15550006602",
                "To": "whatsapp:+15558889999",
                "Body": "tell me in english",
                "MessageSid": "SM_openclaw_unavail",
            },
        )
        assert response.status_code == 200
        assert "I can handle:" in response.text
    finally:
        settings.conversation_engine = previous_engine


def test_openclaw_local_base_url_uses_inprocess_bridge() -> None:
    settings.validate_twilio_signature = False
    previous_engine = settings.conversation_engine
    previous_base_url = settings.openclaw_base_url
    try:
        settings.conversation_engine = "openclaw"
        settings.openclaw_base_url = "http://127.0.0.1:8115"
        tenant = client.post(
            "/tenants",
            json={"name": "OpenClawLocalBridge", "type": "family", "timezone": "UTC", "status": "active"},
        ).json()
        _seed_patient(tenant["id"], "whatsapp:+15550006603", "Local Bridge Dose")

        response = client.post(
            "/twilio/webhook",
            data={
                "From": "whatsapp:+15550006603",
                "To": "whatsapp:+15558889999",
                "Body": "what is pending today?",
                "MessageSid": "SM_openclaw_local_bridge",
            },
        )
        assert response.status_code == 200
        assert "Schedule (" in response.text
    finally:
        settings.conversation_engine = previous_engine
        settings.openclaw_base_url = previous_base_url
