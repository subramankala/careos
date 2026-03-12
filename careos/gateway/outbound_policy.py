from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass
class OutboundDecision:
    action: str  # send | suppress | delay
    reason: str
    delay_until: datetime | None = None


def _default_deny_policy() -> dict:
    return {
        "criticality_class": "A",
        "suppression_allowed": False,
        "delay_allowed": False,
        "transformation_allowed": False,
        "reroute_allowed": False,
    }


def normalize_policy(policy: dict | None) -> dict:
    if not policy:
        return _default_deny_policy()
    required = {
        "criticality_class",
        "suppression_allowed",
        "delay_allowed",
        "transformation_allowed",
        "reroute_allowed",
    }
    if not required.issubset(policy.keys()):
        return _default_deny_policy()
    out = {
        "criticality_class": str(policy.get("criticality_class", "A")),
        "suppression_allowed": bool(policy.get("suppression_allowed", False)),
        "delay_allowed": bool(policy.get("delay_allowed", False)),
        "transformation_allowed": bool(policy.get("transformation_allowed", False)),
        "reroute_allowed": bool(policy.get("reroute_allowed", False)),
    }
    if out["criticality_class"] not in {"A", "B", "C"}:
        return _default_deny_policy()
    return out


def decide_outbound_action(
    *,
    event_policy: dict | None,
    active_rules: list[dict],
    now: datetime | None = None,
) -> OutboundDecision:
    ts = now or datetime.now(UTC)
    policy = normalize_policy(event_policy)
    rule_types = {str(rule.get("rule_type", "")) for rule in active_rules}

    if policy["criticality_class"] == "A":
        return OutboundDecision(action="send", reason="class_a_non_negotiable")

    if "critical_only_today" in rule_types:
        if policy["suppression_allowed"]:
            return OutboundDecision(action="suppress", reason="critical_only_today")
        return OutboundDecision(action="send", reason="critical_only_today_but_suppression_disallowed")

    if "delay_non_critical_30m" in rule_types and policy["delay_allowed"]:
        return OutboundDecision(action="delay", reason="delay_non_critical_30m", delay_until=ts + timedelta(minutes=30))

    return OutboundDecision(action="send", reason="default_send")
