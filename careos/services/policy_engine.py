from dataclasses import dataclass

from careos.domain.enums.core import Criticality, Flexibility, PersonaType


@dataclass
class PolicyDecision:
    reminder_offsets_minutes: list[int]
    escalation_after_minutes: int | None
    max_retries: int
    channel: str
    tone: str


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
