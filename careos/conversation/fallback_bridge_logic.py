from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from urllib.error import URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from careos.conversation.deterministic_router import DeterministicRouter
from careos.domain.enums.core import WinState
from careos.domain.models.api import ParticipantContext
from careos.logging import get_logger
from careos.services.win_service import WinService
from careos.settings import settings

logger = get_logger("fallback_bridge")

ALLOWED_INTENTS = {
    "schedule",
    "schedule_tomorrow",
    "next",
    "status",
    "critical_missed_today",
    "done",
    "skip",
    "delay",
    "help",
    "medication_count_today",
    "clarify",
}


def _rule_map_plain_english_to_command(text: str) -> str | None:
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


def _timeline_for_offset_days(
    participant_context: ParticipantContext, win_service: WinService, days_offset: int
):
    tz = ZoneInfo(participant_context.patient_timezone)
    now_local = datetime.now(tz)
    target_local = now_local + timedelta(days=days_offset)
    target_utc = target_local.astimezone(UTC)
    return win_service.today(participant_context.patient_id, at=target_utc)


def _timeline_snapshot(response) -> list[dict[str, str]]:
    return [
        {
            "item_no": str(index),
            "title": item.title,
            "category": item.category,
            "criticality": item.criticality.value,
            "state": item.current_state.value,
            "scheduled_start": item.scheduled_start.isoformat(),
        }
        for index, item in enumerate(response.timeline, start=1)
    ]


def _format_timeline(prefix: str, response) -> str:
    if not response.timeline:
        return f"{prefix}: no wins scheduled."
    tz = ZoneInfo(response.timezone)
    lines = [f"{prefix} ({response.date}):"]
    for idx, item in enumerate(response.timeline, start=1):
        local_time = item.scheduled_start.astimezone(tz).strftime("%H:%M")
        lines.append(f"{idx}. {local_time} {item.title} [{item.current_state.value}]")
    return "\n".join(lines)


def _medication_count_today_text(participant_context: ParticipantContext, win_service: WinService) -> str:
    today = _timeline_for_offset_days(participant_context, win_service, 0)
    med_items = [item for item in today.timeline if item.category.strip().lower() == "medication"]
    completed_meds = [item for item in med_items if item.current_state == WinState.COMPLETED]
    return (
        f"You completed {len(completed_meds)} of {len(med_items)} scheduled medications today "
        f"({today.date}, {today.timezone})."
    )


def _critical_missed_today_text(participant_context: ParticipantContext, win_service: WinService) -> str:
    today = _timeline_for_offset_days(participant_context, win_service, 0)
    critical_missed = [
        item.title
        for item in today.timeline
        if item.criticality.value == "high" and item.current_state.value == "missed"
    ]
    if not critical_missed:
        return "No critical wins are missed today."
    lines = ["Missed critical wins today:"]
    lines.extend([f"- {title}" for title in critical_missed])
    return "\n".join(lines)


def _llm_intent(text: str, participant_context: ParticipantContext, win_service: WinService) -> dict | None:
    if not settings.openai_api_key:
        return None
    today = _timeline_for_offset_days(participant_context, win_service, 0)
    tomorrow = _timeline_for_offset_days(participant_context, win_service, 1)
    status = win_service.status(participant_context.patient_id, at=datetime.now(UTC))
    payload = {
        "text": text,
        "patient_timezone": participant_context.patient_timezone,
        "timeline_today": _timeline_snapshot(today),
        "timeline_tomorrow": _timeline_snapshot(tomorrow),
        "status_today": {
            "completed": status.completed_count,
            "due": status.due_count,
            "missed": status.missed_count,
            "skipped": status.skipped_count,
            "adherence_score": status.adherence_score,
        },
        "allowed_intents": sorted(ALLOWED_INTENTS),
    }
    system = (
        "You are a strict intent parser for CareOS. "
        "Return JSON only with keys: intent, item_no, minutes, reply. "
        "Use only allowed intents. "
        "Use schedule_tomorrow for tomorrow/next-day schedule questions. "
        "Use critical_missed_today for questions about missed critical meds/tasks. "
        "Use medication_count_today for questions about total meds taken/completed today. "
        "Choose clarify only when truly unclear; do not ask for clarification if provided data already answers."
    )
    request_payload = {
        "model": settings.openai_model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload)},
        ],
    }
    req = Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(request_payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.openai_api_key}",
        },
    )
    try:
        with urlopen(req, timeout=max(settings.openai_timeout_seconds, 1)) as resp:  # noqa: S310
            body = json.loads(resp.read().decode("utf-8"))
    except (URLError, OSError, ValueError, TimeoutError):
        logger.exception("nl_fallback_llm_error")
        return None
    try:
        raw = body["choices"][0]["message"]["content"]
        parsed = json.loads(raw)
        intent_name = str(parsed.get("intent", "")).strip()
        if intent_name not in ALLOWED_INTENTS:
            return None
        logger.info("nl_fallback_llm_intent", intent=intent_name)
        return parsed
    except (KeyError, IndexError, TypeError, ValueError):
        logger.warning("nl_fallback_llm_parse_error")
        return None


def _intent_to_command(intent: dict) -> tuple[str | None, str | None]:
    name = str(intent.get("intent", "")).strip()
    if name == "schedule":
        return "schedule", None
    if name == "schedule_tomorrow":
        return "__schedule_tomorrow__", None
    if name == "next":
        return "next", None
    if name == "status":
        return "status", None
    if name == "critical_missed_today":
        return "__critical_missed_today__", None
    if name == "help":
        return "help", None
    if name == "done":
        item_no = int(intent.get("item_no", 0) or 0)
        return (f"done {item_no}", None) if item_no > 0 else (None, "Tell me which item number to mark done.")
    if name == "skip":
        item_no = int(intent.get("item_no", 0) or 0)
        return (f"skip {item_no}", None) if item_no > 0 else (None, "Tell me which item number to skip.")
    if name == "delay":
        item_no = int(intent.get("item_no", 0) or 0)
        minutes = int(intent.get("minutes", 0) or 0)
        if item_no > 0 and minutes > 0:
            return f"delay {item_no} {minutes}", None
        return None, "Tell me item number and minutes, for example: delay 2 30."
    if name == "clarify":
        reply = str(intent.get("reply", "")).strip()
        return None, reply or "Please rephrase. You can ask schedule, next, status, done, delay, or skip."
    if name == "medication_count_today":
        return "__medication_count_today__", None
    return None, None


def resolve_fallback_text(text: str, participant_context: ParticipantContext, win_service: WinService) -> str:
    parsed = _llm_intent(text, participant_context, win_service)
    if parsed is not None:
        command, direct_reply = _intent_to_command(parsed)
        if direct_reply:
            return direct_reply
        if command == "__medication_count_today__":
            return _medication_count_today_text(participant_context, win_service)
        if command == "__schedule_tomorrow__":
            tomorrow = _timeline_for_offset_days(participant_context, win_service, 1)
            return _format_timeline("Tomorrow schedule", tomorrow)
        if command == "__critical_missed_today__":
            return _critical_missed_today_text(participant_context, win_service)
        if command:
            router = DeterministicRouter(win_service)
            return router.handle(command, participant_context).text

    lower = text.strip().lower()
    if (
        ("how many" in lower or "count" in lower or "total" in lower)
        and ("medication" in lower or "medications" in lower or "meds" in lower)
        and ("took" in lower or "taken" in lower or "completed" in lower)
        and "today" in lower
    ):
        return _medication_count_today_text(participant_context, win_service)
    if "tomorrow" in lower or "next day" in lower:
        tomorrow = _timeline_for_offset_days(participant_context, win_service, 1)
        return _format_timeline("Tomorrow schedule", tomorrow)
    if "critical" in lower and ("missed" in lower or "due" in lower or "pending" in lower):
        return _critical_missed_today_text(participant_context, win_service)

    mapped = _rule_map_plain_english_to_command(text)
    if mapped is None:
        return (
            "I can help with schedule, next, status, done <item>, delay <item> <minutes>, and skip <item>. "
            "Try: 'schedule' or 'done 1'."
        )
    router = DeterministicRouter(win_service)
    return router.handle(mapped, participant_context).text


def fallback_intent(text: str) -> str:
    lower = text.strip().lower()
    if (
        ("how many" in lower or "count" in lower or "total" in lower)
        and ("medication" in lower or "medications" in lower or "meds" in lower)
        and ("took" in lower or "taken" in lower or "completed" in lower)
        and "today" in lower
    ):
        return "medication_count_today"
    if "tomorrow" in lower or "next day" in lower:
        return "schedule_tomorrow"
    if "critical" in lower and ("missed" in lower or "due" in lower or "pending" in lower):
        return "critical_missed_today"
    mapped = _rule_map_plain_english_to_command(text)
    return mapped or "unmapped"
