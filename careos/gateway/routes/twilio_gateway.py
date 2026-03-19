from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import re
from hashlib import sha1
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


@dataclass(frozen=True)
class PendingMedicationEdit:
    item_no: int
    win_instance_id: str
    title: str
    recurrence_type: str
    recurrence_interval: int = 1
    recurrence_days_of_week: list[int] = field(default_factory=list)
    pending_action: str = ""
    requested_days_of_week: list[int] = field(default_factory=list)


_PENDING_ACTIONS: dict[str, PendingGatewayAction] = {}
_PENDING_MEDICATION_EDITS: dict[str, PendingMedicationEdit] = {}
_WEEKDAY_ALIASES = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}
_WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
openclaw_delegate = OpenClawConversationEngine(
    base_url=(settings.gateway_openclaw_base_url or settings.openclaw_base_url or "").strip(),
    timeout_seconds=settings.openclaw_timeout_seconds,
    win_service=app_context.win_service,
    patient_context_service=app_context.patient_context,
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


def _normalize_fact_key(raw_key: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", raw_key.strip().lower()).strip("_")
    return cleaned[:64]


def _derive_fact_key(summary: str) -> str:
    tokens = [token for token in re.split(r"[^a-z0-9]+", summary.lower()) if token]
    stop_words = {"that", "i", "me", "my", "had", "have", "was", "were", "am", "is", "the", "a", "an", "on", "in"}
    informative = [token for token in tokens if token not in stop_words]
    base = "_".join(informative[:4]).strip("_")
    if not base:
        digest = sha1(summary.encode("utf-8")).hexdigest()[:10]
        return f"fact_{digest}"
    return _normalize_fact_key(base)


def _extract_detected_dates(summary: str) -> list[str]:
    return re.findall(r"\b\d{4}-\d{2}-\d{2}\b", summary)


def _parse_remember_command(text: str) -> tuple[str, str, bool] | None:
    match = re.fullmatch(r"\s*remember(?:\s+that)?\s+(.+?)\s*", text, flags=re.IGNORECASE)
    if match is None:
        return None
    body = match.group(1).strip()
    if not body:
        return None
    if ":" in body:
        raw_key, summary = body.split(":", 1)
        fact_key = _normalize_fact_key(raw_key)
        summary = summary.strip()
        if fact_key and summary:
            return fact_key, summary, True
    summary = body.strip()
    if not summary:
        return None
    return _derive_fact_key(summary), summary, False


def _remember_source_for_role(role: str) -> str:
    normalized = str(role).strip().lower()
    if normalized == "patient":
        return "patient_reported"
    if normalized == "clinician":
        return "clinician_reported"
    return "caregiver_reported"


def _handle_remember_command(text: str, context: dict) -> str | None:
    parsed = _parse_remember_command(text)
    if parsed is None:
        return None
    fact_key, summary, explicit_key = parsed
    adapter.upsert_patient_clinical_fact(
        tenant_id=str(context["tenant_id"]),
        patient_id=str(context["patient_id"]),
        actor_participant_id=str(context["participant_id"]),
        fact_key=fact_key,
        fact_value={
            "statement": summary,
            "detected_dates": _extract_detected_dates(summary),
        },
        summary=summary,
        source=_remember_source_for_role(str(context["participant_role"])),
        effective_at_iso=None,
    )
    if explicit_key:
        return f"Remembered under {fact_key}: {summary}"
    return f"Remembered under {fact_key}: {summary}\nTo update it later, send: remember {fact_key}: <updated fact>"


def _handle_list_clinical_facts(context: dict) -> str | None:
    response = adapter.list_active_patient_clinical_facts(
        tenant_id=str(context["tenant_id"]),
        patient_id=str(context["patient_id"]),
    )
    facts = list(response.get("facts", []))
    if not facts:
        return "No durable clinical facts are stored yet. Use 'remember ...' to add one."
    lines = ["Remembered clinical facts:"]
    for index, fact in enumerate(facts, start=1):
        key = str(fact.get("fact_key", "")).strip()
        summary = str(fact.get("summary", "")).strip()
        lines.append(f"{index}. {key}: {summary}")
    return "\n".join(lines)


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


def _is_bulk_medication_completion_reply(text: str) -> bool:
    normalized = " ".join(text.strip().lower().split())
    return normalized in {
        "i took them",
        "taken all",
        "taken all meds",
        "took all",
        "took all meds",
        "done all meds",
        "done all medications",
    }


def _due_actionable_items(today: dict) -> list[dict]:
    timeline = list(today.get("timeline", []))
    return [
        item
        for item in timeline
        if str(item.get("current_state", "")).lower() in {"due", "delayed"}
    ]


def _due_medication_items(today: dict) -> list[dict]:
    return [
        item
        for item in _due_actionable_items(today)
        if str(item.get("category", "")).lower() == "medication"
    ]


def _multiple_due_items_reply(actionable: list[dict], *, medications_only: bool = False) -> str:
    lines = [
        "I found multiple due medications from recent reminders. Reply with one of these instead:"
        if medications_only
        else "I found multiple due items. Reply with one of these instead:"
    ]
    for index, item in enumerate(actionable[:5], start=1):
        lines.append(f"- done {index} for {item['title']}")
    if medications_only:
        lines.append("If you took all of the due medications, reply 'done all meds'.")
    else:
        lines.append("You can also ask for your schedule first.")
    return "\n".join(lines)


def _implicit_completion_reply(text: str, context: dict, today: dict) -> str | None:
    if not _is_short_completion_reply(text) and not _is_bulk_medication_completion_reply(text):
        return None
    bulk_medication_reply = _is_bulk_medication_completion_reply(text)
    reminder_context = adapter.get_latest_scheduled_reminder_context(
        str(context["participant_id"]),
        str(context["patient_id"]),
    )
    actionable = _due_actionable_items(today)
    due_medications = _due_medication_items(today)
    if bulk_medication_reply:
        if len(due_medications) == 0:
            return "I could not find any currently due medications to mark completed. Send 'schedule' first if needed."
        for item in due_medications:
            adapter.complete_win(str(item["win_instance_id"]), str(context["participant_id"]))
        if len(due_medications) == 1:
            return f"Marked {str(due_medications[0].get('title', 'medication')).lower()} as completed."
        return f"Marked {len(due_medications)} due medications as completed."
    if reminder_context is not None and str(reminder_context.get("win_instance_id", "")).strip():
        win_instance_id = str(reminder_context["win_instance_id"])
        title = str(reminder_context.get("title", "task")).strip() or "task"
        matching_due_medications = [
            item for item in due_medications if str(item.get("win_instance_id")) == win_instance_id
        ]
        if matching_due_medications and len(due_medications) > 1:
            return _multiple_due_items_reply(due_medications, medications_only=True)
        adapter.complete_win(win_instance_id, str(context["participant_id"]))
        return f"Marked {title.lower()} as completed."
    if len(actionable) == 1:
        item = actionable[0]
        adapter.complete_win(str(item["win_instance_id"]), str(context["participant_id"]))
        return f"Marked {str(item.get('title', 'task')).lower()} as completed."
    if len(actionable) > 1:
        return _multiple_due_items_reply(actionable)
    return "I could not find a currently due item to mark completed. Send 'schedule' or 'done <number>'."


def _pending_key(context: dict) -> str:
    return f"{context['tenant_id']}:{context['participant_id']}:{context['patient_id']}"


def _store_pending_medication_edit(context: dict, pending: PendingMedicationEdit) -> None:
    _PENDING_MEDICATION_EDITS[_pending_key(context)] = pending


def _get_pending_medication_edit(context: dict) -> PendingMedicationEdit | None:
    return _PENDING_MEDICATION_EDITS.get(_pending_key(context))


def _clear_pending_medication_edit(context: dict) -> None:
    _PENDING_MEDICATION_EDITS.pop(_pending_key(context), None)


def _format_weekdays(days: list[int]) -> str:
    if not days:
        return "every day"
    return ", ".join(_WEEKDAY_LABELS[day] for day in sorted(dict.fromkeys(days)))


def _parse_weekdays(text: str) -> list[int] | None:
    normalized = re.sub(r"[^a-z,\s]", " ", text.lower())
    if "weekdays" in normalized:
        return [0, 1, 2, 3, 4]
    tokens = [token for token in re.split(r"[\s,]+", normalized) if token]
    days: list[int] = []
    for token in tokens:
        if token in {"days", "day", "only", "on", "reply", "set", "to"}:
            continue
        mapped = _WEEKDAY_ALIASES.get(token)
        if mapped is None:
            continue
        if mapped not in days:
            days.append(mapped)
    return days or None


def _medication_edit_options_reply(title: str) -> str:
    return (
        f"Editing {title}. Reply with DELETE, ONE OFF, DAILY, or DAYS mon wed fri. "
        "Reply CANCEL to stop."
    )


def _select_medication_for_edit(item_no: int, today: dict) -> tuple[dict | None, str | None]:
    timeline = list(today.get("timeline", []))
    if item_no <= 0 or item_no > len(timeline):
        return None, "Item number is out of range. Send 'schedule' first."
    item = dict(timeline[item_no - 1])
    if str(item.get("category", "")).lower() != "medication":
        return None, "That item is not a medication. Reply with a medication item number from 'schedule'."
    return item, None


def _start_medication_edit(text: str, context: dict, today: dict) -> str | None:
    normalized = " ".join(text.strip().lower().split())
    match = re.fullmatch(r"(?:change|edit|modify)\s+(\d+)(?:\s+(.*))?", normalized)
    if match is None:
        direct_delete = re.fullmatch(r"(?:delete|remove)\s+(\d+)", normalized)
        if direct_delete is None:
            return None
        item_no = int(direct_delete.group(1))
        immediate_action = "delete"
    else:
        item_no = int(match.group(1))
        immediate_action = str(match.group(2) or "").strip()
    item, error = _select_medication_for_edit(item_no, today)
    if error is not None or item is None:
        return error
    binding = adapter.get_win_binding(str(item["win_instance_id"]))
    pending = PendingMedicationEdit(
        item_no=item_no,
        win_instance_id=str(item["win_instance_id"]),
        title=str(item.get("title", "medication")).strip() or "medication",
        recurrence_type=str(binding.get("recurrence_type", "one_off")),
        recurrence_interval=int(binding.get("recurrence_interval", 1) or 1),
        recurrence_days_of_week=list(binding.get("recurrence_days_of_week", []) or []),
    )
    _store_pending_medication_edit(context, pending)
    if immediate_action == "delete":
        _store_pending_medication_edit(
            context,
            PendingMedicationEdit(**{**pending.__dict__, "pending_action": "delete"}),
        )
        return f"Reply YES to delete {pending.title}. Reply CANCEL to stop."
    if immediate_action:
        return _handle_pending_medication_edit(context, immediate_action)
    return _medication_edit_options_reply(pending.title)


def _handle_pending_medication_edit(context: dict, text: str) -> str | None:
    pending = _get_pending_medication_edit(context)
    if pending is None:
        return None
    normalized = " ".join(text.strip().lower().split())
    if normalized in {"cancel", "stop", "never mind", "nevermind"}:
        _clear_pending_medication_edit(context)
        return "Okay, I cancelled the medication change."
    if not pending.pending_action:
        if normalized in {"delete", "remove"}:
            _store_pending_medication_edit(
                context,
                PendingMedicationEdit(**{**pending.__dict__, "pending_action": "delete"}),
            )
            return f"Reply YES to delete {pending.title}. Reply CANCEL to stop."
        if normalized in {"one off", "one-off", "make one off", "make one-off", "remove recurrence", "stop recurrence"}:
            if pending.recurrence_type == "one_off":
                _clear_pending_medication_edit(context)
                return f"{pending.title} is already one-off."
            _store_pending_medication_edit(
                context,
                PendingMedicationEdit(**{**pending.__dict__, "pending_action": "one_off"}),
            )
            return f"Reply YES to make {pending.title} one-off and stop future recurrence."
        if normalized in {"daily", "every day", "everyday"}:
            _store_pending_medication_edit(
                context,
                PendingMedicationEdit(**{**pending.__dict__, "pending_action": "daily"}),
            )
            return f"Reply YES to make {pending.title} recur daily."
        requested_days = _parse_weekdays(normalized)
        if requested_days is not None:
            _store_pending_medication_edit(
                context,
                PendingMedicationEdit(
                    **{
                        **pending.__dict__,
                        "pending_action": "days",
                        "requested_days_of_week": requested_days,
                    }
                ),
            )
            return f"Reply YES to make {pending.title} recur only on {_format_weekdays(requested_days)}."
        return _medication_edit_options_reply(pending.title)
    if not is_confirmation(text):
        return "Reply YES to confirm or CANCEL to stop."
    actor_id = str(context["participant_id"])
    if pending.pending_action == "delete":
        adapter.remove_task(
            win_instance_id=pending.win_instance_id,
            actor_id=actor_id,
            supersede_active_due=True,
        )
        _clear_pending_medication_edit(context)
        return f"Deleted {pending.title}."
    if pending.pending_action == "one_off":
        adapter.update_task_recurrence(
            win_instance_id=pending.win_instance_id,
            actor_id=actor_id,
            recurrence_type="one_off",
            recurrence_interval=1,
            recurrence_days_of_week=[],
            recurrence_until=None,
        )
        _clear_pending_medication_edit(context)
        return f"Updated {pending.title} to one-off only."
    if pending.pending_action == "daily":
        adapter.update_task_recurrence(
            win_instance_id=pending.win_instance_id,
            actor_id=actor_id,
            recurrence_type="daily",
            recurrence_interval=1,
            recurrence_days_of_week=[],
            recurrence_until=None,
        )
        _clear_pending_medication_edit(context)
        return f"Updated {pending.title} to daily recurrence."
    if pending.pending_action == "days":
        adapter.update_task_recurrence(
            win_instance_id=pending.win_instance_id,
            actor_id=actor_id,
            recurrence_type="weekly",
            recurrence_interval=1,
            recurrence_days_of_week=pending.requested_days_of_week,
            recurrence_until=None,
        )
        _clear_pending_medication_edit(context)
        return f"Updated {pending.title} to recur on {_format_weekdays(pending.requested_days_of_week)}."
    _clear_pending_medication_edit(context)
    return "I could not apply that medication change."


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
    pending_medication_edit_reply = _handle_pending_medication_edit(context, text)
    if pending_medication_edit_reply is not None:
        return Response(content=message_response(pending_medication_edit_reply), media_type="text/xml")
    medication_edit_reply = _start_medication_edit(text, context, today)
    if medication_edit_reply is not None:
        return Response(content=message_response(medication_edit_reply), media_type="text/xml")
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
    if normalized in {"facts", "clinical facts", "remembered facts"}:
        reply = _handle_list_clinical_facts(context)
        return Response(content=message_response(reply or "No clinical facts available."), media_type="text/xml")
    remember_reply = _handle_remember_command(text, context)
    if remember_reply is not None:
        return Response(content=message_response(remember_reply), media_type="text/xml")

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
