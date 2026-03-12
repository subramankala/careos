from __future__ import annotations

from datetime import UTC, datetime

from careos.db.repositories.store import Store


class PersonalizationService:
    def __init__(self, store: Store) -> None:
        self.store = store

    def create_rule(
        self,
        *,
        tenant_id: str,
        patient_id: str,
        actor_participant_id: str,
        rule_type: str,
        rule_payload: dict,
        expires_at: datetime,
    ) -> dict:
        profile = self.store.get_patient_profile(patient_id)
        if profile is None:
            raise ValueError("patient not found")
        if str(profile.get("tenant_id")) != str(tenant_id):
            raise ValueError("tenant-patient mismatch")
        return self.store.create_personalization_rule(
            tenant_id=tenant_id,
            patient_id=patient_id,
            actor_participant_id=actor_participant_id,
            rule_type=rule_type,
            rule_payload=rule_payload,
            expires_at=expires_at,
        )

    def active_rules(self, *, tenant_id: str, patient_id: str, now: datetime | None = None) -> list[dict]:
        ts = now or datetime.now(UTC)
        return self.store.list_active_personalization_rules(tenant_id=tenant_id, patient_id=patient_id, now=ts)
