from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import re
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request, Response

from careos.app_context import context as app_context
from careos.conversation.openclaw_engine import OpenClawConversationEngine
from careos.domain.enums.core import PersonaType, Role
from careos.domain.models.api import CommandResult, LinkedPatientSummary, ParticipantContext, ParticipantIdentity
from careos.gateway.action_proposals import (
    is_cancellation,
    is_confirmation,
)
from careos.gateway.action_planner import CompiledActionPlan, deserialize_compiled_plan, plan_action_request, serialize_compiled_plan
from careos.gateway.careos_adapter import CareOSAdapter, DashboardLinkError
from careos.gateway.careos_adapter import TaskEditError
from careos.gateway.intent_parser import IntentParseResult, parse_intent
from careos.integrations.twilio.twiml import message_response
from careos.logging import get_logger
from careos.settings import settings

router = APIRouter()
adapter = CareOSAdapter()
logger = get_logger("gateway_twilio_webhook")


@dataclass(frozen=True)
class PendingGatewayAction:
    plan: CompiledActionPlan
    expires_at: datetime


_PENDING_ACTIONS: dict[str, PendingGatewayAction] = {}
openclaw_delegate = OpenClawConversationEngine(
    base_url=(settings.gateway_openclaw_base_url or settings.openclaw_base_url or "").strip(),
    timeout_seconds=settings.openclaw_timeout_seconds,
    fallback_path=(
        settings.gateway_openclaw_fallback_path
        or settings.openclaw_fallback_path
        or "/v1/careos/fallback"
    ),
    responses_path=(
        settings.gateway_openclaw_responses_path
        or settings.openclaw_responses_path
        or "/v1/responses"
    ),
    gateway_token=(settings.gateway_openclaw_token or settings.openclaw_gateway_token or "").strip(),
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


def _patients_prompt(patients: list[LinkedPatientSummary], active_patient_id: str | None = None) -> str:
    lines = ["Multiple patients are linked to this number."]
    for index, patient in enumerate(patients, start=1):
        marker = " *" if active_patient_id and patient.patient_id == active_patient_id else ""
        lines.append(f"{index}. {patient.display_name} ({patient.timezone}){marker}")
    lines.append("Reply: use <number>")
    return "\n".join(lines)


def _single_patient_prompt(patient: LinkedPatientSummary) -> str:
    return f"Active patient: {patient.display_name} ({patient.timezone})."


def _is_legacy_router_command(text: str) -> bool:
    normalized = text.strip().lower()
    if normalized in {"help", "?", "next", "whoami", "profile", "schedule", "today", "status"}:
        return True
    return normalized.startswith("done ") or normalized.startswith("skip ") or normalized.startswith("delay ")


def _normalize_setup_intent(text: str) -> str | None:
    normalized = " ".join(text.strip().lower().split())
    if not normalized:
        return None
    if normalized in {"add a medication", "add medication", "add a medicine", "add medicine"}:
        return "add medications"
    if normalized in {"add an appointment", "add appointment"}:
        return "add appointments"
    if normalized in {"add a routine", "add routine"}:
        return "add routines"
    return None


def _parse_caregiver_preset_command(text: str) -> tuple[str, str] | None:
    normalized = " ".join(text.strip().lower().split())
    match = re.fullmatch(r"set caregiver (\+?\d{7,15}) as (observer|primary|primary caregiver|primary_caregiver)", normalized)
    if match is None:
        return None
    phone_number = match.group(1)
    if not phone_number.startswith("+"):
        phone_number = f"+{phone_number}"
    preset = "observer" if match.group(2) == "observer" else "primary_caregiver"
    return phone_number, preset


def _list_caregivers_reply(patient_id: str) -> str:
    links = app_context.store.list_caregiver_links_for_patient(patient_id)
    if not links:
        return "No caregivers are linked to this patient."
    lines = ["Caregivers:"]
    for index, link in enumerate(links, start=1):
        name = str(link.get("display_name", link.get("caregiver_participant_id", "")))
        phone_number = str(link.get("phone_number", ""))
        preset = str(link.get("preset", "primary_caregiver")).replace("_", " ")
        lines.append(f"{index}. {name} ({phone_number}) - {preset}")
    lines.append("Reply: set caregiver <phone> as observer|primary")
    return "\n".join(lines)


def _normalize_phone(value: str) -> str:
    normalized = value.strip().lower()
    if normalized.startswith("whatsapp:"):
        normalized = normalized[len("whatsapp:") :]
    return "".join(ch for ch in normalized if ch.isdigit() or ch == "+")


def _update_caregiver_preset_reply(*, actor_id: str, patient_id: str, phone_number: str, preset: str) -> str:
    actor_link = app_context.store.get_caregiver_link(actor_id, patient_id)
    if actor_link is None or not bool(actor_link.get("can_edit_plan", False)):
        return "Only a primary caregiver can change caregiver presets."
    normalized_phone = _normalize_phone(phone_number)
    target_link = next(
        (
            link
            for link in app_context.store.list_caregiver_links_for_patient(patient_id)
            if _normalize_phone(str(link.get("phone_number", ""))) == normalized_phone
        ),
        None,
    )
    if target_link is None:
        return f"I could not find a caregiver with phone {phone_number}."
    caregiver_participant_id = str(target_link.get("caregiver_participant_id", ""))
    updated = app_context.store.update_caregiver_link_preset(caregiver_participant_id, patient_id, preset)
    if updated is None:
        return "I could not update that caregiver preset right now."
    name = str(target_link.get("display_name", caregiver_participant_id))
    label = "observer" if preset == "observer" else "primary caregiver"
    return (
        f"Updated {name} to {label}. "
        f"Authorization version is now {int(updated.get('authorization_version', 1) or 1)}."
    )


def _parse_use_target(raw_body: str) -> str | None:
    parts = raw_body.strip().split(maxsplit=1)
    if len(parts) != 2:
        return None
    if parts[0].lower() != "use":
        return None
    return parts[1].strip()


def _resolve_use_target(target: str, linked_patients: list[LinkedPatientSummary]) -> LinkedPatientSummary | None:
    if not target:
        return None
    if target.isdigit():
        index = int(target)
        if index < 1 or index > len(linked_patients):
            return None
        return linked_patients[index - 1]
    for patient in linked_patients:
        if patient.patient_id == target:
            return patient
    return None


def _resolve_context_for_message(
    body: str,
    identity: ParticipantIdentity,
    linked_patients: list[LinkedPatientSummary],
) -> tuple[str, str | None]:
    normalized = body.strip().lower()
    active_patient_id = app_context.identity_service.get_active_patient_context(identity.participant_id)

    if len(linked_patients) == 0:
        return ("We could not match this number to a CareOS profile. Ask your caregiver to complete onboarding.", None)

    use_target = _parse_use_target(body)
    if use_target is not None:
        selected = _resolve_use_target(use_target, linked_patients)
        if selected is None:
            if len(linked_patients) > 1:
                return ("Invalid selection.\n" + _patients_prompt(linked_patients, active_patient_id), None)
            return ("Invalid selection.", None)
        try:
            app_context.identity_service.set_active_patient_context(
                identity.participant_id,
                selected.patient_id,
                "whatsapp_use_command",
            )
        except ValueError:
            return ("Could not switch patient context safely. Please try again.", None)
        return (f"Switched to {selected.display_name} ({selected.timezone}).", selected.patient_id)

    if len(linked_patients) == 1:
        only = linked_patients[0]
        if active_patient_id != only.patient_id:
            app_context.identity_service.set_active_patient_context(identity.participant_id, only.patient_id, "auto_single_link")
        return ("", only.patient_id)

    if normalized in {"patients", "switch"}:
        return (_patients_prompt(linked_patients, active_patient_id), None)

    if normalized in {"whoami", "profile"} and not active_patient_id:
        text = (
            f"You are {identity.participant_role.value}. Active patient: none selected.\n"
            + _patients_prompt(linked_patients, None)
        )
        return (text, None)

    if active_patient_id is None:
        return (_patients_prompt(linked_patients, None), None)

    if active_patient_id not in {item.patient_id for item in linked_patients}:
        app_context.identity_service.clear_active_patient_context(identity.participant_id)
        return (_patients_prompt(linked_patients, None), None)

    return ("", active_patient_id)


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


def _is_short_completion_reply(text: str) -> bool:
    normalized = " ".join(text.strip().lower().split())
    return normalized in {
        "taken",
        "took it",
        "i took it",
        "i took them",
        "gave it",
        "given",
        "administered",
    }


def _implicit_completion_reply(text: str, context: dict, today: dict) -> str | None:
    if not _is_short_completion_reply(text):
        return None
    reminder_context = adapter.get_latest_scheduled_reminder_context(
        str(context["participant_id"]),
        str(context["patient_id"]),
    )
    if reminder_context is not None and str(reminder_context.get("win_instance_id", "")).strip():
        win_instance_id = str(reminder_context["win_instance_id"])
        title = str(reminder_context.get("title", "task")).strip() or "task"
        adapter.complete_win(win_instance_id, str(context["participant_id"]))
        return f"Marked {title.lower()} as completed."
    timeline = list(today.get("timeline", []))
    actionable = [
        item
        for item in timeline
        if str(item.get("current_state", "")).lower() in {"due", "delayed"}
    ]
    if len(actionable) == 1:
        item = actionable[0]
        adapter.complete_win(str(item["win_instance_id"]), str(context["participant_id"]))
        return f"Marked {str(item.get('title', 'task')).lower()} as completed."
    if len(actionable) > 1:
        lines = ["I found multiple due items. Reply with one of these instead:"]
        for index, item in enumerate(actionable[:5], start=1):
            lines.append(f"- done {index} for {item['title']}")
        lines.append("You can also ask for your schedule first.")
        return "\n".join(lines)
    return "I could not find a currently due item to mark completed. Send 'schedule' or 'done <number>'."


def _pending_key(context: dict) -> str:
    return f"{context['tenant_id']}:{context['participant_id']}:{context['patient_id']}"


def _store_pending_action(context: dict, plan: CompiledActionPlan) -> None:
    ttl_minutes = max(int(settings.gateway_pending_action_ttl_minutes), 1)
    pending_key = _pending_key(context)
    pending = PendingGatewayAction(
        plan=plan,
        expires_at=datetime.now(UTC) + timedelta(minutes=ttl_minutes),
    )
    _PENDING_ACTIONS[pending_key] = pending
    adapter.save_pending_gateway_action(
        pending_key=pending_key,
        plan=serialize_compiled_plan(plan),
        expires_at_iso=pending.expires_at.isoformat(),
    )


def _pop_pending_action(context: dict) -> PendingGatewayAction | None:
    key = _pending_key(context)
    pending = _PENDING_ACTIONS.get(key)
    if pending is None:
        persisted = adapter.get_pending_gateway_action(key)
        if persisted is None:
            return None
        pending = PendingGatewayAction(
            plan=deserialize_compiled_plan(dict(persisted["plan"])),
            expires_at=datetime.fromisoformat(str(persisted["expires_at"])),
        )
    if pending.expires_at <= datetime.now(UTC):
        _PENDING_ACTIONS.pop(key, None)
        adapter.clear_pending_gateway_action(key)
        return None
    _PENDING_ACTIONS.pop(key, None)
    adapter.clear_pending_gateway_action(key)
    return pending


def _get_pending_action(context: dict) -> PendingGatewayAction | None:
    key = _pending_key(context)
    pending = _PENDING_ACTIONS.get(key)
    if pending is None:
        persisted = adapter.get_pending_gateway_action(key)
        if persisted is None:
            return None
        pending = PendingGatewayAction(
            plan=deserialize_compiled_plan(dict(persisted["plan"])),
            expires_at=datetime.fromisoformat(str(persisted["expires_at"])),
        )
        _PENDING_ACTIONS[key] = pending
    if pending.expires_at <= datetime.now(UTC):
        _PENDING_ACTIONS.pop(key, None)
        adapter.clear_pending_gateway_action(key)
        return None
    return pending


def _execute_intent(intent: IntentParseResult, context: dict) -> str:
    patient_id = str(context["patient_id"])
    participant_id = str(context["participant_id"])
    timezone_name = str(context["patient_timezone"])
    now_local = datetime.now(ZoneInfo(timezone_name))

    if intent.intent == "caregiver_dashboard":
        try:
            result = adapter.generate_dashboard_view(
                tenant_id=str(context["tenant_id"]),
                patient_id=patient_id,
                actor_id=participant_id,
                role=str(context["participant_role"]),
                view="caregiver_dashboard",
            )
        except DashboardLinkError as exc:
            logger.warning(
                "dashboard_link_unavailable",
                reason=str(exc),
                tenant_id=str(context["tenant_id"]),
                patient_id=patient_id,
                participant_id=participant_id,
            )
            return (
                "I recognized a dashboard request, but the secure caregiver dashboard is temporarily unavailable. "
                "Please try again in a few minutes."
            )
        url = str(result.get("url", "")).strip()
        expires = int(result.get("expires_in_seconds", 1800) or 1800)
        if not url:
            return "I recognized a dashboard request, but could not generate the secure dashboard link right now."
        expires_minutes = max(int(expires / 60), 1)
        return f"Open caregiver dashboard: {url} (expires in {expires_minutes} minutes)"
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


def _execute_pending_action(pending: PendingGatewayAction) -> str:
    plan = pending.plan
    proposal = plan.bound.parsed.proposal
    payload = plan.execution_payload
    if plan.execution_strategy == "create_task":
        adapter.create_task(
            patient_id=str(payload["patient_id"]),
            actor_id=str(payload["actor_id"]),
            category=str(payload["category"]),
            title=str(payload["title"]),
            instructions=str(payload["instructions"]),
            start_at_iso=str(payload["start_at_iso"]),
            end_at_iso=str(payload["end_at_iso"]),
            criticality=str(payload["criticality"]),
            flexibility=str(payload["flexibility"]),
        )
        return f"Created {proposal.title.lower()}. You can ask for your dashboard to verify it."
    if plan.execution_strategy in {"reschedule_one_off_task", "override_recurring_task"} and proposal.target_instance_id:
        try:
            if plan.execution_strategy == "reschedule_one_off_task":
                adapter.reschedule_task(
                    win_instance_id=str(payload["win_instance_id"]),
                    actor_id=str(payload["actor_id"]),
                    start_at_iso=str(payload["start_at_iso"]),
                    end_at_iso=str(payload["end_at_iso"]),
                )
            else:
                adapter.override_recurring_task(
                    win_instance_id=str(payload["win_instance_id"]),
                    actor_id=str(payload["actor_id"]),
                    start_at_iso=str(payload["start_at_iso"]),
                    end_at_iso=str(payload["end_at_iso"]),
                )
        except TaskEditError:
            return "I could not safely move that task."
        return f"Moved {proposal.title.lower()}. You can ask for your schedule to verify it."
    if plan.execution_strategy == "complete_task" and proposal.target_instance_id:
        adapter.complete_win(str(payload["win_instance_id"]), str(payload["actor_id"]))
        return f"Marked {proposal.title.lower()} as completed."
    return "I could not execute that pending action."


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

    identity = app_context.identity_service.resolve_participant_by_phone(sender)
    linked_patients: list[LinkedPatientSummary] = []
    if identity is not None:
        linked_patients = app_context.identity_service.list_linked_patients(identity.participant_id)

    onboarding_reply = app_context.onboarding.maybe_handle_message(
        sender_phone=sender,
        body=text,
        identity=identity,
        linked_patient_count=len(linked_patients),
    )
    if onboarding_reply is not None:
        return Response(content=message_response(onboarding_reply), media_type="text/xml")

    if identity is None:
        return Response(
            content=message_response("Could not resolve sender identity. Reply 'hi' to start onboarding."),
            media_type="text/xml",
        )

    preflight_text, selected_patient_id = _resolve_context_for_message(text, identity, linked_patients)
    if selected_patient_id is None:
        return Response(content=message_response(preflight_text), media_type="text/xml")
    if preflight_text:
        return Response(content=message_response(preflight_text), media_type="text/xml")

    setup_intent = _normalize_setup_intent(text)
    if setup_intent is not None:
        if hasattr(app_context.onboarding, "_activate_setup_session"):
            app_context.onboarding._activate_setup_session(  # type: ignore[attr-defined]
                phone_number=sender,
                participant_id=identity.participant_id,
                patient_id=selected_patient_id,
                source="gateway_setup_shortcut",
            )
        setup_reply = app_context.onboarding.maybe_handle_message(
            sender_phone=sender,
            body=setup_intent,
            identity=identity,
            linked_patient_count=len(linked_patients),
        )
        if setup_reply is not None:
            return Response(content=message_response(setup_reply), media_type="text/xml")

    context = adapter.resolve_context(sender)
    if context is None:
        return Response(
            content=message_response("Could not resolve active patient context."),
            media_type="text/xml",
        )

    pending = _get_pending_action(context)
    if pending is not None and is_confirmation(text):
        reply = _execute_pending_action(_pop_pending_action(context) or pending)
        return Response(content=message_response(reply), media_type="text/xml")
    if pending is not None and is_cancellation(text):
        _pop_pending_action(context)
        return Response(content=message_response("Okay, I did not create that change."), media_type="text/xml")

    normalized = text.strip().lower()
    today = adapter.get_today(str(context["patient_id"]))
    implicit_completion = _implicit_completion_reply(text, context, today)
    if implicit_completion is not None:
        return Response(content=message_response(implicit_completion), media_type="text/xml")
    preset_command = _parse_caregiver_preset_command(text)
    if normalized in {"patients", "switch"}:
        if linked_patients:
            if len(linked_patients) == 1:
                return Response(
                    content=message_response(_single_patient_prompt(linked_patients[0])),
                    media_type="text/xml",
                )
            return Response(
                content=message_response(_patients_prompt(linked_patients, str(context["patient_id"]))),
                media_type="text/xml",
            )
        return Response(
            content=message_response("No linked patients were found for this number."),
            media_type="text/xml",
        )
    if normalized in {"caregivers", "list caregivers"}:
        return Response(content=message_response(_list_caregivers_reply(str(context["patient_id"]))), media_type="text/xml")
    if preset_command is not None:
        phone_number, preset = preset_command
        reply = _update_caregiver_preset_reply(
            actor_id=str(context["participant_id"]),
            patient_id=str(context["patient_id"]),
            phone_number=phone_number,
            preset=preset,
        )
        return Response(content=message_response(reply), media_type="text/xml")

    if _is_legacy_router_command(text):
        result = app_context.router.handle(text, _to_participant_context(context))
        return Response(content=message_response(result.text), media_type="text/xml")

    compiled_plan = plan_action_request(text, context, today.get("timeline", []), adapter)
    if compiled_plan is not None and compiled_plan.execution_strategy == "clarify_target":
        return Response(content=message_response(compiled_plan.confirmation_text), media_type="text/xml")
    if compiled_plan is not None:
        _store_pending_action(context, compiled_plan)
        return Response(content=message_response(compiled_plan.confirmation_text), media_type="text/xml")

    status = adapter.get_status(str(context["patient_id"]))
    parsed_intent = parse_intent(text, context=context, today=today, status=status)
    if parsed_intent.intent in {
        "caregiver_dashboard",
        "schedule_today",
        "schedule_tomorrow",
        "status",
        "med_count_today",
        "critical_missed_today",
    }:
        reply = _execute_intent(parsed_intent, context)
        return Response(content=message_response(reply), media_type="text/xml")

    mode = str(settings.gateway_conversation_mode or "openclaw_first").strip().lower()
    reply = ""
    if mode == "openclaw_first":
        openclaw_result: CommandResult = openclaw_delegate.handle(text, _to_participant_context(context))
        if openclaw_result.action != "unavailable" and openclaw_result.text.strip():
            reply = openclaw_result.text
        else:
            reply = _execute_intent(parsed_intent, context)
    else:
        reply = _execute_intent(parsed_intent, context)
    return Response(content=message_response(reply), media_type="text/xml")
