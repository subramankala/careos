from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from careos.db.repositories.store import Store
from careos.domain.enums.core import Criticality, Flexibility, PersonaType, RecurrenceType, Role
from careos.domain.models.api import (
    AddWinsRequest,
    CarePlanCreate,
    CaregiverVerificationRequest,
    ParticipantCreate,
    ParticipantIdentity,
    PatientCreate,
    TenantCreate,
    WinDefinitionCreate,
    WinInstanceCreate,
)
from careos.integrations.twilio.sender import TwilioWhatsAppSender
from careos.settings import settings


class OnboardingService:
    def __init__(self, store: Store) -> None:
        self.store = store

    def _is_existing_user_onboarding_trigger(self, body: str) -> bool:
        normalized = " ".join(body.strip().lower().split())
        return normalized in {
            "register as patient",
            "register me as patient",
            "onboard myself",
            "register myself",
        }

    def _is_patient_invite_trigger(self, body: str) -> bool:
        normalized = " ".join(body.strip().lower().split())
        return normalized in {
            "invite caregiver",
            "add caregiver",
            "invite observer",
            "add observer",
            "invite an observer",
            "add an observer",
        }

    def _is_patient_invite_list_trigger(self, body: str) -> bool:
        normalized = " ".join(body.strip().lower().split())
        return normalized in {
            "invites",
            "invite status",
            "pending invites",
            "list invites",
            "show invites",
        }

    def _parse_patient_invite_cancel_command(self, body: str) -> str | None:
        normalized = " ".join(body.strip().split())
        lowered = normalized.lower()
        prefixes = (
            "cancel invite",
            "cancel caregiver invite",
            "cancel pending invite",
        )
        for prefix in prefixes:
            if lowered == prefix:
                return ""
            if lowered.startswith(prefix + " "):
                return normalized[len(prefix) :].strip()
        return None

    def _caregiver_preset_for_relationship(self, relationship: str) -> str:
        normalized = " ".join(str(relationship).strip().lower().split())
        if normalized in {"observer", "updates only", "family observer", "observer only"}:
            return "observer"
        return "primary_caregiver"

    def _is_onboarding_cancel_command(self, body: str) -> bool:
        normalized = " ".join(body.strip().lower().split())
        return normalized in {"cancel onboarding", "exit onboarding", "stop onboarding"}

    def _is_onboarding_restart_command(self, body: str) -> bool:
        normalized = " ".join(body.strip().lower().split())
        return normalized in {"restart onboarding", "start onboarding again"}

    def maybe_handle_message(
        self,
        *,
        sender_phone: str,
        body: str,
        identity: ParticipantIdentity | None,
        linked_patient_count: int,
    ) -> str | None:
        session = self.store.get_onboarding_session(sender_phone)
        normalized = body.strip().lower()

        if identity is not None and linked_patient_count > 0 and session is not None and session.status == "active":
            if self._is_onboarding_cancel_command(body):
                self._save_session(
                    sender_phone,
                    state="completed",
                    status="completed",
                    data=dict(session.data),
                    completion_note="onboarding_cancelled_by_existing_user",
                )
                return "Okay, I closed onboarding. Reply 'help' for commands."
            if self._is_onboarding_restart_command(body):
                self._save_session(
                    sender_phone,
                    state="choose_role",
                    status="active",
                    data={"existing_user": True},
                    completion_note="",
                )
                return "Restarting onboarding.\n" + self._role_prompt()
            invite_target = self._resolve_existing_user_patient_target(identity)
            if invite_target is not None:
                invite_management = self._handle_existing_user_invite_management(
                    sender_phone=sender_phone,
                    body=body,
                    invite_target=invite_target,
                )
                if invite_management is not None:
                    return invite_management

        # Phase C continuation: keep lightweight setup wizard active after onboarding/approval.
        if session is not None and session.status == "active" and session.state.startswith("setup_"):
            if identity is None:
                return "Could not resolve setup context. Reply 'hi' to restart onboarding."
            if linked_patient_count > 0 and self._is_patient_invite_trigger(body):
                invite_target = self._resolve_existing_user_patient_target(identity)
                if invite_target is None:
                    return "Could not resolve which patient this invite should apply to. Reply 'patients' first."
                self._save_session(
                    sender_phone,
                    state="patient_invite_caregiver_phone",
                    status="active",
                    data=invite_target,
                )
                return (
                    f"Inviting a caregiver for {invite_target['invite_patient_name']}. "
                    "Reply with caregiver WhatsApp number (+countrycode)."
                )
            return self._handle_setup_message(sender_phone=sender_phone, body=body, identity=identity, session_data=dict(session.data))

        verification_reply = self._handle_verification_message(sender_phone=sender_phone, body=body)
        if verification_reply is not None:
            return verification_reply

        if identity is not None and linked_patient_count > 0:
            if session is not None and session.status == "active":
                pass
            else:
                invite_target = self._resolve_existing_user_patient_target(identity)
                if invite_target is None:
                    return "Could not resolve which patient this invite should apply to. Reply 'patients' first."
                invite_management = self._handle_existing_user_invite_management(
                    sender_phone=sender_phone,
                    body=body,
                    invite_target=invite_target,
                )
                if invite_management is not None:
                    return invite_management
                if self._is_patient_invite_trigger(body):
                    self._save_session(
                        sender_phone,
                        state="patient_invite_caregiver_phone",
                        status="active",
                        data=invite_target,
                    )
                    return (
                        f"Inviting a caregiver for {invite_target['invite_patient_name']}. "
                        "Reply with caregiver WhatsApp number (+countrycode)."
                    )
                if self._is_existing_user_onboarding_trigger(body):
                    self._save_session(sender_phone, state="choose_role", status="active", data={"existing_user": True})
                    return "You already have caregiver access. " + self._role_prompt()
                return None

        if identity is not None and linked_patient_count == 0:
            pending = self.store.get_pending_verification_for_caregiver(identity.participant_id)
            if pending is not None:
                return self._handle_caregiver_pending(sender_phone=sender_phone, body=body, request=pending)

        now = datetime.now(UTC)
        expired = False
        if session and session.status == "active" and session.expires_at <= now:
            self.store.save_onboarding_session(
                phone_number=sender_phone,
                state="choose_role",
                status="expired",
                data=dict(session.data),
                expires_at=now,
                completion_note="session_expired",
            )
            session = None
            expired = True

        if session is None or session.status != "active":
            self._save_session(sender_phone, state="choose_role", status="active", data={})
            prefix = "Previous onboarding session expired. " if expired else "Welcome to CareOS Lite onboarding. "
            return prefix + self._role_prompt()

        text = body.strip()
        normalized = text.lower()
        data = dict(session.data)

        if session.state == "choose_role":
            if normalized in {"myself", "1"}:
                self._save_session(sender_phone, state="self_patient_name", status="active", data={"mode": "myself"})
                return "Please share patient full name."
            if normalized in {"someone i care for", "care", "caregiver", "2"}:
                self._save_session(
                    sender_phone,
                    state="caregiver_name",
                    status="active",
                    data={"mode": "someone_i_care_for"},
                )
                return "Please share your name."
            return self._role_prompt()

        if session.state == "self_patient_name":
            if not text:
                return "Please share patient full name."
            patient_name = self._clean_name(text)
            created = self._complete_self_onboarding(sender_phone, patient_name, identity)
            self._activate_setup_session(
                phone_number=sender_phone,
                participant_id=created["participant_id"],
                patient_id=created["patient_id"],
                source="self_onboarding_complete",
            )
            return f"Done. Profile created for {patient_name}.\n{self._setup_menu_prompt()}"

        if session.state == "caregiver_name":
            if not text:
                return "Please share your name."
            data["caregiver_name"] = self._clean_name(text)
            self._save_session(sender_phone, state="caregiver_patient_name", status="active", data=data)
            return "Please share patient full name."

        if session.state == "caregiver_patient_name":
            if not text:
                return "Please share patient full name."
            data["patient_name"] = self._clean_name(text)
            self._save_session(sender_phone, state="caregiver_patient_phone", status="active", data=data)
            return "Please share patient WhatsApp number (example: +919999999999)."

        if session.state == "caregiver_patient_phone":
            patient_phone = self._normalize_phone_input(text)
            if patient_phone is None:
                return "Invalid phone format. Reply with +countrycode number, e.g. +919999999999."
            data["patient_phone"] = patient_phone
            self._save_session(sender_phone, state="caregiver_relationship", status="active", data=data)
            return "Relationship to patient? (example: spouse, son, daughter, caregiver)"

        if session.state == "caregiver_relationship":
            if not text:
                return "Please share relationship to patient."
            data["relationship"] = text.strip()[:40]
            pending = self._start_caregiver_verification(sender_phone, data, identity)
            if pending is None:
                self._save_session(
                    sender_phone,
                    state="verification_failed",
                    status="completed",
                    data=data,
                    completion_note="verification_start_failed",
                )
                return "Could not start verification for this patient phone. Reply 'hi' to restart onboarding."

            data["verification_request_id"] = pending.id
            self._save_session(sender_phone, state="verification_pending", status="active", data=data, completion_note="")
            return self._caregiver_waiting_prompt(pending)

        if session.state == "verification_pending":
            request_id = str(data.get("verification_request_id") or "")
            request = self.store.get_verification_request(request_id) if request_id else None
            if request is None:
                self._save_session(
                    sender_phone,
                    state="verification_failed",
                    status="completed",
                    data=data,
                    completion_note="verification_request_missing",
                )
                return "Verification request not found. Reply 'hi' to restart onboarding."
            return self._handle_caregiver_pending(sender_phone=sender_phone, body=body, request=request)

        if session.state == "patient_invite_caregiver_phone":
            caregiver_phone = self._normalize_phone_input(text)
            if caregiver_phone is None:
                return "Invalid phone format. Reply with +countrycode number, e.g. +919999999999."
            data["invite_caregiver_phone"] = caregiver_phone
            self._save_session(sender_phone, state="patient_invite_preset", status="active", data=data)
            return "Choose caregiver preset: 1) primary caregiver 2) observer"

        if session.state == "patient_invite_preset":
            preset = self._parse_caregiver_preset(text)
            if preset is None:
                return "Choose caregiver preset: 1) primary caregiver 2) observer"
            data["invite_caregiver_preset"] = preset
            invite_request, error_text = self._start_patient_initiated_caregiver_invite(
                sender_phone=sender_phone,
                identity=identity,
                data=data,
            )
            if invite_request is None:
                self._save_session(
                    sender_phone,
                    state="completed",
                    status="completed",
                    data=data,
                    completion_note="patient_invite_failed",
                )
                return error_text or "Could not start caregiver invite right now."
            self._save_session(
                sender_phone,
                state="completed",
                status="completed",
                data={
                    "invite_request_id": invite_request.id,
                    "invite_caregiver_phone": invite_request.caregiver_phone_number,
                    "invite_caregiver_preset": preset,
                },
                completion_note="patient_invite_created",
            )
            preset_text = "observer" if preset == "observer" else "primary caregiver"
            return (
                f"Invite sent to {invite_request.caregiver_phone_number} as {preset_text}. "
                f"They can reply APPROVE {invite_request.approval_code} or DECLINE {invite_request.approval_code}."
            )

        if session.state in {"completed", "verification_failed"}:
            return "Onboarding already completed. Reply 'schedule' or 'help'."

        self._save_session(sender_phone, state="choose_role", status="active", data={})
        return self._role_prompt()

    def _handle_setup_message(self, *, sender_phone: str, body: str, identity: ParticipantIdentity, session_data: dict) -> str:
        text = body.strip()
        normalized = text.lower()

        if normalized in {"cancel setup", "cancel wizard"}:
            self._save_session(
                sender_phone,
                state="completed",
                status="completed",
                data=session_data,
                completion_note="setup_cancelled",
            )
            return "Okay, I cancelled setup. Reply 'add a medication', 'add an appointment', or 'add a routine' to start again."

        if normalized in {"restart setup", "setup menu", "menu"}:
            session_data["setup_state"] = "menu"
            session_data.pop("setup_type", None)
            session_data.pop("setup_draft", None)
            self._save_session(sender_phone, state="setup_menu", status="active", data=session_data)
            return self._setup_menu_prompt()

        if normalized in {"finish", "finish for now", "4"} and session_data.get("setup_state", "menu") == "menu":
            self._save_session(
                sender_phone,
                state="completed",
                status="completed",
                data=session_data,
                completion_note="setup_finished",
            )
            return "Setup saved. You can now use: schedule, next, status."

        setup_state = str(session_data.get("setup_state") or "menu")
        draft = dict(session_data.get("setup_draft") or {})

        if setup_state == "menu":
            if normalized in {"menu", "0"}:
                return self._setup_menu_prompt()
            if normalized in {"1", "add medications", "medication", "medications"}:
                session_data["setup_type"] = "medication"
                session_data["setup_state"] = "med_name"
                session_data["setup_draft"] = {}
                self._save_session(sender_phone, state="setup_wizard", status="active", data=session_data)
                return "Medication name?"
            if normalized in {"2", "add appointments", "appointment", "appointments"}:
                session_data["setup_type"] = "appointment"
                session_data["setup_state"] = "appt_title"
                session_data["setup_draft"] = {}
                self._save_session(sender_phone, state="setup_wizard", status="active", data=session_data)
                return "Appointment title?"
            if normalized in {"3", "add routines", "routine", "routines"}:
                session_data["setup_type"] = "routine"
                session_data["setup_state"] = "routine_category"
                session_data["setup_draft"] = {}
                self._save_session(sender_phone, state="setup_wizard", status="active", data=session_data)
                return "Routine category: 1) meal 2) movement 3) sleep 4) therapy"
            return self._setup_menu_prompt()

        if session_data.get("setup_type") == "medication":
            return self._handle_medication_setup(sender_phone, text, normalized, identity, session_data, draft)
        if session_data.get("setup_type") == "appointment":
            return self._handle_appointment_setup(sender_phone, text, normalized, identity, session_data, draft)
        if session_data.get("setup_type") == "routine":
            return self._handle_routine_setup(sender_phone, text, normalized, identity, session_data, draft)

        session_data["setup_state"] = "menu"
        session_data.pop("setup_type", None)
        session_data.pop("setup_draft", None)
        self._save_session(sender_phone, state="setup_menu", status="active", data=session_data)
        return self._setup_menu_prompt()

    def _handle_existing_user_invite_management(self, *, sender_phone: str, body: str, invite_target: dict) -> str | None:
        if self._is_patient_invite_list_trigger(body):
            return self._patient_invite_list_prompt(sender_phone=sender_phone, patient_id=str(invite_target["invite_patient_id"]))
        cancel_reference = self._parse_patient_invite_cancel_command(body)
        if cancel_reference is not None:
            return self._cancel_patient_invite(
                sender_phone=sender_phone,
                patient_id=str(invite_target["invite_patient_id"]),
                reference=cancel_reference,
            )
        return None

    def _handle_medication_setup(
        self,
        sender_phone: str,
        text: str,
        normalized: str,
        identity: ParticipantIdentity,
        session_data: dict,
        draft: dict,
    ) -> str:
        state = str(session_data.get("setup_state") or "")

        if state == "med_name":
            draft["title"] = self._clean_name(text)
            session_data["setup_state"] = "med_time"
            session_data["setup_draft"] = draft
            self._save_session(sender_phone, state="setup_wizard", status="active", data=session_data)
            return "Medication timing? Use HH:MM (24h)."

        if state == "med_time":
            parsed = self._parse_time(text)
            if parsed is None:
                return "Invalid time. Use HH:MM (24h), e.g. 08:00"
            draft["time"] = parsed
            session_data["setup_state"] = "med_instructions"
            session_data["setup_draft"] = draft
            self._save_session(sender_phone, state="setup_wizard", status="active", data=session_data)
            return "Instructions? (or reply 'skip')"

        if state == "med_instructions":
            draft["instructions"] = "Take as prescribed" if normalized == "skip" else text.strip()[:200]
            session_data["setup_state"] = "med_why"
            session_data["setup_draft"] = draft
            self._save_session(sender_phone, state="setup_wizard", status="active", data=session_data)
            return "Why it matters? (or reply 'skip')"

        if state == "med_why":
            draft["why"] = "" if normalized == "skip" else text.strip()[:200]
            try:
                result = self._create_medication_item(identity, session_data, draft)
            except ValueError:
                result = "Could not resolve setup target patient. Reply 'patients' then try setup again."
            session_data["setup_state"] = "menu"
            session_data.pop("setup_type", None)
            session_data.pop("setup_draft", None)
            self._save_session(sender_phone, state="setup_menu", status="active", data=session_data)
            return f"{result}\n{self._setup_menu_prompt()}"

        session_data["setup_state"] = "menu"
        self._save_session(sender_phone, state="setup_menu", status="active", data=session_data)
        return self._setup_menu_prompt()

    def _handle_appointment_setup(
        self,
        sender_phone: str,
        text: str,
        _normalized: str,
        identity: ParticipantIdentity,
        session_data: dict,
        draft: dict,
    ) -> str:
        state = str(session_data.get("setup_state") or "")

        if state == "appt_title":
            draft["title"] = self._clean_name(text)
            session_data["setup_state"] = "appt_date"
            session_data["setup_draft"] = draft
            self._save_session(sender_phone, state="setup_wizard", status="active", data=session_data)
            return "Appointment date? Use YYYY-MM-DD"

        if state == "appt_date":
            parsed_date = self._parse_date(text)
            if parsed_date is None:
                return "Invalid date. Use YYYY-MM-DD"
            draft["date"] = parsed_date
            session_data["setup_state"] = "appt_time"
            session_data["setup_draft"] = draft
            self._save_session(sender_phone, state="setup_wizard", status="active", data=session_data)
            return "Appointment time? Use HH:MM (24h)."

        if state == "appt_time":
            parsed_time = self._parse_time(text)
            if parsed_time is None:
                return "Invalid time. Use HH:MM (24h), e.g. 14:30"
            draft["time"] = parsed_time
            try:
                result = self._create_appointment_item(identity, session_data, draft)
            except ValueError:
                result = "Could not resolve setup target patient. Reply 'patients' then try setup again."
            session_data["setup_state"] = "menu"
            session_data.pop("setup_type", None)
            session_data.pop("setup_draft", None)
            self._save_session(sender_phone, state="setup_menu", status="active", data=session_data)
            return f"{result}\n{self._setup_menu_prompt()}"

        session_data["setup_state"] = "menu"
        self._save_session(sender_phone, state="setup_menu", status="active", data=session_data)
        return self._setup_menu_prompt()

    def _handle_routine_setup(
        self,
        sender_phone: str,
        text: str,
        normalized: str,
        identity: ParticipantIdentity,
        session_data: dict,
        draft: dict,
    ) -> str:
        state = str(session_data.get("setup_state") or "")

        if state == "routine_category":
            mapping = {
                "1": "meal",
                "2": "movement",
                "3": "sleep",
                "4": "therapy",
                "meal": "meal",
                "movement": "movement",
                "sleep": "sleep",
                "therapy": "therapy",
            }
            category = mapping.get(normalized)
            if category is None:
                return "Pick category: 1) meal 2) movement 3) sleep 4) therapy"
            draft["category"] = category
            session_data["setup_state"] = "routine_timing"
            session_data["setup_draft"] = draft
            self._save_session(sender_phone, state="setup_wizard", status="active", data=session_data)
            return "Timing/window? HH:MM or HH:MM-HH:MM"

        if state == "routine_timing":
            parsed = self._parse_time_or_window(text)
            if parsed is None:
                return "Invalid format. Use HH:MM or HH:MM-HH:MM"
            draft.update(parsed)
            session_data["setup_state"] = "routine_instructions"
            session_data["setup_draft"] = draft
            self._save_session(sender_phone, state="setup_wizard", status="active", data=session_data)
            return "Instructions? (or reply 'skip')"

        if state == "routine_instructions":
            draft["instructions"] = "" if normalized == "skip" else text.strip()[:200]
            try:
                result = self._create_routine_item(identity, session_data, draft)
            except ValueError:
                result = "Could not resolve setup target patient. Reply 'patients' then try setup again."
            session_data["setup_state"] = "menu"
            session_data.pop("setup_type", None)
            session_data.pop("setup_draft", None)
            self._save_session(sender_phone, state="setup_menu", status="active", data=session_data)
            return f"{result}\n{self._setup_menu_prompt()}"

        session_data["setup_state"] = "menu"
        self._save_session(sender_phone, state="setup_menu", status="active", data=session_data)
        return self._setup_menu_prompt()

    def _create_medication_item(self, identity: ParticipantIdentity, session_data: dict, draft: dict) -> str:
        patient_id, participant_id = self._resolve_setup_target(identity, session_data)
        care_plan_id = self._ensure_active_care_plan(patient_id, participant_id)
        start_utc = self._next_local_time_utc(patient_id, str(draft["time"]))
        end_utc = start_utc + timedelta(minutes=30)

        payload = AddWinsRequest(
            patient_id=patient_id,
            definitions=[
                WinDefinitionCreate(
                    category="medication",
                    title=str(draft["title"]),
                    instructions=str(draft.get("instructions") or "Take as prescribed"),
                    why_it_matters=str(draft.get("why") or ""),
                    criticality=Criticality.HIGH,
                    flexibility=Flexibility.RIGID,
                    recurrence_type=RecurrenceType.DAILY,
                    recurrence_interval=1,
                    recurrence_days_of_week=[],
                    recurrence_until=None,
                    temporary_start=None,
                    temporary_end=None,
                    default_channel_policy={"channel": "whatsapp"},
                    escalation_policy={"caregiver_notify": "true"},
                )
            ],
            instances=[WinInstanceCreate(scheduled_start=start_utc, scheduled_end=end_utc)],
        )
        self.store.add_wins(care_plan_id, payload)
        return f"Medication added: {draft['title']} at {draft['time']}."

    def _create_appointment_item(self, identity: ParticipantIdentity, session_data: dict, draft: dict) -> str:
        patient_id, participant_id = self._resolve_setup_target(identity, session_data)
        care_plan_id = self._ensure_active_care_plan(patient_id, participant_id)
        start_utc = self._local_datetime_to_utc(patient_id, str(draft["date"]), str(draft["time"]))
        end_utc = start_utc + timedelta(hours=1)

        payload = AddWinsRequest(
            patient_id=patient_id,
            definitions=[
                WinDefinitionCreate(
                    category="appointment",
                    title=str(draft["title"]),
                    instructions="Attend appointment",
                    why_it_matters="",
                    criticality=Criticality.MEDIUM,
                    flexibility=Flexibility.WINDOWED,
                    recurrence_type=RecurrenceType.ONE_OFF,
                    recurrence_interval=1,
                    recurrence_days_of_week=[],
                    recurrence_until=None,
                    temporary_start=None,
                    temporary_end=None,
                    default_channel_policy={"channel": "whatsapp"},
                    escalation_policy={},
                )
            ],
            instances=[WinInstanceCreate(scheduled_start=start_utc, scheduled_end=end_utc)],
        )
        self.store.add_wins(care_plan_id, payload)
        return f"Appointment added: {draft['title']} on {draft['date']} {draft['time']}."

    def _create_routine_item(self, identity: ParticipantIdentity, session_data: dict, draft: dict) -> str:
        patient_id, participant_id = self._resolve_setup_target(identity, session_data)
        care_plan_id = self._ensure_active_care_plan(patient_id, participant_id)

        if "window_start" in draft and "window_end" in draft:
            start_utc = self._next_local_time_utc(patient_id, str(draft["window_start"]))
            end_utc = self._next_local_time_utc(patient_id, str(draft["window_end"]))
            if end_utc <= start_utc:
                end_utc = start_utc + timedelta(minutes=60)
            flexibility = Flexibility.WINDOWED
            timing_text = f"{draft['window_start']}-{draft['window_end']}"
        else:
            start_utc = self._next_local_time_utc(patient_id, str(draft["time"]))
            end_utc = start_utc + timedelta(minutes=30)
            flexibility = Flexibility.FLEXIBLE
            timing_text = str(draft["time"])

        category = str(draft["category"])
        payload = AddWinsRequest(
            patient_id=patient_id,
            definitions=[
                WinDefinitionCreate(
                    category=category,
                    title=f"{category.title()} routine",
                    instructions=str(draft.get("instructions") or ""),
                    why_it_matters="",
                    criticality=Criticality.LOW,
                    flexibility=flexibility,
                    recurrence_type=RecurrenceType.DAILY,
                    recurrence_interval=1,
                    recurrence_days_of_week=[],
                    recurrence_until=None,
                    temporary_start=None,
                    temporary_end=None,
                    default_channel_policy={"channel": "whatsapp"},
                    escalation_policy={},
                )
            ],
            instances=[WinInstanceCreate(scheduled_start=start_utc, scheduled_end=end_utc)],
        )
        self.store.add_wins(care_plan_id, payload)
        return f"Routine added: {category} at {timing_text}."

    def _resolve_setup_target(self, identity: ParticipantIdentity, session_data: dict) -> tuple[str, str]:
        patient_id = str(session_data.get("setup_patient_id") or "")
        participant_id = str(session_data.get("setup_participant_id") or identity.participant_id)

        if not patient_id:
            active = self.store.get_active_patient_context(identity.participant_id)
            if active:
                patient_id = active
            else:
                linked = self.store.list_linked_patients(identity.participant_id)
                if len(linked) == 1:
                    patient_id = linked[0].patient_id

        if not patient_id:
            raise ValueError("setup target patient not found")
        return patient_id, participant_id

    def _ensure_active_care_plan(self, patient_id: str, participant_id: str) -> str:
        existing = self.store.get_active_care_plan_for_patient(patient_id)
        if existing is not None:
            return str(existing["id"])
        created = self.store.create_care_plan(
            CarePlanCreate(
                patient_id=patient_id,
                created_by_participant_id=participant_id,
                status="active",
                version=1,
                source_type="manual",
            )
        )
        return str(created["id"])

    def _next_local_time_utc(self, patient_id: str, hhmm: str) -> datetime:
        profile = self.store.get_patient_profile(patient_id) or {"timezone": settings.default_timezone}
        tz = ZoneInfo(str(profile.get("timezone") or settings.default_timezone))
        now_local = datetime.now(UTC).astimezone(tz)
        hour, minute = [int(piece) for piece in hhmm.split(":", 1)]
        candidate = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now_local:
            candidate = candidate + timedelta(days=1)
        return candidate.astimezone(UTC)

    def _local_datetime_to_utc(self, patient_id: str, yyyy_mm_dd: str, hhmm: str) -> datetime:
        profile = self.store.get_patient_profile(patient_id) or {"timezone": settings.default_timezone}
        tz = ZoneInfo(str(profile.get("timezone") or settings.default_timezone))
        day = datetime.fromisoformat(yyyy_mm_dd).date()
        hour, minute = [int(piece) for piece in hhmm.split(":", 1)]
        local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
        return local.astimezone(UTC)

    def _handle_verification_message(self, *, sender_phone: str, body: str) -> str | None:
        command, code = self._parse_verification_reply(body)
        patient_requests = [
            request
            for request in self.store.list_pending_verifications_for_patient_phone(sender_phone)
            if not self._is_patient_initiated_invite_request(request)
        ]
        caregiver_requests = self.store.list_pending_verifications_for_caregiver_phone(sender_phone)
        if not patient_requests and not caregiver_requests:
            if command in {"approve", "decline"}:
                return "No pending caregiver approval request for this number."
            return None

        if patient_requests and caregiver_requests:
            return "Multiple approval requests pending. Reply APPROVE <code> or DECLINE <code>."

        if command is None:
            requests = patient_requests or caregiver_requests
            if len(requests) == 1:
                req = requests[0]
                subject = req.patient_name if patient_requests else req.patient_name
                return (
                    f"Caregiver approval pending for {subject}. "
                    f"Reply APPROVE {req.approval_code} or DECLINE {req.approval_code}."
                )
            return "Multiple approval requests pending. Reply APPROVE <code> or DECLINE <code>."

        requests = patient_requests if patient_requests else caregiver_requests
        resolution_actor = "patient" if patient_requests else "caregiver"
        chosen = self._choose_verification_request(requests, code)
        if chosen is None:
            return "Invalid approval code. Reply APPROVE <code> or DECLINE <code>."

        if command == "approve":
            caregiver_preset = self._caregiver_preset_for_relationship(chosen.relationship)
            self.store.update_verification_request(
                chosen.id,
                status="approved",
                resolved_at=datetime.now(UTC),
                resolution_note=f"approved_by_{resolution_actor}",
            )
            self.store.link_caregiver(chosen.caregiver_participant_id, chosen.patient_id, preset=caregiver_preset)
            self.store.link_caregiver(chosen.patient_participant_id, chosen.patient_id)
            self.store.set_active_patient_context(chosen.caregiver_participant_id, chosen.patient_id, "verification_approved")
            self._activate_setup_session(
                phone_number=chosen.caregiver_phone_number,
                participant_id=chosen.caregiver_participant_id,
                patient_id=chosen.patient_id,
                source="verification_approved",
            )
            if patient_requests:
                caregiver_msg = (
                    f"Approved by {chosen.patient_name}. Caregiver access is now active.\n"
                    + self._setup_menu_prompt()
                )
                self._send_whatsapp_by_phone(chosen.caregiver_phone_number, caregiver_msg)
                return "Approved. Caregiver has been informed."

            self._send_whatsapp_by_phone(
                chosen.patient_phone_number,
                (
                    f"{chosen.caregiver_phone_number} accepted caregiver access for {chosen.patient_name} "
                    f"as {caregiver_preset.replace('_', ' ')}."
                ),
            )
            return f"Approved. Caregiver access for {chosen.patient_name} is now active.\n{self._setup_menu_prompt()}"

        self.store.update_verification_request(
            chosen.id,
            status="declined",
            resolved_at=datetime.now(UTC),
            resolution_note=f"declined_by_{resolution_actor}",
        )
        if patient_requests:
            self.store.save_onboarding_session(
                phone_number=chosen.caregiver_phone_number,
                state="completed",
                status="completed",
                data={"verification_request_id": chosen.id},
                expires_at=datetime.now(UTC) + timedelta(hours=max(int(settings.onboarding_session_ttl_hours), 1)),
                completion_note="verification_declined",
            )
            caregiver_msg = f"Declined by {chosen.patient_name}. No caregiver link was created."
            self._send_whatsapp_by_phone(chosen.caregiver_phone_number, caregiver_msg)
            return "Declined. Caregiver has been informed."

        self._send_whatsapp_by_phone(
            chosen.patient_phone_number,
            f"{chosen.caregiver_phone_number} declined caregiver access for {chosen.patient_name}.",
        )
        return "Declined. No caregiver link was created."

    def _patient_invite_list_prompt(self, *, sender_phone: str, patient_id: str) -> str:
        pending = self._pending_patient_invites(sender_phone=sender_phone, patient_id=patient_id)
        if not pending:
            return "No pending caregiver invites for the active patient."
        lines = ["Pending caregiver invites:"]
        for request in pending:
            preset = self._caregiver_preset_for_relationship(request.relationship).replace("_", " ")
            lines.append(f"- {request.caregiver_phone_number} as {preset} (code {request.approval_code})")
        lines.append("Reply `cancel invite <code>` to revoke one.")
        return "\n".join(lines)

    def _cancel_patient_invite(self, *, sender_phone: str, patient_id: str, reference: str) -> str:
        pending = self._pending_patient_invites(sender_phone=sender_phone, patient_id=patient_id)
        if not pending:
            return "No pending caregiver invites for the active patient."
        chosen = self._choose_patient_invite_request(pending, reference)
        if chosen is None:
            return "Reply `cancel invite <code>` using one of the pending invite codes."
        self.store.update_verification_request(
            chosen.id,
            status="canceled",
            resolved_at=datetime.now(UTC),
            resolution_note="canceled_by_patient",
        )
        self._send_whatsapp_by_phone(
            chosen.caregiver_phone_number,
            f"CareOS invite cancelled by {chosen.patient_name}. No caregiver link was created.",
        )
        return f"Cancelled invite for {chosen.caregiver_phone_number}."

    def _pending_patient_invites(self, *, sender_phone: str, patient_id: str) -> list[CaregiverVerificationRequest]:
        return [
            request
            for request in self.store.list_pending_verifications_for_patient_phone(sender_phone)
            if str(request.patient_id) == patient_id
        ]

    def _choose_patient_invite_request(
        self,
        requests: list[CaregiverVerificationRequest],
        reference: str,
    ) -> CaregiverVerificationRequest | None:
        normalized = reference.strip()
        if not normalized:
            return requests[0] if len(requests) == 1 else None
        normalized_phone = self._normalize_phone_input(normalized)
        for request in requests:
            if normalized.lower() == request.approval_code.lower():
                return request
            if normalized.lower() == request.caregiver_phone_number.lower():
                return request
            if normalized_phone is not None and normalized_phone == request.caregiver_phone_number:
                return request
        return None

    def _handle_caregiver_pending(self, *, sender_phone: str, body: str, request: CaregiverVerificationRequest) -> str:
        now = datetime.now(UTC)
        if request.status != "pending":
            if request.status == "approved":
                return "Approved. You can now continue setup."
            if request.status == "declined":
                return "Declined by patient. No link was created."
            if request.status == "canceled":
                return "Verification request was canceled. Reply 'hi' to start again."
            if request.status == "expired":
                return "Verification request expired. Reply 'hi' to restart onboarding."

        if request.expires_at <= now:
            self.store.update_verification_request(
                request.id,
                status="expired",
                resolved_at=now,
                resolution_note="expired",
            )
            return "Verification request expired. Reply 'hi' to restart onboarding."

        normalized = body.strip().lower()
        if normalized in {"status", "verification", "pending"}:
            return self._caregiver_waiting_prompt(request)

        if normalized == "cancel":
            self.store.update_verification_request(
                request.id,
                status="canceled",
                resolved_at=now,
                resolution_note="canceled_by_caregiver",
            )
            self.store.save_onboarding_session(
                phone_number=sender_phone,
                state="completed",
                status="completed",
                data={"verification_request_id": request.id},
                expires_at=now + timedelta(hours=max(int(settings.onboarding_session_ttl_hours), 1)),
                completion_note="verification_canceled",
            )
            return "Verification canceled. No caregiver link was created."

        if normalized == "resend":
            sent = self._send_verification_prompt(request)
            status_text = "sent" if sent else "queued"
            updated = self.store.update_verification_request(
                request.id,
                send_attempt_count=request.send_attempt_count + 1,
                last_sent_at=now,
                resolution_note=f"resent_{status_text}",
            )
            return f"Verification {status_text} to {updated.patient_phone_number}. Reply STATUS, RESEND, or CANCEL."

        return self._caregiver_waiting_prompt(request)

    def _complete_self_onboarding(
        self,
        sender_phone: str,
        patient_name: str,
        identity: ParticipantIdentity | None,
    ) -> dict:
        participant_record = self.store.find_participant_record_by_phone(sender_phone)
        tenant_id: str
        participant_id: str

        if identity is not None and participant_record is not None:
            tenant_id = identity.tenant_id
            participant_id = participant_record["id"]
            self.store.ensure_identity_membership_for_participant(participant_id)
        else:
            tenant = self.store.create_tenant(
                TenantCreate(
                    name=f"{patient_name} Family",
                    type="family",
                    timezone=settings.default_timezone,
                    status="active",
                )
            )
            tenant_id = str(tenant["id"])
            participant = self.store.create_participant(
                ParticipantCreate(
                    tenant_id=tenant_id,
                    role=Role.PATIENT,
                    display_name=patient_name,
                    phone_number=self._normalize_phone_input(sender_phone) or sender_phone,
                    preferred_channel="whatsapp",
                    preferred_language="en",
                    active=True,
                )
            )
            participant_id = str(participant["id"])
            self.store.ensure_identity_membership_for_participant(participant_id)

        patient = self.store.create_patient(
            PatientCreate(
                tenant_id=tenant_id,
                display_name=patient_name,
                timezone=settings.default_timezone,
                primary_language="en",
                persona_type=PersonaType.CAREGIVER_MANAGED_ELDER,
                risk_level="medium",
                status="active",
            )
        )
        patient_id = str(patient["id"])
        self.store.link_caregiver(participant_id, patient_id)
        self.store.set_active_patient_context(participant_id, patient_id, "onboarding_self")
        return {"participant_id": participant_id, "patient_id": patient_id}

    def _start_caregiver_verification(
        self,
        sender_phone: str,
        data: dict,
        identity: ParticipantIdentity | None,
    ) -> CaregiverVerificationRequest | None:
        caregiver_name = str(data.get("caregiver_name") or "Caregiver")
        patient_name = str(data.get("patient_name") or "Patient")
        patient_phone = str(data.get("patient_phone") or "")
        relationship = str(data.get("relationship") or "family")

        sender_participant = self.store.find_participant_record_by_phone(sender_phone)
        if identity is not None and sender_participant is not None:
            tenant_id = identity.tenant_id
            caregiver_participant_id = str(sender_participant["id"])
            self.store.ensure_identity_membership_for_participant(caregiver_participant_id)
        else:
            tenant = self.store.create_tenant(
                TenantCreate(
                    name=f"{patient_name} Family",
                    type="family",
                    timezone=settings.default_timezone,
                    status="active",
                )
            )
            tenant_id = str(tenant["id"])
            caregiver = self.store.create_participant(
                ParticipantCreate(
                    tenant_id=tenant_id,
                    role=Role.CAREGIVER,
                    display_name=caregiver_name,
                    phone_number=self._normalize_phone_input(sender_phone) or sender_phone,
                    preferred_channel="whatsapp",
                    preferred_language="en",
                    active=True,
                )
            )
            caregiver_participant_id = str(caregiver["id"])
            self.store.ensure_identity_membership_for_participant(caregiver_participant_id)

        existing_pending = self.store.get_pending_verification_for_caregiver(caregiver_participant_id)
        if existing_pending is not None:
            return existing_pending

        patient = self.store.create_patient(
            PatientCreate(
                tenant_id=tenant_id,
                display_name=patient_name,
                timezone=settings.default_timezone,
                primary_language="en",
                persona_type=PersonaType.CAREGIVER_MANAGED_ELDER,
                risk_level="medium",
                status="active",
            )
        )
        patient_id = str(patient["id"])

        existing_patient_participant = self.store.find_participant_record_by_phone(patient_phone)
        if existing_patient_participant is not None and str(existing_patient_participant["tenant_id"]) != tenant_id:
            return None

        if existing_patient_participant is not None:
            patient_participant_id = str(existing_patient_participant["id"])
            self.store.ensure_identity_membership_for_participant(patient_participant_id)
        else:
            patient_participant = self.store.create_participant(
                ParticipantCreate(
                    tenant_id=tenant_id,
                    role=Role.PATIENT,
                    display_name=patient_name,
                    phone_number=patient_phone,
                    preferred_channel="whatsapp",
                    preferred_language="en",
                    active=True,
                )
            )
            patient_participant_id = str(patient_participant["id"])
            self.store.ensure_identity_membership_for_participant(patient_participant_id)

        ttl_hours = max(int(settings.onboarding_verification_ttl_hours), 1)
        request = self.store.create_caregiver_verification_request(
            tenant_id=tenant_id,
            caregiver_participant_id=caregiver_participant_id,
            patient_id=patient_id,
            patient_participant_id=patient_participant_id,
            caregiver_name=caregiver_name,
            caregiver_phone_number=self._normalize_phone_input(sender_phone) or sender_phone,
            patient_name=patient_name,
            patient_phone_number=patient_phone,
            relationship=relationship,
            approval_code=self._approval_code(),
            expires_at=datetime.now(UTC) + timedelta(hours=ttl_hours),
        )
        sent = self._send_verification_prompt(request)
        now = datetime.now(UTC)
        self.store.update_verification_request(
            request.id,
            send_attempt_count=1,
            last_sent_at=now,
            resolution_note="initial_send_success" if sent else "initial_send_not_configured",
        )
        return self.store.get_verification_request(request.id)

    def _start_patient_initiated_caregiver_invite(
        self,
        *,
        sender_phone: str,
        identity: ParticipantIdentity | None,
        data: dict,
    ) -> tuple[CaregiverVerificationRequest | None, str | None]:
        if identity is None:
            return None, "Could not resolve patient identity for this invite."

        tenant_id = str(data.get("invite_tenant_id") or identity.tenant_id)
        patient_id = str(data.get("invite_patient_id") or "")
        patient_participant_id = str(data.get("invite_patient_participant_id") or identity.participant_id)
        patient_name = str(data.get("invite_patient_name") or "Patient")
        caregiver_phone = str(data.get("invite_caregiver_phone") or "")
        preset = str(data.get("invite_caregiver_preset") or "primary_caregiver")
        relationship = "observer" if preset == "observer" else "primary caregiver"
        normalized_sender = self._normalize_phone_input(sender_phone) or sender_phone

        if not patient_id or not caregiver_phone:
            return None, "Could not resolve the patient or caregiver phone for this invite."
        if self._normalize_phone_input(caregiver_phone) == normalized_sender:
            return None, "You are already linked to this patient. Invite a different caregiver number."
        self.store.ensure_identity_membership_for_participant(patient_participant_id)

        existing_caregiver = self.store.find_participant_record_by_phone(caregiver_phone)
        if existing_caregiver is not None and str(existing_caregiver["tenant_id"]) != tenant_id:
            self.store.ensure_identity_membership_for_participant(str(existing_caregiver["id"]))
            return (
                None,
                "That WhatsApp number already belongs to a different CareOS family workspace. "
                "Under the current model, one phone can only belong to one tenant. "
                "Use a different number or migrate that person into this family workspace first.",
            )

        caregiver_participant_id: str
        caregiver_name: str
        if existing_caregiver is not None:
            caregiver_participant_id = str(existing_caregiver["id"])
            caregiver_name = str(existing_caregiver.get("display_name") or "Caregiver")
            self.store.ensure_identity_membership_for_participant(caregiver_participant_id)
            if self.store.get_caregiver_link(caregiver_participant_id, patient_id) is not None:
                return None, f"{caregiver_phone} is already linked to {patient_name}."
            existing_pending = self.store.get_pending_verification_for_caregiver(caregiver_participant_id)
            if existing_pending is not None:
                return existing_pending, None
        else:
            caregiver = self.store.create_participant(
                ParticipantCreate(
                    tenant_id=tenant_id,
                    role=Role.CAREGIVER,
                    display_name="Invited Caregiver",
                    phone_number=caregiver_phone,
                    preferred_channel="whatsapp",
                    preferred_language="en",
                    active=True,
                )
            )
            caregiver_participant_id = str(caregiver["id"])
            caregiver_name = str(caregiver["display_name"])
            self.store.ensure_identity_membership_for_participant(caregiver_participant_id)

        ttl_hours = max(int(settings.onboarding_verification_ttl_hours), 1)
        request = self.store.create_caregiver_verification_request(
            tenant_id=tenant_id,
            caregiver_participant_id=caregiver_participant_id,
            patient_id=patient_id,
            patient_participant_id=patient_participant_id,
            caregiver_name=caregiver_name,
            caregiver_phone_number=caregiver_phone,
            patient_name=patient_name,
            patient_phone_number=normalized_sender,
            relationship=relationship,
            approval_code=self._approval_code(),
            expires_at=datetime.now(UTC) + timedelta(hours=ttl_hours),
        )
        sent = self._send_patient_initiated_invite_prompt(request)
        now = datetime.now(UTC)
        self.store.update_verification_request(
            request.id,
            send_attempt_count=1,
            last_sent_at=now,
            resolution_note="invite_sent" if sent else "invite_not_configured",
        )
        return self.store.get_verification_request(request.id), None

    def _send_verification_prompt(self, request: CaregiverVerificationRequest) -> bool:
        body = (
            f"CareOS request: {request.caregiver_name} asks caregiver access for {request.patient_name}. "
            f"Reply APPROVE {request.approval_code} or DECLINE {request.approval_code}."
        )
        return self._send_whatsapp_by_phone(request.patient_phone_number, body)

    def _send_patient_initiated_invite_prompt(self, request: CaregiverVerificationRequest) -> bool:
        preset = self._caregiver_preset_for_relationship(request.relationship).replace("_", " ")
        body = (
            f"CareOS invite: {request.patient_name} invited you as {preset}. "
            f"Reply APPROVE {request.approval_code} or DECLINE {request.approval_code}."
        )
        return self._send_whatsapp_by_phone(request.caregiver_phone_number, body)

    def _send_whatsapp_by_phone(self, phone_number: str, body: str) -> bool:
        if not settings.twilio_account_sid or not settings.twilio_auth_token or not settings.twilio_whatsapp_number:
            return False
        try:
            sender = TwilioWhatsAppSender(
                account_sid=settings.twilio_account_sid,
                auth_token=settings.twilio_auth_token,
                from_number=settings.twilio_whatsapp_number,
            )
            sender.send_text(to_number=phone_number, body=body)
            return True
        except Exception:
            return False

    def _activate_setup_session(self, *, phone_number: str, participant_id: str, patient_id: str, source: str) -> None:
        self.store.save_onboarding_session(
            phone_number=phone_number,
            state="setup_menu",
            status="active",
            data={
                "setup_state": "menu",
                "setup_patient_id": patient_id,
                "setup_participant_id": participant_id,
                "setup_source": source,
            },
            expires_at=datetime.now(UTC) + timedelta(hours=max(int(settings.onboarding_session_ttl_hours), 1)),
            completion_note="",
        )

    def _choose_verification_request(
        self, requests: list[CaregiverVerificationRequest], code: str | None
    ) -> CaregiverVerificationRequest | None:
        if code:
            for request in requests:
                if request.approval_code.lower() == code.lower():
                    return request
            return None
        if len(requests) == 1:
            return requests[0]
        return None

    def _parse_verification_reply(self, body: str) -> tuple[str | None, str | None]:
        parts = body.strip().split()
        if not parts:
            return None, None
        cmd = parts[0].lower()
        if cmd == "accept":
            cmd = "approve"
        elif cmd == "reject":
            cmd = "decline"
        if cmd not in {"approve", "decline"}:
            return None, None
        code = parts[1].strip() if len(parts) > 1 else None
        return cmd, code

    def _is_patient_initiated_invite_request(self, request: CaregiverVerificationRequest) -> bool:
        return str(request.resolution_note or "").startswith("invite_")

    def _parse_caregiver_preset(self, body: str) -> str | None:
        normalized = " ".join(body.strip().lower().split())
        if normalized in {"1", "primary", "primary caregiver", "full caregiver"}:
            return "primary_caregiver"
        if normalized in {"2", "observer", "updates only", "family observer"}:
            return "observer"
        return None

    def _resolve_existing_user_patient_target(self, identity: ParticipantIdentity) -> dict | None:
        patient_id = self.store.get_active_patient_context(identity.participant_id)
        if patient_id is None:
            linked = self.store.list_linked_patients(identity.participant_id)
            if len(linked) == 1:
                patient_id = linked[0].patient_id
        if patient_id is None:
            return None

        profile = self.store.get_patient_profile(patient_id)
        if profile is None:
            return None

        return {
            "invite_patient_id": patient_id,
            "invite_patient_name": str(profile.get("display_name") or patient_id),
            "invite_tenant_id": str(profile.get("tenant_id") or identity.tenant_id),
            "invite_patient_participant_id": identity.participant_id,
        }

    def _approval_code(self) -> str:
        return uuid4().hex[:6].upper()

    def _setup_menu_prompt(self) -> str:
        return (
            "Care setup menu:\n"
            "1) add medications\n"
            "2) add appointments\n"
            "3) add routines\n"
            "4) finish for now\n"
            "Reply 1-4"
        )

    def _caregiver_waiting_prompt(self, request: CaregiverVerificationRequest) -> str:
        return (
            f"Verification pending for {request.patient_name} ({request.patient_phone_number}). "
            "Reply STATUS, RESEND, or CANCEL."
        )

    def _save_session(
        self,
        phone_number: str,
        *,
        state: str,
        status: str,
        data: dict,
        completion_note: str = "",
    ) -> None:
        ttl_hours = max(int(settings.onboarding_session_ttl_hours), 1)
        self.store.save_onboarding_session(
            phone_number=phone_number,
            state=state,
            status=status,
            data=data,
            expires_at=datetime.now(UTC) + timedelta(hours=ttl_hours),
            completion_note=completion_note,
        )

    def _role_prompt(self) -> str:
        return (
            "Are you onboarding for:\n"
            "1) myself\n"
            "2) someone I care for\n"
            "Reply: myself or someone I care for"
        )

    def _normalize_phone_input(self, raw_phone: str) -> str | None:
        phone = raw_phone.strip()
        if phone.lower().startswith("whatsapp:"):
            phone = phone.split(":", 1)[1].strip()
        digits = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
        if not digits.startswith("+"):
            return None
        plain_digits = digits[1:]
        if not plain_digits.isdigit() or len(plain_digits) < 8:
            return None
        return f"whatsapp:{digits}"

    def _clean_name(self, raw_name: str) -> str:
        return " ".join(raw_name.strip().split())[:80]

    def _parse_time(self, value: str) -> str | None:
        text = value.strip()
        parts = text.split(":")
        if len(parts) != 2:
            return None
        if not all(part.isdigit() for part in parts):
            return None
        hour = int(parts[0])
        minute = int(parts[1])
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            return None
        return f"{hour:02d}:{minute:02d}"

    def _parse_date(self, value: str) -> str | None:
        text = value.strip()
        try:
            return datetime.fromisoformat(text).date().isoformat()
        except ValueError:
            return None

    def _parse_time_or_window(self, value: str) -> dict | None:
        text = value.strip()
        if "-" not in text:
            parsed = self._parse_time(text)
            if parsed is None:
                return None
            return {"time": parsed}

        left, right = [piece.strip() for piece in text.split("-", 1)]
        start = self._parse_time(left)
        end = self._parse_time(right)
        if start is None or end is None:
            return None
        return {"window_start": start, "window_end": end}
