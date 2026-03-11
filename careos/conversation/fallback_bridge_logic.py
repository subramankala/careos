from __future__ import annotations

import re
from datetime import UTC, datetime

from careos.conversation.deterministic_router import DeterministicRouter
from careos.domain.enums.core import WinState
from careos.domain.models.api import ParticipantContext
from careos.services.win_service import WinService


def map_plain_english_to_command(text: str) -> str | None:
    raw = text.strip()
    lower = raw.lower()

    if not raw:
        return "help"
    if lower in {"help", "?"} or "what can you do" in lower:
        return "help"
    if "schedule" in lower or "pending today" in lower or "left today" in lower:
        return "schedule"
    if "next" in lower:
        return "next"
    if "status" in lower or "adherence" in lower or "how am i doing" in lower:
        return "status"

    done_match = re.search(r"\b(?:done|complete|completed|took|taken|mark)\s+(\d+)\b", lower)
    if done_match:
        return f"done {done_match.group(1)}"
    done_mark_match = re.search(r"\bmark\s+(\d+)\s+as?\s+done\b", lower)
    if done_mark_match:
        return f"done {done_mark_match.group(1)}"

    skip_match = re.search(r"\b(?:skip|skipped)\s+(\d+)\b", lower)
    if skip_match:
        return f"skip {skip_match.group(1)}"

    delay_match = re.search(r"\b(?:delay|snooze)\s+(\d+)\s+(\d+)\b", lower)
    if delay_match:
        return f"delay {delay_match.group(1)} {delay_match.group(2)}"

    return None


def resolve_fallback_text(text: str, participant_context: ParticipantContext, win_service: WinService) -> str:
    lower = text.strip().lower()
    if (
        ("how many" in lower or "count" in lower)
        and ("medication" in lower or "medications" in lower or "meds" in lower)
        and ("took" in lower or "taken" in lower or "completed" in lower)
        and "today" in lower
    ):
        today = win_service.today(participant_context.patient_id, at=datetime.now(UTC))
        med_items = [item for item in today.timeline if item.category.strip().lower() == "medication"]
        completed_meds = [item for item in med_items if item.current_state == WinState.COMPLETED]
        return (
            f"You completed {len(completed_meds)} of {len(med_items)} scheduled medications today "
            f"({today.date}, {today.timezone})."
        )

    mapped = map_plain_english_to_command(text)
    if mapped is None:
        return (
            "I can help with schedule, next, status, done <item>, delay <item> <minutes>, and skip <item>. "
            "Try: 'schedule' or 'done 1'."
        )
    router = DeterministicRouter(win_service)
    result = router.handle(mapped, participant_context)
    return result.text


def fallback_intent(text: str) -> str:
    lower = text.strip().lower()
    if (
        ("how many" in lower or "count" in lower)
        and ("medication" in lower or "medications" in lower or "meds" in lower)
        and ("took" in lower or "taken" in lower or "completed" in lower)
        and "today" in lower
    ):
        return "medication_count_today"
    mapped = map_plain_english_to_command(text)
    return mapped or "unmapped"
