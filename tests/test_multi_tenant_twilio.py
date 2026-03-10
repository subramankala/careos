from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

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
    _seed_patient(tenant["id"], "whatsapp:+15550009999", "TZ med", timezone="Asia/Kolkata")

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
    assert "07:00" in xml
    assert "01:30" not in xml


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
    assert "Reply: use <number>" in no_context.text

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
