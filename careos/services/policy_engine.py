from dataclasses import asdict, dataclass

from careos.domain.enums.core import Criticality, Flexibility, PersonaType


@dataclass
class PolicyDecision:
    reminder_offsets_minutes: list[int]
    escalation_after_minutes: int | None
    max_retries: int
    channel: str
    tone: str


@dataclass
class EventPolicyFlags:
    criticality_class: str
    suppression_allowed: bool
    delay_allowed: bool
    transformation_allowed: bool
    reroute_allowed: bool

    def as_payload(self) -> dict:
        return asdict(self)

    @classmethod
    def default_deny(cls) -> "EventPolicyFlags":
        return cls(
            criticality_class="A",
            suppression_allowed=False,
            delay_allowed=False,
            transformation_allowed=False,
            reroute_allowed=False,
        )


class PolicyEngine:
    def decide(
        self,
        *,
        criticality: Criticality,
        flexibility: Flexibility,
        persona: PersonaType,
    ) -> PolicyDecision:
        if criticality == Criticality.HIGH and flexibility == Flexibility.RIGID:
            base = PolicyDecision([0, 10, 20], 30, 3, "whatsapp", "firm_supportive")
        elif criticality == Criticality.HIGH and flexibility in {Flexibility.WINDOWED, Flexibility.FLEXIBLE}:
            base = PolicyDecision([0, 30, 60], 90, 3, "whatsapp", "supportive")
        elif criticality == Criticality.MEDIUM:
            base = PolicyDecision([0, 30], 120, 2, "whatsapp", "encouraging")
        else:
            base = PolicyDecision([0], None, 1, "whatsapp", "light")

        if persona == PersonaType.BUSY_PROFESSIONAL:
            return PolicyDecision(base.reminder_offsets_minutes[:2], base.escalation_after_minutes, 2, base.channel, "concise")
        if persona == PersonaType.SKEPTICAL_RESISTANT:
            return PolicyDecision(base.reminder_offsets_minutes[:1], base.escalation_after_minutes, 1, base.channel, "explanatory")
        return base

    def event_policy_flags(
        self,
        *,
        criticality: Criticality,
        flexibility: Flexibility,
    ) -> EventPolicyFlags:
        if criticality == Criticality.HIGH and flexibility == Flexibility.RIGID:
            return EventPolicyFlags(
                criticality_class="A",
                suppression_allowed=False,
                delay_allowed=False,
                transformation_allowed=True,
                reroute_allowed=True,
            )
        if criticality == Criticality.HIGH:
            return EventPolicyFlags(
                criticality_class="B",
                suppression_allowed=False,
                delay_allowed=True,
                transformation_allowed=True,
                reroute_allowed=True,
            )
        if criticality == Criticality.MEDIUM:
            return EventPolicyFlags(
                criticality_class="B",
                suppression_allowed=False,
                delay_allowed=True,
                transformation_allowed=True,
                reroute_allowed=True,
            )
        return EventPolicyFlags(
            criticality_class="C",
            suppression_allowed=True,
            delay_allowed=True,
            transformation_allowed=True,
            reroute_allowed=True,
        )

    def normalize_event_policy_flags(self, payload: dict | None) -> EventPolicyFlags:
        if not payload:
            return EventPolicyFlags.default_deny()
        required = {
            "criticality_class",
            "suppression_allowed",
            "delay_allowed",
            "transformation_allowed",
            "reroute_allowed",
        }
        if not required.issubset(payload.keys()):
            return EventPolicyFlags.default_deny()
        try:
            return EventPolicyFlags(
                criticality_class=str(payload["criticality_class"]),
                suppression_allowed=bool(payload["suppression_allowed"]),
                delay_allowed=bool(payload["delay_allowed"]),
                transformation_allowed=bool(payload["transformation_allowed"]),
                reroute_allowed=bool(payload["reroute_allowed"]),
            )
        except Exception:
            return EventPolicyFlags.default_deny()
