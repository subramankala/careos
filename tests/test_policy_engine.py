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
