from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from careos.main import app
from careos.settings import settings


client = TestClient(app)


def _seed_patient(tenant_id: str, phone_number: str, title: str) -> tuple[str, str, str]:
    patient = client.post(
        "/patients",
        json={
            "tenant_id": tenant_id,
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
