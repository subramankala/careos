from __future__ import annotations

from datetime import UTC, datetime, timedelta

from careos.db.repositories.store import InMemoryStore


def test_inmemory_personalization_rules_respect_ttl() -> None:
    store = InMemoryStore()
    now = datetime.now(UTC)
    store.create_personalization_rule(
        tenant_id="tenant-1",
        patient_id="patient-1",
        actor_participant_id="actor-1",
        rule_type="critical_only_today",
        rule_payload={"allow_only": ["A"]},
        expires_at=now + timedelta(minutes=30),
    )
    store.create_personalization_rule(
        tenant_id="tenant-1",
        patient_id="patient-1",
        actor_participant_id="actor-1",
        rule_type="expired_rule",
        rule_payload={},
        expires_at=now - timedelta(minutes=1),
    )
    active = store.list_active_personalization_rules(tenant_id="tenant-1", patient_id="patient-1", now=now)
    assert len(active) == 1
    assert active[0]["rule_type"] == "critical_only_today"


def test_inmemory_mediation_decision_idempotency() -> None:
    store = InMemoryStore()
    first = store.log_mediation_decision(
        event_id="evt-1",
        tenant_id="tenant-1",
        patient_id="patient-1",
        participant_id="participant-1",
        action="suppress",
        reason="critical_only_today",
        policy_snapshot={"criticality_class": "C", "suppression_allowed": True},
        personalization_snapshot={"rule_type": "critical_only_today"},
        rendered_text="",
        correlation_id="corr-1",
        idempotency_key="mediation:evt-1",
    )
    second = store.log_mediation_decision(
        event_id="evt-1",
        tenant_id="tenant-1",
        patient_id="patient-1",
        participant_id="participant-1",
        action="suppress",
        reason="critical_only_today",
        policy_snapshot={"criticality_class": "C", "suppression_allowed": True},
        personalization_snapshot={"rule_type": "critical_only_today"},
        rendered_text="",
        correlation_id="corr-1",
        idempotency_key="mediation:evt-1",
    )
    assert first is True
    assert second is False


def test_inmemory_patient_clinical_facts_upsert_latest_active_by_key() -> None:
    store = InMemoryStore()
    first = store.upsert_patient_clinical_fact(
        tenant_id="tenant-1",
        patient_id="patient-1",
        actor_participant_id="actor-1",
        fact_key="recent_procedure",
        fact_value={"procedure": "PCI", "date": "2026-02-26"},
        summary="PCI on 2026-02-26.",
        source="caregiver_reported",
        effective_at=None,
    )
    second = store.upsert_patient_clinical_fact(
        tenant_id="tenant-1",
        patient_id="patient-1",
        actor_participant_id="actor-2",
        fact_key="recent_procedure",
        fact_value={"procedure": "Coronary stent placement", "date": "2026-02-27"},
        summary="Coronary stent placement on 2026-02-27.",
        source="caregiver_reported",
        effective_at=None,
    )

    active = store.list_active_patient_clinical_facts(tenant_id="tenant-1", patient_id="patient-1")
    assert len(active) == 1
    assert active[0]["id"] == second["id"]
    assert active[0]["summary"] == "Coronary stent placement on 2026-02-27."
    assert store.patient_clinical_facts[first["id"]]["status"] == "superseded"


def test_inmemory_patient_clinical_facts_can_be_forgotten() -> None:
    store = InMemoryStore()
    inserted = store.upsert_patient_clinical_fact(
        tenant_id="tenant-1",
        patient_id="patient-1",
        actor_participant_id="actor-1",
        fact_key="recent_procedure",
        fact_value={"procedure": "PCI", "date": "2026-02-26"},
        summary="PCI on 2026-02-26.",
        source="caregiver_reported",
        effective_at=None,
    )
    forgotten = store.deactivate_patient_clinical_fact(
        tenant_id="tenant-1",
        patient_id="patient-1",
        fact_key="recent_procedure",
    )
    active = store.list_active_patient_clinical_facts(tenant_id="tenant-1", patient_id="patient-1")
    assert forgotten is not None
    assert forgotten["id"] == inserted["id"]
    assert forgotten["status"] == "forgotten"
    assert active == []


def test_inmemory_patient_observations_respect_expiry() -> None:
    store = InMemoryStore()
    now = datetime.now(UTC)
    store.create_patient_observation(
        tenant_id="tenant-1",
        patient_id="patient-1",
        actor_participant_id="actor-1",
        observation_key="sleep_last_night",
        observation_value={"hours": 4},
        summary="slept 4 hours last night",
        source="caregiver_reported",
        observed_at=now,
        expires_at=now + timedelta(hours=30),
    )
    store.create_patient_observation(
        tenant_id="tenant-1",
        patient_id="patient-1",
        actor_participant_id="actor-1",
        observation_key="pain_today",
        observation_value={"level": "mild"},
        summary="pain today is mild",
        source="caregiver_reported",
        observed_at=now - timedelta(hours=3),
        expires_at=now - timedelta(minutes=1),
    )

    active = store.list_active_patient_observations(tenant_id="tenant-1", patient_id="patient-1", now=now)
    assert len(active) == 1
    assert active[0]["observation_key"] == "sleep_last_night"


def test_inmemory_patient_day_plans_upsert_latest_active_by_key_and_day() -> None:
    store = InMemoryStore()
    now = datetime.now(UTC)
    first = store.upsert_patient_day_plan(
        tenant_id="tenant-1",
        patient_id="patient-1",
        actor_participant_id="actor-1",
        plan_key="doctor_visit",
        plan_value={"time": "16:00"},
        summary="doctor visit at 4 pm today",
        source="caregiver_reported",
        plan_date=now.date(),
        expires_at=now + timedelta(hours=6),
    )
    second = store.upsert_patient_day_plan(
        tenant_id="tenant-1",
        patient_id="patient-1",
        actor_participant_id="actor-1",
        plan_key="doctor_visit",
        plan_value={"time": "17:00"},
        summary="doctor visit moved to 5 pm today",
        source="caregiver_reported",
        plan_date=now.date(),
        expires_at=now + timedelta(hours=7),
    )

    active = store.list_active_patient_day_plans(
        tenant_id="tenant-1",
        patient_id="patient-1",
        plan_date=now.date(),
        now=now,
    )
    assert len(active) == 1
    assert active[0]["id"] == second["id"]
    assert store.patient_day_plans[first["id"]]["status"] == "superseded"


def test_inmemory_patient_day_plans_can_be_forgotten() -> None:
    store = InMemoryStore()
    now = datetime.now(UTC)
    inserted = store.upsert_patient_day_plan(
        tenant_id="tenant-1",
        patient_id="patient-1",
        actor_participant_id="actor-1",
        plan_key="doctor_visit",
        plan_value={"time": "16:00"},
        summary="doctor visit at 4 pm today",
        source="caregiver_reported",
        plan_date=now.date(),
        expires_at=now + timedelta(hours=6),
    )
    forgotten = store.deactivate_patient_day_plan(
        tenant_id="tenant-1",
        patient_id="patient-1",
        plan_key="doctor_visit",
        plan_date=now.date(),
    )
    active = store.list_active_patient_day_plans(
        tenant_id="tenant-1",
        patient_id="patient-1",
        plan_date=now.date(),
        now=now,
    )
    assert forgotten is not None
    assert forgotten["id"] == inserted["id"]
    assert forgotten["status"] == "forgotten"
    assert active == []
