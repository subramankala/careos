from datetime import UTC, date, datetime

import pytest

from careos.app_context import context
from careos.domain.models.api import PatientCreate, TenantCreate


def test_patient_context_service_rejects_tenant_patient_mismatch() -> None:
    tenant_a = context.store.create_tenant(TenantCreate(name="A", type="family", timezone="UTC", status="active"))
    tenant_b = context.store.create_tenant(TenantCreate(name="B", type="family", timezone="UTC", status="active"))
    patient = context.store.create_patient(
        PatientCreate(
            tenant_id=str(tenant_a["id"]),
            display_name="P",
            timezone="UTC",
            primary_language="en",
            persona_type="caregiver_managed_elder",
            risk_level="medium",
            status="active",
        )
    )
    with pytest.raises(ValueError):
        context.patient_context.upsert_clinical_fact(
            tenant_id=str(tenant_b["id"]),
            patient_id=str(patient["id"]),
            actor_participant_id="actor-1",
            fact_key="recent_procedure",
            fact_value={"procedure": "PCI"},
            summary="PCI in Feb 2026.",
            source="caregiver_reported",
            effective_at=datetime.now(UTC),
        )


def test_patient_context_service_lists_active_clinical_facts() -> None:
    tenant = context.store.create_tenant(TenantCreate(name="A", type="family", timezone="UTC", status="active"))
    patient = context.store.create_patient(
        PatientCreate(
            tenant_id=str(tenant["id"]),
            display_name="P",
            timezone="UTC",
            primary_language="en",
            persona_type="caregiver_managed_elder",
            risk_level="medium",
            status="active",
        )
    )

    inserted = context.patient_context.upsert_clinical_fact(
        tenant_id=str(tenant["id"]),
        patient_id=str(patient["id"]),
        actor_participant_id="actor-1",
        fact_key="implant_history",
        fact_value={"implant": "pacemaker", "date": "2024-04-18"},
        summary="Pacemaker implanted on 2024-04-18.",
        source="caregiver_reported",
        effective_at=datetime(2024, 4, 18, tzinfo=UTC),
    )

    active = context.patient_context.active_clinical_facts(
        tenant_id=str(tenant["id"]),
        patient_id=str(patient["id"]),
    )
    assert len(active) == 1
    assert active[0]["id"] == inserted["id"]
    assert active[0]["fact_key"] == "implant_history"


def test_patient_context_service_lists_active_observations() -> None:
    tenant = context.store.create_tenant(TenantCreate(name="A", type="family", timezone="UTC", status="active"))
    patient = context.store.create_patient(
        PatientCreate(
            tenant_id=str(tenant["id"]),
            display_name="P",
            timezone="UTC",
            primary_language="en",
            persona_type="caregiver_managed_elder",
            risk_level="medium",
            status="active",
        )
    )

    inserted = context.patient_context.add_observation(
        tenant_id=str(tenant["id"]),
        patient_id=str(patient["id"]),
        actor_participant_id="actor-1",
        observation_key="sleep_last_night",
        observation_value={"hours": 4},
        summary="slept 4 hours last night",
        source="caregiver_reported",
        observed_at=datetime(2026, 3, 20, 6, 0, tzinfo=UTC),
        expires_at=datetime(2026, 3, 21, 12, 0, tzinfo=UTC),
    )

    active = context.patient_context.active_observations(
        tenant_id=str(tenant["id"]),
        patient_id=str(patient["id"]),
        now=datetime(2026, 3, 20, 8, 0, tzinfo=UTC),
    )
    assert len(active) == 1
    assert active[0]["id"] == inserted["id"]
    assert active[0]["observation_key"] == "sleep_last_night"


def test_patient_context_service_lists_active_day_plans() -> None:
    tenant = context.store.create_tenant(TenantCreate(name="A", type="family", timezone="UTC", status="active"))
    patient = context.store.create_patient(
        PatientCreate(
            tenant_id=str(tenant["id"]),
            display_name="P",
            timezone="UTC",
            primary_language="en",
            persona_type="caregiver_managed_elder",
            risk_level="medium",
            status="active",
        )
    )

    inserted = context.patient_context.upsert_day_plan(
        tenant_id=str(tenant["id"]),
        patient_id=str(patient["id"]),
        actor_participant_id="actor-1",
        plan_key="doctor_visit",
        plan_value={"time": "16:00"},
        summary="doctor visit at 4 pm today",
        source="caregiver_reported",
        plan_date=date(2026, 3, 20),
        expires_at=datetime(2026, 3, 20, 23, 59, 59, tzinfo=UTC),
    )

    active = context.patient_context.active_day_plans(
        tenant_id=str(tenant["id"]),
        patient_id=str(patient["id"]),
        plan_date=date(2026, 3, 20),
        now=datetime(2026, 3, 20, 8, 0, tzinfo=UTC),
    )
    assert len(active) == 1
    assert active[0]["id"] == inserted["id"]
    assert active[0]["plan_key"] == "doctor_visit"


def test_patient_context_service_defaults_day_plan_queries_to_patient_local_date() -> None:
    tenant = context.store.create_tenant(TenantCreate(name="A", type="family", timezone="UTC", status="active"))
    patient = context.store.create_patient(
        PatientCreate(
            tenant_id=str(tenant["id"]),
            display_name="P",
            timezone="Asia/Kolkata",
            primary_language="en",
            persona_type="caregiver_managed_elder",
            risk_level="medium",
            status="active",
        )
    )

    context.patient_context.upsert_day_plan(
        tenant_id=str(tenant["id"]),
        patient_id=str(patient["id"]),
        actor_participant_id="actor-1",
        plan_key="travel",
        plan_value={"statement": "traveling this evening"},
        summary="traveling this evening",
        source="caregiver_reported",
        plan_date=date(2026, 3, 21),
        expires_at=datetime(2026, 3, 21, 18, 29, 59, tzinfo=UTC),
    )

    active = context.patient_context.active_day_plans(
        tenant_id=str(tenant["id"]),
        patient_id=str(patient["id"]),
        now=datetime(2026, 3, 20, 20, 30, tzinfo=UTC),
    )
    assert len(active) == 1
    assert active[0]["plan_key"] == "travel"
