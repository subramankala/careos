from __future__ import annotations

from careos.db.repositories.store import Store


class PatientContextService:
    def __init__(self, store: Store) -> None:
        self.store = store

    def upsert_clinical_fact(
        self,
        *,
        tenant_id: str,
        patient_id: str,
        actor_participant_id: str,
        fact_key: str,
        fact_value: dict,
        summary: str,
        source: str = "caregiver_reported",
        effective_at=None,
    ) -> dict:
        profile = self.store.get_patient_profile(patient_id)
        if profile is None:
            raise ValueError("patient not found")
        if str(profile.get("tenant_id")) != str(tenant_id):
            raise ValueError("tenant-patient mismatch")
        normalized_key = str(fact_key).strip().lower()
        if not normalized_key:
            raise ValueError("fact_key is required")
        if not str(summary).strip():
            raise ValueError("summary is required")
        return self.store.upsert_patient_clinical_fact(
            tenant_id=tenant_id,
            patient_id=patient_id,
            actor_participant_id=actor_participant_id,
            fact_key=normalized_key,
            fact_value=dict(fact_value or {}),
            summary=str(summary).strip(),
            source=str(source).strip() or "caregiver_reported",
            effective_at=effective_at,
        )

    def active_clinical_facts(self, *, tenant_id: str, patient_id: str) -> list[dict]:
        return self.store.list_active_patient_clinical_facts(tenant_id=tenant_id, patient_id=patient_id)
