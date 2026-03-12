from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request, Response

from careos.conversation.openclaw_engine import OpenClawConversationEngine
from careos.domain.enums.core import PersonaType, Role
from careos.domain.models.api import CommandResult, ParticipantContext
from careos.gateway.careos_adapter import CareOSAdapter
from careos.gateway.intent_parser import IntentParseResult, parse_intent
from careos.integrations.twilio.twiml import message_response
from careos.settings import settings

router = APIRouter()
adapter = CareOSAdapter()
openclaw_delegate = OpenClawConversationEngine(
    base_url=(settings.gateway_openclaw_base_url or settings.openclaw_base_url or "").strip(),
    timeout_seconds=settings.openclaw_timeout_seconds,
    fallback_path=(
        settings.gateway_openclaw_fallback_path
        or settings.openclaw_fallback_path
        or "/v1/careos/fallback"
    ),
)


def _normalize_sender_phone(sender: str) -> str:
    value = str(sender).strip()
    if not value:
        return value
    if value.startswith("whatsapp: "):
        value = "whatsapp:+" + value[len("whatsapp: ") :]
    elif value.startswith("whatsapp:") and "+" not in value:
        suffix = value[len("whatsapp:") :].strip()
        if suffix and suffix[0].isdigit():
            value = f"whatsapp:+{suffix}"
    return value.replace(" ", "")


def _render_schedule(payload: dict, *, prefix: str = "Schedule") -> str:
    timeline = payload.get("timeline", [])
    if not timeline:
        return f"{prefix}: no wins scheduled."
    timezone_name = str(payload.get("timezone", "UTC"))
    tz = ZoneInfo(timezone_name)
    lines = [f"{prefix} ({payload.get('date','')}):"]
    for idx, item in enumerate(timeline, start=1):
        start = datetime.fromisoformat(str(item["scheduled_start"]).replace("Z", "+00:00"))
        local_time = start.astimezone(tz).strftime("%H:%M")
        lines.append(f"{idx}. {local_time} {item['title']} [{item['current_state']}]")
    return "\n".join(lines)


def _execute_intent(intent: IntentParseResult, context: dict) -> str:
    patient_id = str(context["patient_id"])
    participant_id = str(context["participant_id"])
    timezone_name = str(context["patient_timezone"])
    now_local = datetime.now(ZoneInfo(timezone_name))

    if intent.intent == "schedule_today":
        today = adapter.get_today(patient_id)
        return _render_schedule(today, prefix="Schedule")
    if intent.intent == "schedule_tomorrow":
        tomorrow = adapter.get_day(patient_id, now_local.date() + timedelta(days=1))
        return _render_schedule(tomorrow, prefix="Tomorrow schedule")
    if intent.intent == "status":
        status = adapter.get_status(patient_id)
        return (
            f"Status: completed={status.get('completed_count',0)}, due={status.get('due_count',0)}, "
            f"missed={status.get('missed_count',0)}, skipped={status.get('skipped_count',0)}, "
            f"score={status.get('adherence_score',0)}%"
        )
    if intent.intent == "critical_missed_today":
        today = adapter.get_today(patient_id)
        critical_missed = [
            row["title"]
            for row in today.get("timeline", [])
            if str(row.get("criticality", "")).lower() == "high" and str(row.get("current_state", "")) == "missed"
        ]
        if not critical_missed:
            return "No critical wins are missed today."
        return "Missed critical wins today:\n" + "\n".join([f"- {title}" for title in critical_missed])
    if intent.intent == "med_count_today":
        today = adapter.get_today(patient_id)
        meds = [row for row in today.get("timeline", []) if str(row.get("category", "")).lower() == "medication"]
        completed = [row for row in meds if str(row.get("current_state", "")) == "completed"]
        return f"You completed {len(completed)} of {len(meds)} scheduled medications today."
    if intent.intent == "set_critical_only_today":
        end_of_day = now_local.replace(hour=23, minute=59, second=59, microsecond=0)
        adapter.create_personalization_rule(
            tenant_id=str(context["tenant_id"]),
            patient_id=patient_id,
            actor_participant_id=participant_id,
            rule_type="critical_only_today",
            rule_payload={"allow_only_classes": ["A"], "scope": "today"},
            expires_at_iso=end_of_day.isoformat(),
        )
        return "Understood. For today, I will focus on critical reminders."
    if intent.intent in {"done", "skip", "delay"}:
        item_no = int(intent.args.get("item_no", 0) or 0)
        if item_no <= 0:
            return "Please provide item number from today's schedule."
        today = adapter.get_today(patient_id)
        timeline = today.get("timeline", [])
        if item_no > len(timeline):
            return "Item number is out of range. Send 'schedule' first."
        instance_id = str(timeline[item_no - 1]["win_instance_id"])
        if intent.intent == "done":
            adapter.complete_win(instance_id, participant_id)
            return f"Marked {item_no} as completed."
        if intent.intent == "skip":
            adapter.skip_win(instance_id, participant_id)
            return f"Marked {item_no} as skipped."
        minutes = int(intent.args.get("minutes", 0) or 0)
        if minutes <= 0:
            return "Please provide delay minutes, e.g. delay 2 30."
        adapter.delay_win(instance_id, participant_id, minutes)
        return f"Delayed {item_no} by {minutes} minutes."
    return "Please rephrase. I can help with schedule, tomorrow, status, medication counts, done, skip, and delay."


def _to_participant_context(context_row: dict) -> ParticipantContext:
    return ParticipantContext(
        tenant_id=str(context_row["tenant_id"]),
        participant_id=str(context_row["participant_id"]),
        participant_role=Role(str(context_row["participant_role"])),
        patient_id=str(context_row["patient_id"]),
        patient_timezone=str(context_row["patient_timezone"]),
        patient_persona=PersonaType(str(context_row["patient_persona"])),
    )


def _deterministic_reply(text: str, context_row: dict) -> str:
    today = adapter.get_today(str(context_row["patient_id"]))
    status = adapter.get_status(str(context_row["patient_id"]))
    intent = parse_intent(text, context=context_row, today=today, status=status)
    return _execute_intent(intent, context_row)


@router.post("/gateway/twilio/webhook")
async def twilio_gateway_webhook(request: Request) -> Response:
    body_bytes = await request.body()
    decoded = body_bytes.decode("utf-8", errors="ignore")
    parsed = parse_qs(decoded, keep_blank_values=True)
    payload = {k: v[0] if v else "" for k, v in parsed.items()}
    sender = _normalize_sender_phone(payload.get("From", ""))
    text = str(payload.get("Body", "")).strip()
    if not sender:
        return Response(content=message_response("Missing sender."), media_type="text/xml")

    context = adapter.resolve_context(sender)
    if context is None:
        return Response(
            content=message_response("Could not resolve sender identity. Ask caregiver to complete onboarding."),
            media_type="text/xml",
        )

    mode = str(settings.gateway_conversation_mode or "openclaw_first").strip().lower()
    reply = ""
    if mode == "openclaw_first":
        openclaw_result: CommandResult = openclaw_delegate.handle(text, _to_participant_context(context))
        if openclaw_result.action != "unavailable" and openclaw_result.text.strip():
            reply = openclaw_result.text
        else:
            reply = _deterministic_reply(text, context)
    else:
        reply = _deterministic_reply(text, context)
    return Response(content=message_response(reply), media_type="text/xml")
