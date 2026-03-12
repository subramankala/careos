from careos.domain.enums.core import Criticality, Flexibility, PersonaType
from careos.services.policy_engine import PolicyEngine


def test_high_rigid_policy_is_strict() -> None:
    engine = PolicyEngine()
    decision = engine.decide(
        criticality=Criticality.HIGH,
        flexibility=Flexibility.RIGID,
        persona=PersonaType.CAREGIVER_MANAGED_ELDER,
    )
    assert decision.max_retries == 3
    assert decision.escalation_after_minutes == 30


def test_skeptical_persona_reduces_retries() -> None:
    engine = PolicyEngine()
    decision = engine.decide(
        criticality=Criticality.MEDIUM,
        flexibility=Flexibility.WINDOWED,
        persona=PersonaType.SKEPTICAL_RESISTANT,
    )
    assert decision.max_retries == 1


def test_event_policy_flags_high_rigid_are_non_negotiable() -> None:
    engine = PolicyEngine()
    flags = engine.event_policy_flags(
        criticality=Criticality.HIGH,
        flexibility=Flexibility.RIGID,
    )
    assert flags.criticality_class == "A"
    assert flags.suppression_allowed is False
    assert flags.delay_allowed is False


def test_event_policy_flags_low_flexible_allow_suppression() -> None:
    engine = PolicyEngine()
    flags = engine.event_policy_flags(
        criticality=Criticality.LOW,
        flexibility=Flexibility.FLEXIBLE,
    )
    assert flags.criticality_class == "C"
    assert flags.suppression_allowed is True
    assert flags.delay_allowed is True


def test_normalize_event_policy_flags_defaults_to_deny_on_missing_fields() -> None:
    engine = PolicyEngine()
    flags = engine.normalize_event_policy_flags({"criticality_class": "C", "suppression_allowed": True})
    assert flags.criticality_class == "A"
    assert flags.suppression_allowed is False
    assert flags.delay_allowed is False
    assert flags.transformation_allowed is False
    assert flags.reroute_allowed is False
