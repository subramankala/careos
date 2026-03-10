from careos.db.repositories.store import Store


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
            payload={},
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
