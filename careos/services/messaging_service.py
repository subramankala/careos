from datetime import UTC, datetime

from careos.db.repositories.store import Store


def _normalize_provider_payload(provider_payload: dict | None, *, received_at: datetime | None = None) -> dict:
    payload = dict(provider_payload or {})
    metadata = {
        "provider": "twilio",
        "webhook_received_at": (received_at or datetime.now(UTC)).isoformat(),
    }
    for key, target in (
        ("MessageSid", "provider_message_sid"),
        ("SmsSid", "provider_sms_sid"),
        ("WaId", "provider_wa_id"),
        ("ProfileName", "provider_profile_name"),
        ("From", "provider_from"),
        ("To", "provider_to"),
        ("AccountSid", "provider_account_sid"),
    ):
        value = str(payload.get(key) or "").strip()
        if value:
            metadata[target] = value
    for candidate in ("Timestamp", "DateSent", "MessageDate"):
        value = str(payload.get(candidate) or "").strip()
        if value:
            metadata["provider_timestamp"] = value
            metadata["timestamp_source"] = candidate
            break
    if "timestamp_source" not in metadata:
        metadata["timestamp_source"] = "webhook_received_at"
    return metadata


class MessageOrchestrator:
    def __init__(self, store: Store) -> None:
        self.store = store

    def log_inbound(
        self,
        *,
        tenant_id: str,
        patient_id: str,
        participant_id: str | None,
        body: str,
        correlation_id: str,
        provider_payload: dict | None = None,
        received_at: datetime | None = None,
    ) -> bool:
        return self.store.log_message_event(
            tenant_id=tenant_id,
            patient_id=patient_id,
            participant_id=participant_id,
            direction="inbound",
            channel="whatsapp",
            message_type="user_text",
            body=body,
            correlation_id=correlation_id,
            idempotency_key=f"in:{correlation_id}",
            payload=_normalize_provider_payload(provider_payload, received_at=received_at),
        )

    def log_outbound(
        self,
        *,
        tenant_id: str,
        patient_id: str,
        participant_id: str | None,
        body: str,
        correlation_id: str,
    ) -> bool:
        return self.store.log_message_event(
            tenant_id=tenant_id,
            patient_id=patient_id,
            participant_id=participant_id,
            direction="outbound",
            channel="whatsapp",
            message_type="reply_text",
            body=body,
            correlation_id=correlation_id,
            idempotency_key=f"out:{correlation_id}",
            payload={},
        )
