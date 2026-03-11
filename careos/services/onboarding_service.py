from __future__ import annotations

from datetime import UTC, datetime, timedelta

from careos.db.repositories.store import Store
from careos.domain.enums.core import PersonaType, Role
from careos.domain.models.api import ParticipantCreate, ParticipantIdentity, PatientCreate, TenantCreate
from careos.settings import settings


class OnboardingService:
    def __init__(self, store: Store) -> None:
        self.store = store

    def maybe_handle_message(
        self,
        *,
        sender_phone: str,
        body: str,
        identity: ParticipantIdentity | None,
        linked_patient_count: int,
    ) -> str | None:
        if identity is not None and linked_patient_count > 0:
            return None

        now = datetime.now(UTC)
        session = self.store.get_onboarding_session(sender_phone)
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
            data["patient_name"] = patient_name
            self._complete_self_onboarding(sender_phone, patient_name, identity)
            self._save_session(
                sender_phone,
                state="completed",
                status="completed",
                data=data,
                completion_note="self_onboarding_complete",
            )
            return f"Done. Profile created for {patient_name}. Reply 'schedule' to see today."

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
            note = self._complete_caregiver_onboarding(sender_phone, data, identity)
            self._save_session(
                sender_phone,
                state="handoff_pending",
                status="handoff_pending",
                data=data,
                completion_note=note,
            )
            patient_name = data.get("patient_name", "the patient")
            return (
                f"Saved. {patient_name} is added. "
                "Handoff pending: ask patient to message CareOS from their WhatsApp."
            )

        if session.state in {"completed", "handoff_pending"}:
            return "Onboarding already completed. Reply 'schedule' or 'help'."

        self._save_session(sender_phone, state="choose_role", status="active", data={})
        return self._role_prompt()

    def _complete_self_onboarding(
        self,
        sender_phone: str,
        patient_name: str,
        identity: ParticipantIdentity | None,
    ) -> None:
        participant_record = self.store.find_participant_record_by_phone(sender_phone)
        tenant_id: str
        participant_id: str

        if identity is not None and participant_record is not None:
            tenant_id = identity.tenant_id
            participant_id = participant_record["id"]
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
        self.store.link_caregiver(participant_id, str(patient["id"]))
        self.store.set_active_patient_context(participant_id, str(patient["id"]), "onboarding_self")

    def _complete_caregiver_onboarding(
        self,
        sender_phone: str,
        data: dict,
        identity: ParticipantIdentity | None,
    ) -> str:
        caregiver_name = str(data.get("caregiver_name") or "Caregiver")
        patient_name = str(data.get("patient_name") or "Patient")
        patient_phone = str(data.get("patient_phone") or "")
        relationship = str(data.get("relationship") or "family")

        sender_participant = self.store.find_participant_record_by_phone(sender_phone)
        if identity is not None and sender_participant is not None:
            tenant_id = identity.tenant_id
            caregiver_participant_id = str(sender_participant["id"])
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
        self.store.link_caregiver(caregiver_participant_id, patient_id)
        self.store.set_active_patient_context(caregiver_participant_id, patient_id, "onboarding_caregiver")

        existing_patient_phone_participant = self.store.find_participant_record_by_phone(patient_phone)
        if existing_patient_phone_participant is None:
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
            self.store.link_caregiver(str(patient_participant["id"]), patient_id)
            return f"handoff_pending:{relationship}:auto_patient_participant_created"

        return f"handoff_pending:{relationship}:patient_phone_already_registered"

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
