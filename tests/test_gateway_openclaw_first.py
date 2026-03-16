import asyncio
from urllib.parse import urlencode

from careos.domain.enums.core import Role
from careos.domain.models.api import CommandResult, LinkedPatientSummary, ParticipantContext, ParticipantIdentity
from careos.gateway.careos_adapter import DashboardLinkError, TaskEditError
from careos.gateway.routes import twilio_gateway
from careos.settings import settings


class _AdapterBase:
    def __init__(self) -> None:
        self.created_tasks: list[dict] = []
        self.completed_instances: list[dict] = []
        self.rescheduled_tasks: list[dict] = []
        self.superseded_instances: list[dict] = []
        self.bindings: dict[str, dict] = {}
        self.timeline: list[dict] = []
        self.pending_gateway_actions: dict[str, dict] = {}

    def resolve_context(self, phone_number: str) -> dict | None:
        return {
            "tenant_id": "tenant-1",
            "participant_id": "participant-1",
            "participant_role": "caregiver",
            "patient_id": "patient-1",
            "patient_timezone": "Asia/Kolkata",
            "patient_persona": "caregiver_managed_elder",
        }

    def get_today(self, patient_id: str) -> dict:
        return {"patient_id": patient_id, "date": "2026-03-12", "timezone": "Asia/Kolkata", "timeline": list(self.timeline)}

    def get_day(self, patient_id: str, day_value) -> dict:  # noqa: ANN001
        return {"patient_id": patient_id, "date": str(day_value), "timezone": "Asia/Kolkata", "timeline": list(self.timeline)}

    def get_status(self, patient_id: str) -> dict:
        return {"completed_count": 0, "due_count": 1, "missed_count": 0, "skipped_count": 0, "adherence_score": 0.0}

    def get_latest_scheduled_reminder_context(self, participant_id: str, patient_id: str) -> dict | None:
        return None

    def generate_dashboard_view(
        self,
        *,
        tenant_id: str,
        patient_id: str,
        actor_id: str,
        role: str = "caregiver",
        view: str = "caregiver_dashboard",
    ) -> dict:
        return {"url": "https://careos.theginger.ai/v/test-token", "expires_in_seconds": 1800}

    def create_task(
        self,
        *,
        patient_id: str,
        actor_id: str,
        category: str,
        title: str,
        instructions: str,
        start_at_iso: str,
        end_at_iso: str,
        criticality: str,
        flexibility: str,
    ) -> dict:
        self.created_tasks.append(
            {
                "patient_id": patient_id,
                "actor_id": actor_id,
                "category": category,
                "title": title,
                "instructions": instructions,
                "start_at_iso": start_at_iso,
                "end_at_iso": end_at_iso,
                "criticality": criticality,
                "flexibility": flexibility,
            }
        )
        return {"ok": True}

    def complete_win(self, instance_id: str, actor_id: str) -> dict:
        self.completed_instances.append({"instance_id": instance_id, "actor_id": actor_id})
        return {"ok": True}

    def reschedule_task(self, *, win_instance_id: str, actor_id: str, start_at_iso: str, end_at_iso: str) -> dict:
        self.rescheduled_tasks.append(
            {
                "instance_id": win_instance_id,
                "actor_id": actor_id,
                "start_at_iso": start_at_iso,
                "end_at_iso": end_at_iso,
            }
        )
        return {"ok": True}

    def get_win_binding(self, win_instance_id: str) -> dict:
        return dict(self.bindings.get(win_instance_id) or {
            "win_instance_id": win_instance_id,
            "win_definition_id": f"def-{win_instance_id}",
            "care_plan_id": "cp-1",
            "patient_id": "patient-1",
            "title": "Task",
            "category": "task",
            "instructions": "",
            "criticality": "medium",
            "flexibility": "flexible",
            "recurrence_type": "one_off",
        })

    def override_recurring_task(self, *, win_instance_id: str, actor_id: str, start_at_iso: str, end_at_iso: str) -> dict:
        binding = self.get_win_binding(win_instance_id)
        self.created_tasks.append(
            {
                "patient_id": binding["patient_id"],
                "actor_id": actor_id,
                "category": binding["category"],
                "title": binding["title"],
                "instructions": binding["instructions"],
                "start_at_iso": start_at_iso,
                "end_at_iso": end_at_iso,
                "criticality": binding["criticality"],
                "flexibility": binding["flexibility"],
            }
        )
        self.superseded_instances.append({"instance_id": win_instance_id, "actor_id": actor_id})
        return {"ok": True}

    def save_pending_gateway_action(self, *, pending_key: str, plan: dict, expires_at_iso: str) -> dict:
        self.pending_gateway_actions[pending_key] = {"plan": dict(plan), "expires_at": expires_at_iso}
        return {"ok": True}

    def get_pending_gateway_action(self, pending_key: str) -> dict | None:
        payload = self.pending_gateway_actions.get(pending_key)
        return dict(payload) if payload is not None else None

    def clear_pending_gateway_action(self, pending_key: str) -> dict:
        self.pending_gateway_actions.pop(pending_key, None)
        return {"ok": True}


class _ObserverAdapter(_AdapterBase):
    def resolve_context(self, phone_number: str) -> dict | None:
        return {
            "tenant_id": "tenant-1",
            "participant_id": "participant-2",
            "participant_role": "caregiver",
            "patient_id": "patient-1",
            "patient_timezone": "Asia/Kolkata",
            "patient_persona": "caregiver_managed_elder",
        }


class _OpenClawOK:
    def handle(self, text: str, context) -> CommandResult:  # noqa: ANN001
        return CommandResult(action="openclaw_fallback", text="OpenClaw says hello.")


class _OpenClawUnavailable:
    def handle(self, text: str, context) -> CommandResult:  # noqa: ANN001
        return CommandResult(action="unavailable", text="")


class _FakeRequest:
    def __init__(self, form_body: str) -> None:
        self._body = form_body.encode("utf-8")

    async def body(self) -> bytes:
        return self._body


def _post_gateway(body: dict[str, str]):
    encoded = urlencode(body)
    return asyncio.run(twilio_gateway.twilio_gateway_webhook(_FakeRequest(encoded)))


class _FakeIdentityService:
    def __init__(self) -> None:
        self.identity: ParticipantIdentity | None = ParticipantIdentity(
            tenant_id="tenant-1",
            participant_id="participant-1",
            participant_role=Role.CAREGIVER,
        )
        self.active_patient_id: str | None = "patient-1"
        self.linked_patients: list[LinkedPatientSummary] = [
            LinkedPatientSummary(
                patient_id="patient-1",
                display_name="Patient One",
                timezone="Asia/Kolkata",
                tenant_id="tenant-1",
            )
        ]

    def resolve_participant_by_phone(self, phone_number: str) -> ParticipantIdentity | None:
        return self.identity

    def list_linked_patients(self, participant_id: str) -> list[LinkedPatientSummary]:
        return list(self.linked_patients)

    def get_active_patient_context(self, participant_id: str) -> str | None:
        return self.active_patient_id

    def set_active_patient_context(self, participant_id: str, patient_id: str, selection_source: str) -> None:
        self.active_patient_id = patient_id

    def clear_active_patient_context(self, participant_id: str) -> None:
        self.active_patient_id = None


class _FakeOnboardingService:
    def __init__(self) -> None:
        self.setup_active = False
        self.last_setup_type: str | None = None
        self.onboarding_active = False

    def _activate_setup_session(self, *, phone_number: str, participant_id: str, patient_id: str, source: str) -> None:
        self.setup_active = True

    def maybe_handle_message(self, *, sender_phone: str, body: str, identity, linked_patient_count: int):  # noqa: ANN001
        normalized = body.strip().lower()
        if identity is None and body.strip().lower() == "hi":
            return "Welcome to CareOS Lite onboarding. Are you: 1) myself 2) someone I care for"
        if identity is not None and linked_patient_count > 0 and normalized == "register me as patient":
            self.onboarding_active = True
            return "You already have caregiver access. Are you onboarding for:\n1) myself\n2) someone I care for\nReply: myself or someone I care for"
        if identity is not None and linked_patient_count > 0 and self.onboarding_active:
            if normalized in {"cancel onboarding", "exit onboarding", "stop onboarding"}:
                self.onboarding_active = False
                return "Okay, I closed onboarding. Reply 'help' for commands."
            if normalized in {"restart onboarding", "start onboarding again"}:
                return "Restarting onboarding.\nAre you onboarding for:\n1) myself\n2) someone I care for\nReply: myself or someone I care for"
        if self.setup_active:
            if normalized in {"cancel setup", "cancel wizard"}:
                self.setup_active = False
                self.last_setup_type = None
                return "Okay, I cancelled setup. Reply 'add a medication', 'add an appointment', or 'add a routine' to start again."
            if normalized in {"restart setup", "setup menu", "menu"}:
                self.last_setup_type = None
                return "Care setup menu:\n1) add medications\n2) add appointments\n3) add routines\n4) finish for now\nReply 1-4"
            if normalized == "add medications":
                self.last_setup_type = "medication"
                return "Medication name?"
            if normalized == "add appointments":
                self.last_setup_type = "appointment"
                return "Appointment title?"
            if normalized == "add routines":
                self.last_setup_type = "routine"
                return "Routine category: 1) meal 2) movement 3) sleep 4) therapy"
        return None


class _FakeStore:
    def __init__(self) -> None:
        self.participants = {
            "participant-1": {
                "id": "participant-1",
                "display_name": "Primary Caregiver",
                "phone_number": "whatsapp:+15550001111",
                "role": "caregiver",
                "active": True,
            },
            "participant-2": {
                "id": "participant-2",
                "display_name": "Observer Caregiver",
                "phone_number": "whatsapp:+15550002222",
                "role": "caregiver",
                "active": True,
            },
        }
        self.links = {
            ("participant-1", "patient-1"): {
                "caregiver_participant_id": "participant-1",
                "patient_id": "patient-1",
                "display_name": "Primary Caregiver",
                "phone_number": "whatsapp:+15550001111",
                "preset": "primary_caregiver",
                "scopes": ["view_dashboard", "update_task"],
                "notification_preferences": {"due_reminders": True},
                "authorization_version": 1,
                "can_edit_plan": True,
            },
            ("participant-2", "patient-1"): {
                "caregiver_participant_id": "participant-2",
                "patient_id": "patient-1",
                "display_name": "Observer Caregiver",
                "phone_number": "whatsapp:+15550002222",
                "preset": "observer",
                "scopes": ["view_dashboard"],
                "notification_preferences": {"due_reminders": False},
                "authorization_version": 2,
                "can_edit_plan": False,
            },
        }

    def list_caregiver_links_for_patient(self, patient_id: str) -> list[dict]:
        return [dict(link) for (participant_id, linked_patient_id), link in self.links.items() if linked_patient_id == patient_id]

    def get_caregiver_link(self, caregiver_participant_id: str, patient_id: str) -> dict | None:
        link = self.links.get((caregiver_participant_id, patient_id))
        return dict(link) if link is not None else None

    def find_participant_record_by_phone(self, phone_number: str) -> dict | None:
        normalized = phone_number.replace(" ", "")
        with_prefix = normalized if normalized.startswith("whatsapp:") else f"whatsapp:{normalized}"
        for participant in self.participants.values():
            if participant["phone_number"] in {normalized, with_prefix}:
                return dict(participant)
        return None

    def update_caregiver_link_preset(self, caregiver_participant_id: str, patient_id: str, preset: str) -> dict | None:
        link = self.links.get((caregiver_participant_id, patient_id))
        if link is None:
            return None
        link = dict(link)
        link["preset"] = "observer" if preset == "observer" else "primary_caregiver"
        link["authorization_version"] = int(link.get("authorization_version", 1)) + 1
        link["can_edit_plan"] = preset != "observer"
        link["notification_preferences"] = {"due_reminders": preset != "observer"}
        self.links[(caregiver_participant_id, patient_id)] = link
        return dict(link)


class _FakeLegacyRouter:
    def handle(self, text: str, context: ParticipantContext) -> CommandResult:
        normalized = text.strip().lower()
        if normalized in {"whoami", "profile"}:
            return CommandResult(
                action="whoami",
                text=(
                    f"You are {context.participant_role.value}. "
                    f"Active patient: {context.patient_id}. "
                    f"Timezone: {context.patient_timezone}."
                ),
            )
        if normalized == "next":
            return CommandResult(action="next", text="Next: 08:00 Morning meds [pending]")
        if normalized in {"schedule", "today"}:
            return CommandResult(action="schedule", text="Schedule (2026-03-12):\n1. 08:00 Morning meds [pending]")
        if normalized == "status":
            return CommandResult(action="status", text="Status: completed=0, due=1, missed=0, skipped=0, score=0.0%")
        if normalized in {"help", "?"}:
            return CommandResult(
                action="help",
                text=(
                    "Commands: schedule, next, status, whoami, patients, switch, use <n>, dashboard, caregivers, "
                    "set caregiver <phone> as observer|primary, invite caregiver, pending invites, cancel invite <code>, "
                    "add a medication, add an appointment, add a routine, "
                    "restart setup, cancel setup, register me as patient, cancel onboarding, restart onboarding, "
                    "done <item_no|win_id> [more items...], delay, skip"
                ),
            )
        if normalized.startswith("done "):
            refs = [
                token
                for token in text.strip().split(maxsplit=1)[1].replace(",", " ").split()
                if token and token.lower() not in {"and", "&", "then"}
            ]
            if len(refs) == 1:
                return CommandResult(action="done", text=f"Marked {refs[0]} as completed.")
            return CommandResult(action="done", text=f"Marked {', '.join(refs)} as completed.")
        if normalized.startswith("skip "):
            return CommandResult(action="skip", text=f"Marked {text.strip().split(maxsplit=1)[1]} as skipped.")
        if normalized.startswith("delay "):
            parts = text.strip().split()
            return CommandResult(action="delay", text=f"Delayed {parts[1]} by {parts[2]} minutes.")
        return CommandResult(action="fallback", text="Unsupported")


class _FakeAppContext:
    def __init__(self) -> None:
        self.identity_service = _FakeIdentityService()
        self.onboarding = _FakeOnboardingService()
        self.router = _FakeLegacyRouter()
        self.store = _FakeStore()


twilio_gateway.app_context = _FakeAppContext()


def test_gateway_openclaw_first_uses_delegate(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "openclaw_first"
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        monkeypatch.setattr(twilio_gateway, "openclaw_delegate", _OpenClawOK())
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "what is next?",
                "MessageSid": "SM-gw-openclaw-1",
            }
        )
        assert response.status_code == 200
        assert b"OpenClaw says hello." in response.body
    finally:
        settings.gateway_conversation_mode = previous_mode


def test_gateway_openclaw_first_falls_back_to_deterministic(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "openclaw_first"
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        monkeypatch.setattr(twilio_gateway, "openclaw_delegate", _OpenClawUnavailable())
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "status",
                "MessageSid": "SM-gw-openclaw-2",
            }
        )
        assert response.status_code == 200
        assert b"Status: completed=0, due=1, missed=0, skipped=0, score=0.0%" in response.body
    finally:
        settings.gateway_conversation_mode = previous_mode


def test_gateway_dispatches_dashboard_intent_to_care_dash(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "give me the patient summary",
                "MessageSid": "SM-gw-openclaw-3",
            }
        )
        assert response.status_code == 200
        assert b"Open caregiver dashboard: https://careos.theginger.ai/v/test-token" in response.body
    finally:
        settings.gateway_conversation_mode = previous_mode


def test_gateway_restores_whoami_legacy_command(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "whoami",
                "MessageSid": "SM-gw-openclaw-whoami",
            }
        )
        assert response.status_code == 200
        assert b"You are caregiver." in response.body
        assert b"Active patient: patient-1." in response.body
    finally:
        settings.gateway_conversation_mode = previous_mode


def test_gateway_restores_next_legacy_command(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "next",
                "MessageSid": "SM-gw-openclaw-next",
            }
        )
        assert response.status_code == 200
        assert b"Next: 08:00 Morning meds [pending]" in response.body
    finally:
        settings.gateway_conversation_mode = previous_mode


def test_gateway_restores_help_legacy_command(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "help",
                "MessageSid": "SM-gw-openclaw-help",
            }
        )
        assert response.status_code == 200
        assert b"Commands: schedule, next, status, whoami" in response.body
        assert b"caregivers" in response.body
        assert b"invite caregiver" in response.body
        assert b"register me as patient" in response.body
    finally:
        settings.gateway_conversation_mode = previous_mode


def test_gateway_restores_schedule_today_and_status_legacy_commands(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "openclaw_first"
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        monkeypatch.setattr(twilio_gateway, "openclaw_delegate", _OpenClawUnavailable())
        schedule_response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "today",
                "MessageSid": "SM-gw-legacy-today",
            }
        )
        status_response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "status",
                "MessageSid": "SM-gw-legacy-status",
            }
        )
        assert schedule_response.status_code == 200
        assert b"Schedule (2026-03-12):" in schedule_response.body
        assert status_response.status_code == 200
        assert b"Status: completed=0, due=1, missed=0, skipped=0, score=0.0%" in status_response.body
    finally:
        settings.gateway_conversation_mode = previous_mode


def test_gateway_restores_done_skip_delay_legacy_commands(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "openclaw_first"
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        monkeypatch.setattr(twilio_gateway, "openclaw_delegate", _OpenClawUnavailable())
        done_response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "done abc12345",
                "MessageSid": "SM-gw-legacy-done",
            }
        )
        skip_response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "skip abc12345",
                "MessageSid": "SM-gw-legacy-skip",
            }
        )
        delay_response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "delay abc12345 30",
                "MessageSid": "SM-gw-legacy-delay",
            }
        )
        assert done_response.status_code == 200
        assert b"Marked abc12345 as completed." in done_response.body
        assert skip_response.status_code == 200
        assert b"Marked abc12345 as skipped." in skip_response.body
        assert delay_response.status_code == 200
        assert b"Delayed abc12345 by 30 minutes." in delay_response.body
    finally:
        settings.gateway_conversation_mode = previous_mode


def test_gateway_restores_batch_done_legacy_command(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "openclaw_first"
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        monkeypatch.setattr(twilio_gateway, "openclaw_delegate", _OpenClawUnavailable())
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "done 1 2 3 4 5 6",
                "MessageSid": "SM-gw-legacy-done-batch",
            }
        )
        assert response.status_code == 200
        assert b"Marked 1, 2, 3, 4, 5, 6 as completed." in response.body
    finally:
        settings.gateway_conversation_mode = previous_mode


def test_gateway_restores_batch_done_with_and_legacy_command(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "openclaw_first"
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        monkeypatch.setattr(twilio_gateway, "openclaw_delegate", _OpenClawUnavailable())
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "done 1 and 2",
                "MessageSid": "SM-gw-legacy-done-batch-and",
            }
        )
        assert response.status_code == 200
        assert b"Marked 1, 2 as completed." in response.body
    finally:
        settings.gateway_conversation_mode = previous_mode


def test_gateway_marks_single_due_item_completed_from_taken_reply(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    adapter = _AdapterBase()
    adapter.timeline = [
        {
            "win_instance_id": "win-due-1",
            "title": "Ecosprin 75mg",
            "category": "medication",
            "criticality": "high",
            "flexibility": "rigid",
            "scheduled_start": "2099-03-15T08:30:00+00:00",
            "scheduled_end": "2099-03-15T09:00:00+00:00",
            "current_state": "due",
        }
    ]
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", adapter)
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "Taken",
                "MessageSid": "SM-gw-taken-1",
            }
        )
        assert response.status_code == 200
        assert b"Marked ecosprin 75mg as completed." in response.body
        assert adapter.completed_instances == [{"instance_id": "win-due-1", "actor_id": "participant-1"}]
    finally:
        settings.gateway_conversation_mode = previous_mode


def test_gateway_marks_latest_reminder_target_completed_from_taken_reply(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    adapter = _AdapterBase()
    adapter.timeline = [
        {
            "win_instance_id": "win-due-1",
            "title": "Some other task",
            "category": "routine",
            "criticality": "low",
            "flexibility": "flexible",
            "scheduled_start": "2099-03-15T08:30:00+00:00",
            "scheduled_end": "2099-03-15T09:00:00+00:00",
            "current_state": "due",
        }
    ]
    adapter.get_latest_scheduled_reminder_context = lambda participant_id, patient_id: {  # type: ignore[method-assign]
        "participant_id": participant_id,
        "patient_id": patient_id,
        "win_instance_id": "win-reminder-1",
        "title": "Ecosprin 75mg",
        "scheduled_start": "2099-03-15T09:30:00+00:00",
        "correlation_id": "sched:patient-1:win-reminder-1:participant-1",
        "created_at": "2099-03-15T09:30:00+00:00",
    }
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", adapter)
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "I took it",
                "MessageSid": "SM-gw-taken-reminder-1",
            }
        )
        assert response.status_code == 200
        assert b"Marked ecosprin 75mg as completed." in response.body
        assert adapter.completed_instances == [{"instance_id": "win-reminder-1", "actor_id": "participant-1"}]
    finally:
        settings.gateway_conversation_mode = previous_mode


def test_gateway_clarifies_taken_reply_when_multiple_due_items_exist(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    adapter = _AdapterBase()
    adapter.timeline = [
        {
            "win_instance_id": "win-due-1",
            "title": "Ecosprin 75mg",
            "category": "medication",
            "criticality": "high",
            "flexibility": "rigid",
            "scheduled_start": "2099-03-15T08:30:00+00:00",
            "scheduled_end": "2099-03-15T09:00:00+00:00",
            "current_state": "due",
        },
        {
            "win_instance_id": "win-due-2",
            "title": "Dytor 5mg",
            "category": "medication",
            "criticality": "medium",
            "flexibility": "windowed",
            "scheduled_start": "2099-03-15T09:30:00+00:00",
            "scheduled_end": "2099-03-15T10:00:00+00:00",
            "current_state": "due",
        },
    ]
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", adapter)
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "I took it",
                "MessageSid": "SM-gw-taken-2",
            }
        )
        assert response.status_code == 200
        assert b"I found multiple due items." in response.body
        assert b"done 1" in response.body
        assert b"done 2" in response.body
        assert adapter.completed_instances == []
    finally:
        settings.gateway_conversation_mode = previous_mode


def test_gateway_restores_patients_and_use_commands(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    fake_context = _FakeAppContext()
    fake_context.identity_service.linked_patients = [
        LinkedPatientSummary(patient_id="patient-1", display_name="Father", timezone="Asia/Kolkata", tenant_id="tenant-1"),
        LinkedPatientSummary(patient_id="patient-2", display_name="Mother", timezone="Asia/Kolkata", tenant_id="tenant-1"),
    ]
    fake_context.identity_service.active_patient_id = None
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        monkeypatch.setattr(twilio_gateway, "app_context", fake_context)
        patients_response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "patients",
                "MessageSid": "SM-gw-openclaw-patients",
            }
        )
        assert patients_response.status_code == 200
        assert b"Multiple patients are linked to this number." in patients_response.body
        use_response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "use 2",
                "MessageSid": "SM-gw-openclaw-use",
            }
        )
        assert use_response.status_code == 200
        assert b"Switched to Mother (Asia/Kolkata)." in use_response.body
    finally:
        monkeypatch.setattr(twilio_gateway, "app_context", _FakeAppContext())
        settings.gateway_conversation_mode = previous_mode


def test_gateway_patients_command_handles_single_patient_context(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        monkeypatch.setattr(twilio_gateway, "app_context", _FakeAppContext())
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "patients",
                "MessageSid": "SM-gw-openclaw-patients-single",
            }
        )
        assert response.status_code == 200
        assert b"Active patient: Patient One (Asia/Kolkata)." in response.body
    finally:
        monkeypatch.setattr(twilio_gateway, "app_context", _FakeAppContext())
        settings.gateway_conversation_mode = previous_mode


def test_gateway_lists_caregivers_for_active_patient(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        monkeypatch.setattr(twilio_gateway, "app_context", _FakeAppContext())
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "caregivers",
                "MessageSid": "SM-gw-caregivers-list",
            }
        )
        assert response.status_code == 200
        assert b"Caregivers:" in response.body
        assert b"Primary Caregiver" in response.body
        assert b"Observer Caregiver" in response.body
        assert b"set caregiver &lt;phone&gt; as observer|primary" in response.body
    finally:
        monkeypatch.setattr(twilio_gateway, "app_context", _FakeAppContext())
        settings.gateway_conversation_mode = previous_mode


def test_gateway_primary_caregiver_can_update_observer_preset(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    fake_context = _FakeAppContext()
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        monkeypatch.setattr(twilio_gateway, "app_context", fake_context)
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "set caregiver +15550002222 as primary",
                "MessageSid": "SM-gw-caregivers-update",
            }
        )
        assert response.status_code == 200
        assert b"Updated Observer Caregiver to primary caregiver." in response.body
        updated = fake_context.store.get_caregiver_link("participant-2", "patient-1")
        assert updated is not None
        assert updated["preset"] == "primary_caregiver"
        assert updated["authorization_version"] == 3
    finally:
        monkeypatch.setattr(twilio_gateway, "app_context", _FakeAppContext())
        settings.gateway_conversation_mode = previous_mode


def test_gateway_updates_caregiver_preset_from_linked_phone_even_if_global_lookup_is_wrong(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    fake_context = _FakeAppContext()

    def _wrong_lookup(phone_number: str) -> dict | None:
        normalized = phone_number.replace(" ", "")
        if normalized in {"+15550002222", "whatsapp:+15550002222"}:
            return {
                "id": "participant-patient-shadow",
                "display_name": "Shadow Patient",
                "phone_number": "whatsapp:+15550002222",
                "role": "patient",
                "active": True,
            }
        return fake_context.store.find_participant_record_by_phone(phone_number)

    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        monkeypatch.setattr(twilio_gateway, "app_context", fake_context)
        monkeypatch.setattr(fake_context.store, "find_participant_record_by_phone", _wrong_lookup)
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "set caregiver +15550002222 as primary",
                "MessageSid": "SM-gw-caregivers-update-linked-phone",
            }
        )
        assert response.status_code == 200
        assert b"Updated Observer Caregiver to primary caregiver." in response.body
        updated = fake_context.store.get_caregiver_link("participant-2", "patient-1")
        assert updated is not None
        assert updated["preset"] == "primary_caregiver"
    finally:
        monkeypatch.setattr(twilio_gateway, "app_context", _FakeAppContext())
        settings.gateway_conversation_mode = previous_mode


def test_gateway_observer_cannot_update_caregiver_preset(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    fake_context = _FakeAppContext()
    fake_context.identity_service.identity = ParticipantIdentity(
        tenant_id="tenant-1",
        participant_id="participant-2",
        participant_role=Role.CAREGIVER,
    )
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _ObserverAdapter())
        monkeypatch.setattr(twilio_gateway, "app_context", fake_context)
        response = _post_gateway(
            {
                "From": "whatsapp:+15550002222",
                "To": "whatsapp:+14155238886",
                "Body": "set caregiver +15550001111 as observer",
                "MessageSid": "SM-gw-caregivers-denied",
            }
        )
        assert response.status_code == 200
        assert b"Only a primary caregiver can change caregiver presets." in response.body
    finally:
        monkeypatch.setattr(twilio_gateway, "app_context", _FakeAppContext())
        settings.gateway_conversation_mode = previous_mode


def test_gateway_restores_onboarding_entry(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    fake_context = _FakeAppContext()
    fake_context.identity_service.identity = None
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        monkeypatch.setattr(twilio_gateway, "app_context", fake_context)
        response = _post_gateway(
            {
                "From": "whatsapp:+15550009999",
                "To": "whatsapp:+14155238886",
                "Body": "hi",
                "MessageSid": "SM-gw-openclaw-hi",
            }
        )
        assert response.status_code == 200
        assert b"Welcome to CareOS Lite onboarding." in response.body
    finally:
        monkeypatch.setattr(twilio_gateway, "app_context", _FakeAppContext())
        settings.gateway_conversation_mode = previous_mode


def test_gateway_existing_caregiver_can_cancel_onboarding(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    fake_context = _FakeAppContext()
    fake_context.onboarding.onboarding_active = True
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        monkeypatch.setattr(twilio_gateway, "app_context", fake_context)
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "cancel onboarding",
                "MessageSid": "SM-gw-cancel-onboarding",
            }
        )
        assert response.status_code == 200
        assert b"Okay, I closed onboarding." in response.body
        assert fake_context.onboarding.onboarding_active is False
    finally:
        monkeypatch.setattr(twilio_gateway, "app_context", _FakeAppContext())
        settings.gateway_conversation_mode = previous_mode


def test_existing_caregiver_can_trigger_self_onboarding(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    fake_context = _FakeAppContext()
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        monkeypatch.setattr(twilio_gateway, "app_context", fake_context)
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "register me as patient",
                "MessageSid": "SM-gw-onboard-existing",
            }
        )
        assert response.status_code == 200
        assert b"You already have caregiver access." in response.body
        assert b"Are you onboarding for:" in response.body
    finally:
        monkeypatch.setattr(twilio_gateway, "app_context", _FakeAppContext())
        settings.gateway_conversation_mode = previous_mode


def test_gateway_shortcuts_vague_add_medication_into_setup_wizard(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    fake_context = _FakeAppContext()
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        monkeypatch.setattr(twilio_gateway, "app_context", fake_context)
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "Add a medication",
                "MessageSid": "SM-gw-add-medication",
            }
        )
        assert response.status_code == 200
        assert b"Medication name?" in response.body
        assert fake_context.onboarding.last_setup_type == "medication"
    finally:
        monkeypatch.setattr(twilio_gateway, "app_context", _FakeAppContext())
        settings.gateway_conversation_mode = previous_mode


def test_gateway_shortcuts_vague_add_appointment_into_setup_wizard(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    fake_context = _FakeAppContext()
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        monkeypatch.setattr(twilio_gateway, "app_context", fake_context)
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "Add an appointment",
                "MessageSid": "SM-gw-add-appointment",
            }
        )
        assert response.status_code == 200
        assert b"Appointment title?" in response.body
        assert fake_context.onboarding.last_setup_type == "appointment"
    finally:
        monkeypatch.setattr(twilio_gateway, "app_context", _FakeAppContext())
        settings.gateway_conversation_mode = previous_mode


def test_gateway_shortcuts_vague_add_routine_into_setup_wizard(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    fake_context = _FakeAppContext()
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        monkeypatch.setattr(twilio_gateway, "app_context", fake_context)
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "Add a routine",
                "MessageSid": "SM-gw-add-routine",
            }
        )
        assert response.status_code == 200
        assert b"Routine category:" in response.body
        assert fake_context.onboarding.last_setup_type == "routine"
    finally:
        monkeypatch.setattr(twilio_gateway, "app_context", _FakeAppContext())
        settings.gateway_conversation_mode = previous_mode


def test_gateway_setup_cancel_and_restart_commands(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    fake_context = _FakeAppContext()
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        monkeypatch.setattr(twilio_gateway, "app_context", fake_context)
        _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "Add a medication",
                "MessageSid": "SM-gw-setup-start",
            }
        )
        restart_response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "restart setup",
                "MessageSid": "SM-gw-setup-restart",
            }
        )
        cancel_response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "cancel setup",
                "MessageSid": "SM-gw-setup-cancel",
            }
        )
        assert restart_response.status_code == 200
        assert b"Care setup menu:" in restart_response.body
        assert cancel_response.status_code == 200
        assert b"Okay, I cancelled setup." in cancel_response.body
        assert fake_context.onboarding.setup_active is False
    finally:
        monkeypatch.setattr(twilio_gateway, "app_context", _FakeAppContext())
        settings.gateway_conversation_mode = previous_mode


def test_gateway_dashboard_intent_returns_friendly_message_on_dash_failure(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"

    class _BrokenAdapter(_AdapterBase):
        def generate_dashboard_view(self, **kwargs) -> dict:  # type: ignore[override]
            raise DashboardLinkError("dashboard_link_unavailable")

    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _BrokenAdapter())
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "how is my patient doing",
                "MessageSid": "SM-gw-openclaw-4",
            }
        )
        assert response.status_code == 200
        assert b"secure caregiver dashboard is temporarily unavailable" in response.body
    finally:
        settings.gateway_conversation_mode = previous_mode


def test_gateway_proposes_structured_walk_confirmation(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    twilio_gateway._PENDING_ACTIONS.clear()
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "Add evening walk for today",
                "MessageSid": "SM-gw-openclaw-5",
            }
        )
        assert response.status_code == 200
        assert b"Reply YES to confirm or CANCEL." in response.body
    finally:
        twilio_gateway._PENDING_ACTIONS.clear()
        settings.gateway_conversation_mode = previous_mode


def test_gateway_confirms_and_creates_walk(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    adapter = _AdapterBase()
    twilio_gateway._PENDING_ACTIONS.clear()
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", adapter)
        first = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "Add evening walk for today",
                "MessageSid": "SM-gw-openclaw-6",
            }
        )
        assert first.status_code == 200
        second = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "YES",
                "MessageSid": "SM-gw-openclaw-7",
            }
        )
        assert second.status_code == 200
        assert b"Created evening walk." in second.body
        assert len(adapter.created_tasks) == 1
    finally:
        twilio_gateway._PENDING_ACTIONS.clear()
        settings.gateway_conversation_mode = previous_mode


def test_gateway_pending_confirmation_survives_memory_clear(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    adapter = _AdapterBase()
    twilio_gateway._PENDING_ACTIONS.clear()
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", adapter)
        first = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "Add evening walk for today",
                "MessageSid": "SM-gw-openclaw-7b",
            }
        )
        assert first.status_code == 200
        twilio_gateway._PENDING_ACTIONS.clear()
        second = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "YES",
                "MessageSid": "SM-gw-openclaw-7c",
            }
        )
        assert second.status_code == 200
        assert b"Created evening walk." in second.body
        assert len(adapter.created_tasks) == 1
        assert adapter.pending_gateway_actions == {}
    finally:
        twilio_gateway._PENDING_ACTIONS.clear()
        settings.gateway_conversation_mode = previous_mode


def test_gateway_returns_clarification_for_ambiguous_target(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    adapter = _AdapterBase()
    adapter.timeline = [
        {
            "win_instance_id": "med-a",
            "title": "Ecosprin 75mg",
            "category": "medication",
            "criticality": "high",
            "flexibility": "rigid",
            "scheduled_start": "2099-03-14T08:30:00+00:00",
            "scheduled_end": "2099-03-14T09:00:00+00:00",
            "current_state": "pending",
        },
        {
            "win_instance_id": "med-b",
            "title": "Ecosprin 75mg",
            "category": "medication",
            "criticality": "high",
            "flexibility": "rigid",
            "scheduled_start": "2099-03-14T12:30:00+00:00",
            "scheduled_end": "2099-03-14T13:00:00+00:00",
            "current_state": "pending",
        },
    ]
    twilio_gateway._PENDING_ACTIONS.clear()
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", adapter)
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "Move my Ecosprin 75mg to evening",
                "MessageSid": "SM-gw-openclaw-25",
            }
        )
        assert response.status_code == 200
        assert b"multiple matches" in response.body.lower()
        assert b"8:30 am" in response.body.lower()
        assert b"12:30 pm" in response.body.lower()
        assert b"reply with the time or item number" in response.body.lower()
        assert adapter.pending_gateway_actions == {}
    finally:
        twilio_gateway._PENDING_ACTIONS.clear()
        settings.gateway_conversation_mode = previous_mode


def test_gateway_cancels_pending_walk(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    adapter = _AdapterBase()
    twilio_gateway._PENDING_ACTIONS.clear()
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", adapter)
        _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "Add evening walk for today",
                "MessageSid": "SM-gw-openclaw-8",
            }
        )
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "CANCEL",
                "MessageSid": "SM-gw-openclaw-9",
            }
        )
        assert response.status_code == 200
        assert b"I did not create that change" in response.body
        assert adapter.created_tasks == []
    finally:
        twilio_gateway._PENDING_ACTIONS.clear()
        settings.gateway_conversation_mode = previous_mode


def test_gateway_proposes_structured_diagnostic_task_confirmation(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    twilio_gateway._PENDING_ACTIONS.clear()
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "I need to get calcium score test done over the next 2 days",
                "MessageSid": "SM-gw-openclaw-12",
            }
        )
        assert response.status_code == 200
        assert b"calcium score test" in response.body.lower()
        assert b"next 2 days" in response.body.lower()
    finally:
        twilio_gateway._PENDING_ACTIONS.clear()
        settings.gateway_conversation_mode = previous_mode


def test_gateway_confirms_and_creates_diagnostic_task(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    adapter = _AdapterBase()
    twilio_gateway._PENDING_ACTIONS.clear()
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", adapter)
        _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "I need to get calcium score test done over the next 2 days",
                "MessageSid": "SM-gw-openclaw-13",
            }
        )
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "YES",
                "MessageSid": "SM-gw-openclaw-14",
            }
        )
        assert response.status_code == 200
        assert b"Created calcium score test." in response.body
        assert len(adapter.created_tasks) == 1
        assert adapter.created_tasks[0]["category"] == "diagnostic_test"
    finally:
        twilio_gateway._PENDING_ACTIONS.clear()
        settings.gateway_conversation_mode = previous_mode


def test_gateway_proposes_appointment_task_confirmation(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    twilio_gateway._PENDING_ACTIONS.clear()
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "Schedule cardiology appointment tomorrow morning",
                "MessageSid": "SM-gw-openclaw-15",
            }
        )
        assert response.status_code == 200
        assert b"cardiology appointment" in response.body.lower()
        assert b"Reply YES to confirm or CANCEL." in response.body
    finally:
        twilio_gateway._PENDING_ACTIONS.clear()
        settings.gateway_conversation_mode = previous_mode


def test_gateway_proposes_medication_reminder_confirmation(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    twilio_gateway._PENDING_ACTIONS.clear()
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "Remind me to take atorvastatin tomorrow evening",
                "MessageSid": "SM-gw-openclaw-16",
            }
        )
        assert response.status_code == 200
        assert b"medication reminder" in response.body.lower()
        assert b"atorvastatin" in response.body.lower()
    finally:
        twilio_gateway._PENDING_ACTIONS.clear()
        settings.gateway_conversation_mode = previous_mode


def test_gateway_proposes_complete_task_confirmation(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    twilio_gateway._PENDING_ACTIONS.clear()
    adapter = _AdapterBase()
    adapter.timeline = [
        {
            "win_instance_id": "win-1",
            "title": "Calcium score test",
            "category": "diagnostic_test",
            "criticality": "medium",
            "flexibility": "windowed",
            "scheduled_start": "2026-03-14T10:00:00+00:00",
            "scheduled_end": "2026-03-14T11:00:00+00:00",
            "current_state": "pending",
        }
    ]
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", adapter)
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "I got the calcium score test done",
                "MessageSid": "SM-gw-openclaw-17",
            }
        )
        assert response.status_code == 200
        assert b"mark calcium score test as completed" in response.body.lower()
    finally:
        twilio_gateway._PENDING_ACTIONS.clear()
        settings.gateway_conversation_mode = previous_mode


def test_gateway_confirms_and_completes_task(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    twilio_gateway._PENDING_ACTIONS.clear()
    adapter = _AdapterBase()
    adapter.timeline = [
        {
            "win_instance_id": "win-2",
            "title": "Calcium score test",
            "category": "diagnostic_test",
            "criticality": "medium",
            "flexibility": "windowed",
            "scheduled_start": "2026-03-14T10:00:00+00:00",
            "scheduled_end": "2026-03-14T11:00:00+00:00",
            "current_state": "pending",
        }
    ]
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", adapter)
        _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "I got the calcium score test done",
                "MessageSid": "SM-gw-openclaw-18",
            }
        )
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "YES",
                "MessageSid": "SM-gw-openclaw-19",
            }
        )
        assert response.status_code == 200
        assert b"Marked calcium score test as completed." in response.body
        assert adapter.completed_instances == [{"instance_id": "win-2", "actor_id": "participant-1"}]
    finally:
        twilio_gateway._PENDING_ACTIONS.clear()
        settings.gateway_conversation_mode = previous_mode


def test_gateway_proposes_update_task_confirmation(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    twilio_gateway._PENDING_ACTIONS.clear()
    adapter = _AdapterBase()
    adapter.timeline = [
        {
            "win_instance_id": "win-3",
            "title": "Evening walk",
            "category": "routine",
            "criticality": "low",
            "flexibility": "flexible",
            "scheduled_start": "2026-03-14T18:00:00+00:00",
            "scheduled_end": "2026-03-14T19:00:00+00:00",
            "current_state": "pending",
        }
    ]
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", adapter)
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "Move my walk to tomorrow morning",
                "MessageSid": "SM-gw-openclaw-20",
            }
        )
        assert response.status_code == 200
        assert b"move evening walk to" in response.body.lower()
    finally:
        twilio_gateway._PENDING_ACTIONS.clear()
        settings.gateway_conversation_mode = previous_mode


def test_gateway_confirms_and_updates_task(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    twilio_gateway._PENDING_ACTIONS.clear()
    adapter = _AdapterBase()
    adapter.timeline = [
        {
            "win_instance_id": "win-4",
            "title": "Evening walk",
            "category": "routine",
            "criticality": "low",
            "flexibility": "flexible",
            "scheduled_start": "2026-03-14T18:00:00+00:00",
            "scheduled_end": "2026-03-14T19:00:00+00:00",
            "current_state": "pending",
        }
    ]
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", adapter)
        _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "Move my walk to tomorrow morning",
                "MessageSid": "SM-gw-openclaw-21",
            }
        )
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "YES",
                "MessageSid": "SM-gw-openclaw-22",
            }
        )
        assert response.status_code == 200
        assert b"Moved evening walk." in response.body
        assert adapter.rescheduled_tasks
        assert adapter.rescheduled_tasks[0]["instance_id"] == "win-4"
    finally:
        twilio_gateway._PENDING_ACTIONS.clear()
        settings.gateway_conversation_mode = previous_mode


def test_gateway_overrides_recurring_update_task(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    twilio_gateway._PENDING_ACTIONS.clear()
    adapter = _AdapterBase()
    adapter.timeline = [
        {
            "win_instance_id": "win-5",
            "title": "Dytor 5mg",
            "category": "medication",
            "criticality": "medium",
            "flexibility": "windowed",
            "scheduled_start": "2099-03-14T10:30:00+00:00",
            "scheduled_end": "2099-03-14T11:00:00+00:00",
            "current_state": "pending",
        }
    ]
    adapter.bindings["win-5"] = {
        "win_instance_id": "win-5",
        "win_definition_id": "def-win-5",
        "care_plan_id": "cp-1",
        "patient_id": "patient-1",
        "title": "Dytor 5mg",
        "category": "medication",
        "instructions": "Take Dytor 5mg.",
        "criticality": "medium",
        "flexibility": "windowed",
        "recurrence_type": "daily",
    }
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", adapter)
        _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "Move my Dytor 5mg to evening",
                "MessageSid": "SM-gw-openclaw-23",
            }
        )
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "YES",
                "MessageSid": "SM-gw-openclaw-24",
            }
        )
        assert response.status_code == 200
        assert b"Moved dytor 5mg." in response.body
        assert adapter.superseded_instances == [{"instance_id": "win-5", "actor_id": "participant-1"}]
        assert adapter.created_tasks
        assert adapter.created_tasks[-1]["title"] == "Dytor 5mg"
    finally:
        twilio_gateway._PENDING_ACTIONS.clear()
        settings.gateway_conversation_mode = previous_mode


def test_gateway_schedule_phrase_uses_schedule_not_critical_missed(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    previous_key = settings.openai_api_key
    settings.gateway_conversation_mode = "openclaw_first"
    settings.openai_api_key = "dummy-key"

    class _OpenClawUnavailableAlways:
        def handle(self, text: str, context) -> CommandResult:  # noqa: ANN001
            return CommandResult(action="unavailable", text="")

    class _ScheduleAdapter(_AdapterBase):
        def get_today(self, patient_id: str) -> dict:
            return {
                "patient_id": patient_id,
                "date": "2026-03-12",
                "timezone": "Asia/Kolkata",
                "timeline": [
                    {
                        "scheduled_start": "2026-03-12T08:00:00+00:00",
                        "title": "Morning meds",
                        "current_state": "pending",
                    }
                ],
            }

    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _ScheduleAdapter())
        monkeypatch.setattr(twilio_gateway, "openclaw_delegate", _OpenClawUnavailableAlways())
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "what's today's schedule",
                "MessageSid": "SM-gw-openclaw-10",
            }
        )
        assert response.status_code == 200
        assert b"Schedule (" in response.body
        assert b"Missed critical wins today" not in response.body
    finally:
        settings.openai_api_key = previous_key
        settings.gateway_conversation_mode = previous_mode


def test_gateway_openclaw_first_short_circuits_clear_schedule_read(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    previous_key = settings.openai_api_key
    settings.gateway_conversation_mode = "openclaw_first"
    settings.openai_api_key = "dummy-key"

    class _WrongOpenClaw:
        def handle(self, text: str, context) -> CommandResult:  # noqa: ANN001
            return CommandResult(action="openclaw_fallback", text="Missed critical wins today:\n- Wrong path")

    class _ScheduleAdapter(_AdapterBase):
        def get_today(self, patient_id: str) -> dict:
            return {
                "patient_id": patient_id,
                "date": "2026-03-12",
                "timezone": "Asia/Kolkata",
                "timeline": [
                    {
                        "scheduled_start": "2026-03-12T08:00:00+00:00",
                        "title": "Morning meds",
                        "current_state": "pending",
                    }
                ],
            }

    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _ScheduleAdapter())
        monkeypatch.setattr(twilio_gateway, "openclaw_delegate", _WrongOpenClaw())
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "what's today's schedule",
                "MessageSid": "SM-gw-openclaw-11",
            }
        )
        assert response.status_code == 200
        assert b"Schedule (" in response.body
        assert b"Wrong path" not in response.body
    finally:
        settings.openai_api_key = previous_key
        settings.gateway_conversation_mode = previous_mode
