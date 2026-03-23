from __future__ import annotations

from fastapi.testclient import TestClient

from careos.app_context import context
from careos.domain.enums.core import PersonaType, Role
from careos.domain.models.api import ParticipantCreate, PatientCreate, TenantCreate
from careos.main import app


client = TestClient(app)


def test_internal_admin_message_send_logs_outbound(monkeypatch) -> None:
    sent: dict[str, str] = {}

    class FakeSender:
        def __init__(self, *, account_sid: str, auth_token: str, from_number: str) -> None:
            sent["from_number"] = from_number

        def send_text(self, *, to_number: str, body: str) -> str:
            sent["to_number"] = to_number
            sent["body"] = body
            return "SM_admin_test_1"

    monkeypatch.setattr("careos.api.routes.internal.TwilioWhatsAppSender", FakeSender)

    tenant = context.store.create_tenant(TenantCreate(name="Admin Message Family"))
    participant = context.store.create_participant(
        ParticipantCreate(
            tenant_id=str(tenant["id"]),
            role=Role.CAREGIVER,
            display_name="Admin Message User",
            phone_number="whatsapp:+15559990001",
        )
    )
    patient = context.store.create_patient(
        PatientCreate(
            tenant_id=str(tenant["id"]),
            display_name="Admin Message Patient",
            timezone="UTC",
            persona_type=PersonaType.CAREGIVER_MANAGED_ELDER,
        )
    )
    context.store.link_caregiver(str(participant["id"]), str(patient["id"]))

    response = client.post(
        "/internal/admin/messages",
        json={
            "participant_id": str(participant["id"]),
            "body": "We received your request and have one follow-up question.",
            "privacy_request_id": "req_123",
            "operator_label": "admin_test",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["message_sid"] == "SM_admin_test_1"
    assert sent["to_number"] == "whatsapp:+15559990001"
    assert "follow-up question" in sent["body"]
    assert any(
        row.get("direction") == "outbound"
        and row.get("participant_id") == str(participant["id"])
        and row.get("correlation_id") == "SM_admin_test_1"
        for row in context.store.message_events
    )
