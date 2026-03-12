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
