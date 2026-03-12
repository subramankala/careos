from datetime import UTC, datetime

from careos.gateway.outbound_policy import decide_outbound_action, normalize_policy


def test_normalize_policy_defaults_to_deny_when_missing() -> None:
    normalized = normalize_policy({"criticality_class": "C"})
    assert normalized["criticality_class"] == "A"
    assert normalized["suppression_allowed"] is False


def test_critical_only_rule_suppresses_class_c_when_allowed() -> None:
    decision = decide_outbound_action(
        event_policy={
            "criticality_class": "C",
            "suppression_allowed": True,
            "delay_allowed": True,
            "transformation_allowed": True,
            "reroute_allowed": True,
        },
        active_rules=[{"rule_type": "critical_only_today"}],
        now=datetime.now(UTC),
    )
    assert decision.action == "suppress"


def test_class_a_never_suppressed_even_with_critical_only_rule() -> None:
    decision = decide_outbound_action(
        event_policy={
            "criticality_class": "A",
            "suppression_allowed": False,
            "delay_allowed": False,
            "transformation_allowed": True,
            "reroute_allowed": True,
        },
        active_rules=[{"rule_type": "critical_only_today"}],
        now=datetime.now(UTC),
    )
    assert decision.action == "send"
