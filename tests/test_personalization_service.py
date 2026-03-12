from datetime import UTC, datetime, timedelta

import pytest

from careos.app_context import context
from careos.domain.models.api import PatientCreate, TenantCreate


def test_personalization_service_rejects_tenant_patient_mismatch() -> None:
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
        context.personalization.create_rule(
            tenant_id=str(tenant_b["id"]),
            patient_id=str(patient["id"]),
            actor_participant_id="actor-1",
            rule_type="critical_only_today",
            rule_payload={},
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
