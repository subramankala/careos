from datetime import UTC, datetime

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
