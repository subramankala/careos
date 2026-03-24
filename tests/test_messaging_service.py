from __future__ import annotations

from datetime import UTC, datetime

from careos.db.repositories.store import InMemoryStore
from careos.services.messaging_service import MessageOrchestrator


def test_log_inbound_persists_provider_metadata_and_webhook_timestamp() -> None:
    store = InMemoryStore()
    messaging = MessageOrchestrator(store)
    received_at = datetime(2026, 3, 24, 3, 15, tzinfo=UTC)

    created = messaging.log_inbound(
        tenant_id="tenant-1",
        patient_id="patient-1",
        participant_id="participant-1",
        body="Taken",
        correlation_id="SM123",
        provider_payload={
            "MessageSid": "SM123",
            "WaId": "14085551234",
            "ProfileName": "Kumar",
            "From": "whatsapp:+14085551234",
            "To": "whatsapp:+14155238886",
        },
        received_at=received_at,
    )

    assert created is True
    event = store.message_events[-1]
    payload = dict(event["structured_payload"])
    assert payload["provider"] == "twilio"
    assert payload["provider_message_sid"] == "SM123"
    assert payload["provider_wa_id"] == "14085551234"
    assert payload["provider_profile_name"] == "Kumar"
    assert payload["provider_from"] == "whatsapp:+14085551234"
    assert payload["provider_to"] == "whatsapp:+14155238886"
    assert payload["webhook_received_at"] == received_at.isoformat()
    assert payload["timestamp_source"] == "webhook_received_at"
