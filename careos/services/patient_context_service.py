from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

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

    def forget_clinical_fact(self, *, tenant_id: str, patient_id: str, fact_key: str) -> dict | None:
        profile = self.store.get_patient_profile(patient_id)
        if profile is None:
            raise ValueError("patient not found")
        if str(profile.get("tenant_id")) != str(tenant_id):
            raise ValueError("tenant-patient mismatch")
        normalized_key = str(fact_key).strip().lower()
        if not normalized_key:
            raise ValueError("fact_key is required")
        return self.store.deactivate_patient_clinical_fact(
            tenant_id=tenant_id,
            patient_id=patient_id,
            fact_key=normalized_key,
        )

    def add_observation(
        self,
        *,
        tenant_id: str,
        patient_id: str,
        actor_participant_id: str,
        observation_key: str,
        observation_value: dict,
        summary: str,
        source: str = "caregiver_reported",
        observed_at: datetime | None = None,
        expires_at: datetime | None = None,
    ) -> dict:
        profile = self.store.get_patient_profile(patient_id)
        if profile is None:
            raise ValueError("patient not found")
        if str(profile.get("tenant_id")) != str(tenant_id):
            raise ValueError("tenant-patient mismatch")
        normalized_key = str(observation_key).strip().lower()
        if not normalized_key:
            raise ValueError("observation_key is required")
        if not str(summary).strip():
            raise ValueError("summary is required")
        observed_ts = observed_at or datetime.now(UTC)
        expires_ts = expires_at or observed_ts
        if expires_ts <= observed_ts:
            raise ValueError("expires_at must be after observed_at")
        return self.store.create_patient_observation(
            tenant_id=tenant_id,
            patient_id=patient_id,
            actor_participant_id=actor_participant_id,
            observation_key=normalized_key,
            observation_value=dict(observation_value or {}),
            summary=str(summary).strip(),
            source=str(source).strip() or "caregiver_reported",
            observed_at=observed_ts,
            expires_at=expires_ts,
        )

    def active_observations(self, *, tenant_id: str, patient_id: str, now: datetime | None = None) -> list[dict]:
        ts = now or datetime.now(UTC)
        return self.store.list_active_patient_observations(tenant_id=tenant_id, patient_id=patient_id, now=ts)

    def upsert_day_plan(
        self,
        *,
        tenant_id: str,
        patient_id: str,
        actor_participant_id: str,
        plan_key: str,
        plan_value: dict,
        summary: str,
        source: str = "caregiver_reported",
        plan_date: date,
        expires_at: datetime,
    ) -> dict:
        profile = self.store.get_patient_profile(patient_id)
        if profile is None:
            raise ValueError("patient not found")
        if str(profile.get("tenant_id")) != str(tenant_id):
            raise ValueError("tenant-patient mismatch")
        normalized_key = str(plan_key).strip().lower()
        if not normalized_key:
            raise ValueError("plan_key is required")
        if not str(summary).strip():
            raise ValueError("summary is required")
        return self.store.upsert_patient_day_plan(
            tenant_id=tenant_id,
            patient_id=patient_id,
            actor_participant_id=actor_participant_id,
            plan_key=normalized_key,
            plan_value=dict(plan_value or {}),
            summary=str(summary).strip(),
            source=str(source).strip() or "caregiver_reported",
            plan_date=plan_date,
            expires_at=expires_at,
        )

    def active_day_plans(
        self,
        *,
        tenant_id: str,
        patient_id: str,
        plan_date: date | None = None,
        now: datetime | None = None,
    ) -> list[dict]:
        ts = now or datetime.now(UTC)
        target_date = plan_date or self._local_date_for_patient(patient_id=patient_id, at=ts)
        return self.store.list_active_patient_day_plans(
            tenant_id=tenant_id,
            patient_id=patient_id,
            plan_date=target_date,
            now=ts,
        )

    def forget_day_plan(
        self,
        *,
        tenant_id: str,
        patient_id: str,
        plan_key: str,
        plan_date: date | None = None,
        now: datetime | None = None,
    ) -> dict | None:
        profile = self.store.get_patient_profile(patient_id)
        if profile is None:
            raise ValueError("patient not found")
        if str(profile.get("tenant_id")) != str(tenant_id):
            raise ValueError("tenant-patient mismatch")
        normalized_key = str(plan_key).strip().lower()
        if not normalized_key:
            raise ValueError("plan_key is required")
        ts = now or datetime.now(UTC)
        target_date = plan_date or self._local_date_for_patient(patient_id=patient_id, at=ts)
        return self.store.deactivate_patient_day_plan(
            tenant_id=tenant_id,
            patient_id=patient_id,
            plan_key=normalized_key,
            plan_date=target_date,
        )

    def _local_date_for_patient(self, *, patient_id: str, at: datetime) -> date:
        profile = self.store.get_patient_profile(patient_id) or {"timezone": "UTC"}
        timezone_name = str(profile.get("timezone", "UTC"))
        return at.astimezone(ZoneInfo(timezone_name)).date()
