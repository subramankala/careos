from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.error import URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from careos.settings import settings


@dataclass(frozen=True)
class StructuredActionProposal:
    action_type: str
    entity_type: str
    category: str
    title: str
    instructions: str
    patient_id: str
    tenant_id: str
    actor_id: str
    start_at: datetime
    end_at: datetime
    criticality: str
    flexibility: str
    confirmation_text: str
    target_instance_id: str = ""
    delay_minutes: int = 0


def _next_window_start(now_local: datetime, *, minimum_minutes_ahead: int = 15) -> datetime:
    candidate = now_local + timedelta(minutes=max(minimum_minutes_ahead, 1))
    rounded = candidate.replace(minute=0, second=0, microsecond=0)
    if rounded < candidate:
        rounded = rounded + timedelta(hours=1)
    return rounded


def _likely_create_request(text: str) -> bool:
    lower = text.strip().lower()
    if not lower:
        return False
    return any(word in lower for word in {"add", "create", "schedule", "plan", "put", "remind", "need"})


def _confirm_text(*, title: str, description: str) -> str:
    return f"I understood this as: {description}. Reply YES to confirm or CANCEL."


def _likely_complete_request(text: str) -> bool:
    lower = text.strip().lower()
    if not lower:
        return False
    return any(phrase in lower for phrase in {"done", "completed", "finished", "i got", "i did"})


def _likely_update_request(text: str) -> bool:
    lower = text.strip().lower()
    if not lower:
        return False
    return any(word in lower for word in {"move", "reschedule", "shift", "delay", "postpone"})


def _normalize_tokens(text: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", text.lower()) if token]


def _resolve_timeline_match(text: str, timeline: list[dict]) -> dict | None:
    request_tokens = {
        token
        for token in _normalize_tokens(text)
        if token
        not in {
            "my",
            "the",
            "a",
            "an",
            "to",
            "for",
            "today",
            "tomorrow",
            "morning",
            "afternoon",
            "evening",
            "night",
            "done",
            "completed",
            "finished",
            "move",
            "reschedule",
            "shift",
            "delay",
            "postpone",
            "i",
            "got",
            "need",
            "add",
            "create",
            "schedule",
            "plan",
            "put",
            "remind",
            "take",
        }
    }
    best: tuple[int, dict] | None = None
    for item in timeline:
        title_tokens = set(_normalize_tokens(str(item.get("title", ""))))
        overlap = len(request_tokens.intersection(title_tokens))
        if overlap <= 0:
            continue
        if best is None or overlap > best[0]:
            best = (overlap, item)
    return best[1] if best is not None else None


def _normalized_patient_context(context: dict) -> dict[str, list[dict[str, object]]]:
    raw = context.get("patient_context")
    if not isinstance(raw, dict):
        return {
            "clinical_facts": [],
            "recent_observations": [],
            "day_plans": [],
        }

    normalized: dict[str, list[dict[str, object]]] = {
        "clinical_facts": [],
        "recent_observations": [],
        "day_plans": [],
    }
    for row in raw.get("clinical_facts", []) or []:
        if not isinstance(row, dict):
            continue
        normalized["clinical_facts"].append(
            {
                "fact_key": str(row.get("fact_key", "")).strip(),
                "summary": str(row.get("summary", "")).strip(),
                "source": str(row.get("source", "")).strip(),
                "effective_at": str(row.get("effective_at", "")).strip(),
            }
        )
    for row in raw.get("recent_observations", []) or []:
        if not isinstance(row, dict):
            continue
        normalized["recent_observations"].append(
            {
                "observation_key": str(row.get("observation_key", "")).strip(),
                "summary": str(row.get("summary", "")).strip(),
                "source": str(row.get("source", "")).strip(),
                "observed_at": str(row.get("observed_at", "")).strip(),
                "expires_at": str(row.get("expires_at", "")).strip(),
            }
        )
    for row in raw.get("day_plans", []) or []:
        if not isinstance(row, dict):
            continue
        normalized["day_plans"].append(
            {
                "plan_key": str(row.get("plan_key", "")).strip(),
                "summary": str(row.get("summary", "")).strip(),
                "source": str(row.get("source", "")).strip(),
                "plan_date": str(row.get("plan_date", "")).strip(),
                "expires_at": str(row.get("expires_at", "")).strip(),
            }
        )
    return normalized


def _timeline_preview(timeline: list[dict]) -> list[dict[str, object]]:
    preview: list[dict[str, object]] = []
    for item in timeline[:12]:
        if not isinstance(item, dict):
            continue
        preview.append(
            {
                "win_instance_id": str(item.get("win_instance_id", "")).strip(),
                "title": str(item.get("title", "")).strip(),
                "category": str(item.get("category", "")).strip(),
                "scheduled_start": str(item.get("scheduled_start", "")).strip(),
                "scheduled_end": str(item.get("scheduled_end", "")).strip(),
                "current_state": str(item.get("current_state", "")).strip(),
            }
        )
    return preview


def _fallback_walk_task(text: str, context: dict) -> StructuredActionProposal | None:
    lower = text.strip().lower()
    if "walk" not in lower or not _likely_create_request(lower):
        return None
    if not any(word in lower for word in {"today", "tonight", "evening"}):
        return None
    tz = ZoneInfo(str(context["patient_timezone"]))
    now_local = datetime.now(tz)
    target_date = now_local.date()
    start_local = datetime.combine(target_date, datetime.min.time(), tzinfo=tz).replace(hour=18)
    end_local = datetime.combine(target_date, datetime.min.time(), tzinfo=tz).replace(hour=21)
    title = "Evening walk"
    return StructuredActionProposal(
        action_type="create_task",
        entity_type="routine",
        category="routine",
        title=title,
        instructions="Take a walk during the scheduled evening window.",
        patient_id=str(context["patient_id"]),
        tenant_id=str(context["tenant_id"]),
        actor_id=str(context["participant_id"]),
        start_at=start_local.astimezone(UTC),
        end_at=end_local.astimezone(UTC),
        criticality="low",
        flexibility="flexible",
        confirmation_text=_confirm_text(
            title=title,
            description="create a one-time evening walk for today, between 6:00 PM and 9:00 PM",
        ),
    )


def _extract_day_window(text: str) -> int | None:
    lower = text.strip().lower()
    patterns = [
        r"next\s+(\d+)\s+days?",
        r"within\s+(\d+)\s+days?",
        r"over\s+the\s+next\s+(\d+)\s+days?",
    ]
    for pattern in patterns:
        match = re.search(pattern, lower)
        if match:
            return max(int(match.group(1)), 1)
    return None


def _diagnostic_title(text: str) -> str:
    cleaned = re.sub(r"\b(i need to|get|done|over the next \d+ days?|within \d+ days?|next \d+ days?)\b", "", text, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        return "Diagnostic test"
    if cleaned.lower().startswith("a "):
        cleaned = cleaned[2:]
    return cleaned[:1].upper() + cleaned[1:]


def _fallback_diagnostic_task(text: str, context: dict) -> StructuredActionProposal | None:
    lower = text.strip().lower()
    if not _likely_create_request(lower):
        return None
    if not any(keyword in lower for keyword in {"test", "scan", "lab", "mri", "ct", "xray"}):
        return None
    window_days = _extract_day_window(lower)
    if window_days is None:
        return None
    tz = ZoneInfo(str(context["patient_timezone"]))
    now_local = datetime.now(tz)
    start_local = _next_window_start(now_local)
    end_local = start_local + timedelta(days=window_days)
    title = _diagnostic_title(text)
    return StructuredActionProposal(
        action_type="create_task",
        entity_type="diagnostic_test",
        category="diagnostic_test",
        title=title,
        instructions=f"Complete {title.lower()} within the requested time window.",
        patient_id=str(context["patient_id"]),
        tenant_id=str(context["tenant_id"]),
        actor_id=str(context["participant_id"]),
        start_at=start_local.astimezone(UTC),
        end_at=end_local.astimezone(UTC),
        criticality="medium",
        flexibility="windowed",
        confirmation_text=_confirm_text(
            title=title,
            description=f"create a task to complete {title.lower()} within the next {window_days} days",
        ),
    )


def _fallback_appointment_task(text: str, context: dict) -> StructuredActionProposal | None:
    lower = text.strip().lower()
    if not _likely_create_request(lower):
        return None
    if not any(keyword in lower for keyword in {"appointment", "visit", "consult"}):
        return None
    tz = ZoneInfo(str(context["patient_timezone"]))
    now_local = datetime.now(tz)
    target_date = now_local.date()
    if "tomorrow" in lower:
        target_date = target_date + timedelta(days=1)
    start_hour = 9
    end_hour = 12
    if "morning" in lower:
        start_hour, end_hour = 9, 12
    elif "afternoon" in lower:
        start_hour, end_hour = 13, 16
    elif "evening" in lower:
        start_hour, end_hour = 17, 20
    start_local = datetime.combine(target_date, datetime.min.time(), tzinfo=tz).replace(hour=start_hour)
    end_local = datetime.combine(target_date, datetime.min.time(), tzinfo=tz).replace(hour=end_hour)
    title = "Appointment"
    if "cardio" in lower:
        title = "Cardiology appointment"
    elif "doctor" in lower:
        title = "Doctor appointment"
    return StructuredActionProposal(
        action_type="create_task",
        entity_type="appointment",
        category="appointment",
        title=title,
        instructions=f"Attend {title.lower()} during the scheduled window.",
        patient_id=str(context["patient_id"]),
        tenant_id=str(context["tenant_id"]),
        actor_id=str(context["participant_id"]),
        start_at=start_local.astimezone(UTC),
        end_at=end_local.astimezone(UTC),
        criticality="medium",
        flexibility="windowed",
        confirmation_text=_confirm_text(
            title=title,
            description=(
                f"create a one-time {title.lower()} "
                f"between {start_local.strftime('%-I:%M %p')} and {end_local.strftime('%-I:%M %p')} "
                f"on {start_local.strftime('%d %b')}"
            ),
        ),
    )


def _fallback_medication_reminder_task(text: str, context: dict) -> StructuredActionProposal | None:
    lower = text.strip().lower()
    if not _likely_create_request(lower):
        return None
    has_medication_signal = any(keyword in lower for keyword in {"med", "medication", "tablet", "pill", "dose"})
    if not has_medication_signal and "take " not in lower:
        return None
    if not any(keyword in lower for keyword in {"remind", "reminder", "take"}):
        return None
    tz = ZoneInfo(str(context["patient_timezone"]))
    now_local = datetime.now(tz)
    target_date = now_local.date()
    if "tomorrow" in lower:
        target_date = target_date + timedelta(days=1)
    start_hour = 20 if "evening" in lower or "night" in lower else 8
    end_hour = start_hour + 1
    start_local = datetime.combine(target_date, datetime.min.time(), tzinfo=tz).replace(hour=start_hour)
    end_local = datetime.combine(target_date, datetime.min.time(), tzinfo=tz).replace(hour=end_hour)
    cleaned = re.sub(r"\b(add|create|schedule|put|remind me to|remind|take|for|today|tomorrow|evening|morning|night)\b", "", text, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    title = cleaned[:1].upper() + cleaned[1:] if cleaned else "Medication reminder"
    return StructuredActionProposal(
        action_type="create_task",
        entity_type="medication_reminder",
        category="medication",
        title=title,
        instructions=f"Medication reminder for {title.lower()}.",
        patient_id=str(context["patient_id"]),
        tenant_id=str(context["tenant_id"]),
        actor_id=str(context["participant_id"]),
        start_at=start_local.astimezone(UTC),
        end_at=end_local.astimezone(UTC),
        criticality="high",
        flexibility="windowed",
        confirmation_text=_confirm_text(
            title=title,
            description=(
                f"create a medication reminder for {title.lower()} "
                f"around {start_local.strftime('%-I:%M %p')} on {start_local.strftime('%d %b')}"
            ),
        ),
    )


def _llm_task_proposal(text: str, context: dict, timeline: list[dict] | None = None) -> StructuredActionProposal | None:
    if not settings.openai_api_key or not _likely_create_request(text):
        return None
    timeline_rows = timeline or []
    payload = {
        "text": text,
        "patient_timezone": str(context["patient_timezone"]),
        "patient_context": _normalized_patient_context(context),
        "timeline_preview": _timeline_preview(timeline_rows),
        "allowed_actions": ["create_task", "none"],
        "allowed_entity_types": ["routine", "diagnostic_test", "appointment", "medication_reminder"],
        "now_utc": datetime.now(UTC).isoformat(),
    }
    system = (
        "You convert natural language into a proposed structured action. "
        "Use patient_context as patient-specific grounding when it is relevant. "
        "Clinical facts are durable history, recent observations are near-term state, and day plans are same-day practical constraints. "
        "If the request depends on that context, reflect it in the title, instructions, timing, and confirmation-safe interpretation. "
        "Use timeline_preview only as current schedule context, not as durable history. "
        "Return JSON only with keys: action, entity_type, category, title, instructions, start_offset_hours, "
        "end_offset_hours, criticality, flexibility, confidence. "
        "Use action=create_task only for clear requests to create a task/reminder. Otherwise use action=none."
    )
    req_payload = {
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
        method="POST",
        data=json.dumps(req_payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {settings.openai_api_key}"},
    )
    try:
        with urlopen(req, timeout=max(getattr(settings, "openai_timeout_seconds", 15), 1)) as resp:  # noqa: S310
            body = json.loads(resp.read().decode("utf-8"))
        raw = body["choices"][0]["message"]["content"]
        parsed = json.loads(raw)
    except (URLError, OSError, ValueError, TimeoutError, KeyError, IndexError, TypeError):
        return None

    if str(parsed.get("action", "")).strip() != "create_task":
        return None
    confidence = float(parsed.get("confidence", 0.0) or 0.0)
    if confidence < 0.7:
        return None
    tz = ZoneInfo(str(context["patient_timezone"]))
    now_local = _next_window_start(datetime.now(tz))
    start_offset_hours = int(parsed.get("start_offset_hours", 0) or 0)
    end_offset_hours = int(parsed.get("end_offset_hours", start_offset_hours + 2) or (start_offset_hours + 2))
    if end_offset_hours <= start_offset_hours:
        end_offset_hours = start_offset_hours + 2
    start_local = now_local + timedelta(hours=start_offset_hours)
    end_local = now_local + timedelta(hours=end_offset_hours)
    title = str(parsed.get("title", "")).strip() or "New task"
    entity_type = str(parsed.get("entity_type", "")).strip() or "routine"
    category = str(parsed.get("category", "")).strip() or entity_type
    instructions = str(parsed.get("instructions", "")).strip() or f"Complete {title.lower()}."
    criticality = str(parsed.get("criticality", "")).strip() or "low"
    flexibility = str(parsed.get("flexibility", "")).strip() or "flexible"
    confirmation = _confirm_text(
        title=title,
        description=(
            f"create a task for {title.lower()}, between "
            f"{start_local.strftime('%-I:%M %p')} and {end_local.strftime('%-I:%M %p')}"
        ),
    )
    return StructuredActionProposal(
        action_type="create_task",
        entity_type=entity_type,
        category=category,
        title=title,
        instructions=instructions,
        patient_id=str(context["patient_id"]),
        tenant_id=str(context["tenant_id"]),
        actor_id=str(context["participant_id"]),
        start_at=start_local.astimezone(UTC),
        end_at=end_local.astimezone(UTC),
        criticality=criticality,
        flexibility=flexibility,
        confirmation_text=confirmation,
    )


def _fallback_complete_task(text: str, context: dict, timeline: list[dict]) -> StructuredActionProposal | None:
    lower = text.strip().lower()
    if not _likely_complete_request(lower):
        return None
    match = _resolve_timeline_match(lower, timeline)
    if match is None:
        return None
    title = str(match.get("title", "task")).strip() or "task"
    scheduled_start = datetime.fromisoformat(str(match["scheduled_start"]).replace("Z", "+00:00")).astimezone(UTC)
    scheduled_end = datetime.fromisoformat(str(match["scheduled_end"]).replace("Z", "+00:00")).astimezone(UTC)
    return StructuredActionProposal(
        action_type="complete_task",
        entity_type=str(match.get("category", "task")),
        category=str(match.get("category", "task")),
        title=title,
        instructions=f"Mark {title.lower()} as completed.",
        patient_id=str(context["patient_id"]),
        tenant_id=str(context["tenant_id"]),
        actor_id=str(context["participant_id"]),
        start_at=scheduled_start,
        end_at=scheduled_end,
        criticality=str(match.get("criticality", "medium")),
        flexibility=str(match.get("flexibility", "flexible")),
        confirmation_text=_confirm_text(
            title=title,
            description=f"mark {title.lower()} as completed",
        ),
        target_instance_id=str(match.get("win_instance_id", "")),
    )


def _fallback_update_task(text: str, context: dict, timeline: list[dict]) -> StructuredActionProposal | None:
    lower = text.strip().lower()
    if not _likely_update_request(lower):
        return None
    match = _resolve_timeline_match(lower, timeline)
    if match is None:
        return None
    scheduled_start = datetime.fromisoformat(str(match["scheduled_start"]).replace("Z", "+00:00")).astimezone(UTC)
    scheduled_end = datetime.fromisoformat(str(match["scheduled_end"]).replace("Z", "+00:00")).astimezone(UTC)
    duration = max(int((scheduled_end - scheduled_start).total_seconds() // 60), 30)
    tz = ZoneInfo(str(context["patient_timezone"]))
    base_local = scheduled_start.astimezone(tz)
    now_local = datetime.now(tz)
    target_date = base_local.date()
    if "tomorrow" in lower:
        target_date = now_local.date() + timedelta(days=1)
    elif target_date < now_local.date():
        target_date = now_local.date()
    start_hour, end_hour = base_local.hour, base_local.hour + max(duration // 60, 1)
    if "morning" in lower:
        start_hour, end_hour = 9, 10
    elif "afternoon" in lower:
        start_hour, end_hour = 14, 15
    elif "evening" in lower or "night" in lower:
        start_hour, end_hour = 18, 19
    target_start_local = datetime.combine(target_date, datetime.min.time(), tzinfo=tz).replace(hour=start_hour)
    if target_start_local.astimezone(UTC) <= datetime.now(UTC):
        return None
    target_end_local = target_start_local + timedelta(minutes=duration)
    delay_minutes = int((target_start_local.astimezone(UTC) - scheduled_start).total_seconds() // 60)
    if delay_minutes <= 0:
        return None
    title = str(match.get("title", "task")).strip() or "task"
    return StructuredActionProposal(
        action_type="update_task",
        entity_type=str(match.get("category", "task")),
        category=str(match.get("category", "task")),
        title=title,
        instructions=f"Move {title.lower()} to the requested time window.",
        patient_id=str(context["patient_id"]),
        tenant_id=str(context["tenant_id"]),
        actor_id=str(context["participant_id"]),
        start_at=target_start_local.astimezone(UTC),
        end_at=target_end_local.astimezone(UTC),
        criticality=str(match.get("criticality", "medium")),
        flexibility=str(match.get("flexibility", "flexible")),
        confirmation_text=_confirm_text(
            title=title,
            description=(
                f"move {title.lower()} to "
                f"{target_start_local.strftime('%-I:%M %p')} on {target_start_local.strftime('%d %b')}"
            ),
        ),
        target_instance_id=str(match.get("win_instance_id", "")),
        delay_minutes=delay_minutes,
    )


def propose_structured_action(text: str, context: dict, timeline: list[dict] | None = None) -> StructuredActionProposal | None:
    timeline_rows = timeline or []
    for resolver in (
        _fallback_complete_task,
        _fallback_update_task,
    ):
        proposal = resolver(text, context, timeline_rows)
        if proposal is not None:
            return proposal
    for resolver in (
        _fallback_walk_task,
        _fallback_diagnostic_task,
        _fallback_appointment_task,
        _fallback_medication_reminder_task,
    ):
        proposal = resolver(text, context)
        if proposal is not None:
            return proposal
    return _llm_task_proposal(text, context, timeline_rows)


def is_confirmation(text: str) -> bool:
    return text.strip().lower() in {"yes", "y", "confirm", "yes confirm", "ok", "okay"}


def is_cancellation(text: str) -> bool:
    return text.strip().lower() in {"cancel", "no", "stop", "never mind", "nevermind"}
