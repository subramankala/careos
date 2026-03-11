from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from careos.main import app


client = TestClient(app)


def _seed_context_and_win(phone: str, title: str = "Bridge Med") -> tuple[dict, str]:
    tenant = client.post(
        "/tenants",
        json={"name": "BridgeTenant", "type": "family", "timezone": "UTC", "status": "active"},
    ).json()

    patient = client.post(
        "/patients",
        json={
            "tenant_id": tenant["id"],
            "display_name": "Bridge Patient",
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
            "display_name": "Bridge User",
            "phone_number": phone,
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
                    "criticality": "high",
                    "flexibility": "rigid",
                }
            ],
            "instances": [{"scheduled_start": start.isoformat(), "scheduled_end": end.isoformat()}],
        },
    )
    participant_context = {
        "tenant_id": tenant["id"],
        "participant_id": participant["id"],
        "participant_role": "patient",
        "patient_id": patient["id"],
        "patient_timezone": "UTC",
        "patient_persona": "caregiver_managed_elder",
    }
    return participant_context, patient["id"]


def test_fallback_bridge_maps_pending_question_to_schedule() -> None:
    participant_context, _ = _seed_context_and_win("whatsapp:+15550110001", title="Pantoprazole 40mg")
    response = client.post(
        "/v1/careos/fallback",
        json={
            "text": "what is pending today?",
            "participant_context": participant_context,
            "allowed_actions": ["read", "write_via_mcp"],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "openclaw_fallback"
    assert "Schedule (" in payload["text"]
    assert "Pantoprazole 40mg" in payload["text"]


def test_fallback_bridge_maps_mark_done_item_number() -> None:
    participant_context, patient_id = _seed_context_and_win("whatsapp:+15550110002", title="Aspirin 75mg")
    response = client.post(
        "/v1/careos/fallback",
        json={
            "text": "mark 1 done",
            "participant_context": participant_context,
            "allowed_actions": ["read", "write_via_mcp"],
        },
    )
    assert response.status_code == 200
    assert "Marked 1 as completed." in response.json()["text"]

    status = client.get(f"/patients/{patient_id}/status").json()
    assert status["completed_count"] >= 1


def test_fallback_bridge_unknown_text_returns_guidance() -> None:
    participant_context, _ = _seed_context_and_win("whatsapp:+15550110003", title="Bridge Unknown")
    response = client.post(
        "/v1/careos/fallback",
        json={
            "text": "can you explain all details deeply",
            "participant_context": participant_context,
            "allowed_actions": ["read"],
        },
    )
    assert response.status_code == 200
    assert "I can help with schedule, next, status" in response.json()["text"]
