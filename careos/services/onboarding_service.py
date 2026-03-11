from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from careos.db.repositories.store import Store
from careos.domain.enums.core import PersonaType, Role
from careos.domain.models.api import CaregiverVerificationRequest, ParticipantCreate, ParticipantIdentity, PatientCreate, TenantCreate
from careos.integrations.twilio.sender import TwilioWhatsAppSender
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
        verification_reply = self._handle_verification_message(sender_phone=sender_phone, body=body)
        if verification_reply is not None:
            return verification_reply

        if identity is not None and linked_patient_count > 0:
            return None

        if identity is not None and linked_patient_count == 0:
            pending = self.store.get_pending_verification_for_caregiver(identity.participant_id)
            if pending is not None:
                return self._handle_caregiver_pending(sender_phone=sender_phone, body=body, request=pending)

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
            self._save_session(
                sender_phone,
                state="verification_pending",
                status="active",
                data=data,
                completion_note="",
            )
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

        if session.state in {"completed", "handoff_pending", "verification_failed"}:
            return "Onboarding already completed. Reply 'schedule' or 'help'."

        self._save_session(sender_phone, state="choose_role", status="active", data={})
        return self._role_prompt()

    def _handle_verification_message(self, *, sender_phone: str, body: str) -> str | None:
        command, code = self._parse_verification_reply(body)
        requests = self.store.list_pending_verifications_for_patient_phone(sender_phone)
        if not requests:
            if command in {"approve", "decline"}:
                return "No pending caregiver approval request for this number."
            return None

        if command is None:
            if len(requests) == 1:
                req = requests[0]
                return (
                    f"Caregiver approval pending for {req.patient_name}. "
                    f"Reply APPROVE {req.approval_code} or DECLINE {req.approval_code}."
                )
            return "Multiple approval requests pending. Reply APPROVE <code> or DECLINE <code>."

        chosen = self._choose_verification_request(requests, code)
        if chosen is None:
            return "Invalid approval code. Reply APPROVE <code> or DECLINE <code>."

        if command == "approve":
            self.store.update_verification_request(
                chosen.id,
                status="approved",
                resolved_at=datetime.now(UTC),
                resolution_note="approved_by_patient",
            )
            self.store.link_caregiver(chosen.caregiver_participant_id, chosen.patient_id)
            self.store.link_caregiver(chosen.patient_participant_id, chosen.patient_id)
            self.store.set_active_patient_context(chosen.caregiver_participant_id, chosen.patient_id, "verification_approved")
            self.store.save_onboarding_session(
                phone_number=chosen.caregiver_phone_number,
                state="completed",
                status="completed",
                data={"verification_request_id": chosen.id},
                expires_at=datetime.now(UTC) + timedelta(hours=max(int(settings.onboarding_session_ttl_hours), 1)),
                completion_note="verification_approved",
            )
            caregiver_msg = (
                f"Approved by {chosen.patient_name}. Caregiver access is now active. "
                "Reply 'patients' to continue."
            )
            self._send_whatsapp_by_phone(chosen.caregiver_phone_number, caregiver_msg)
            return "Approved. Caregiver has been informed."

        self.store.update_verification_request(
            chosen.id,
            status="declined",
            resolved_at=datetime.now(UTC),
            resolution_note="declined_by_patient",
        )
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

    def _handle_caregiver_pending(self, *, sender_phone: str, body: str, request: CaregiverVerificationRequest) -> str:
        now = datetime.now(UTC)
        if request.status != "pending":
            if request.status == "approved":
                return "Approved. You can now use 'patients' and continue setup."
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
            return (
                f"Verification {status_text} to {updated.patient_phone_number}. "
                "Reply STATUS, RESEND, or CANCEL."
            )

        return self._caregiver_waiting_prompt(request)

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

    def _send_verification_prompt(self, request: CaregiverVerificationRequest) -> bool:
        body = (
            f"CareOS request: {request.caregiver_name} asks caregiver access for {request.patient_name}. "
            f"Reply APPROVE {request.approval_code} or DECLINE {request.approval_code}."
        )
        return self._send_whatsapp_by_phone(request.patient_phone_number, body)

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
        if cmd not in {"approve", "decline"}:
            return None, None
        code = parts[1].strip() if len(parts) > 1 else None
        return cmd, code

    def _approval_code(self) -> str:
        return uuid4().hex[:6].upper()

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
