from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from careos.main import app


client = TestClient(app)


def test_done_delay_skip_actions() -> None:
    tenant = client.post(
        "/tenants",
        json={"name": "Actions", "type": "family", "timezone": "UTC", "status": "active"},
    ).json()
    patient = client.post(
        "/patients",
        json={
            "tenant_id": tenant["id"],
            "display_name": "Action Patient",
            "timezone": "UTC",
            "persona_type": "caregiver_managed_elder",
        },
    ).json()
    participant = client.post(
        "/participants",
        json={
            "tenant_id": tenant["id"],
            "role": "caregiver",
            "display_name": "Caregiver",
            "phone_number": "whatsapp:+15551112222",
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
                    "title": "Evening dose",
                    "instructions": "Take tablet",
                    "criticality": "medium",
                    "flexibility": "windowed",
                }
            ],
            "instances": [{"scheduled_start": start.isoformat(), "scheduled_end": end.isoformat()}],
        },
    )

    timeline = client.get(f"/patients/{patient['id']}/timeline").json()
    win_id = timeline[0]["win_instance_id"]

    complete = client.post(f"/wins/{win_id}/complete", json={"actor_participant_id": participant["id"]})
    assert complete.status_code == 200

    skip = client.post(f"/wins/{win_id}/skip", json={"actor_participant_id": participant["id"]})
    assert skip.status_code == 200

    delay = client.post(
        f"/wins/{win_id}/delay",
        json={"actor_participant_id": participant["id"], "minutes": 15},
    )
    assert delay.status_code == 200
