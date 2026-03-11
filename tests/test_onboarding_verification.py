from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from careos.app_context import context
from careos.main import app
from careos.settings import settings


client = TestClient(app)


def _twilio(from_phone: str, body: str, sid: str) -> str:
    response = client.post(
        "/twilio/webhook",
        data={
            "From": from_phone,
            "To": "whatsapp:+14155238886",
            "Body": body,
            "MessageSid": sid,
        },
    )
    assert response.status_code == 200
    return response.text


def _run_caregiver_onboarding(caregiver_phone: str, patient_phone: str) -> str:
    _twilio(caregiver_phone, "hi", f"{caregiver_phone}-1")
    _twilio(caregiver_phone, "someone I care for", f"{caregiver_phone}-2")
    _twilio(caregiver_phone, "Caregiver One", f"{caregiver_phone}-3")
    _twilio(caregiver_phone, "Patient One", f"{caregiver_phone}-4")
    _twilio(caregiver_phone, patient_phone, f"{caregiver_phone}-5")
    done = _twilio(caregiver_phone, "spouse", f"{caregiver_phone}-6")
    assert "Verification pending" in done

    caregiver = context.store.find_participant_record_by_phone(caregiver_phone)
    assert caregiver is not None
    pending = context.store.get_pending_verification_for_caregiver(str(caregiver["id"]))
    assert pending is not None
    return pending.approval_code


def test_patient_approve_activates_caregiver_link() -> None:
    settings.validate_twilio_signature = False
    caregiver_phone = "whatsapp:+15557770001"
    patient_phone = "whatsapp:+15557770002"
    code = _run_caregiver_onboarding(caregiver_phone, patient_phone)

    approved = _twilio(patient_phone, f"APPROVE {code}", "SM-approve-1")
    assert "Approved" in approved

    caregiver = context.store.find_participant_record_by_phone(caregiver_phone)
    assert caregiver is not None
    linked = context.store.list_linked_patients(str(caregiver["id"]))
    assert len(linked) == 1

    duplicate = _twilio(patient_phone, f"APPROVE {code}", "SM-approve-2")
    assert "onboarding" in duplicate.lower() or "no" in duplicate.lower()


def test_patient_decline_keeps_link_inactive() -> None:
    settings.validate_twilio_signature = False
    caregiver_phone = "whatsapp:+15557770011"
    patient_phone = "whatsapp:+15557770012"
    code = _run_caregiver_onboarding(caregiver_phone, patient_phone)

    declined = _twilio(patient_phone, f"DECLINE {code}", "SM-decline-1")
    assert "Declined" in declined

    caregiver = context.store.find_participant_record_by_phone(caregiver_phone)
    assert caregiver is not None
    linked = context.store.list_linked_patients(str(caregiver["id"]))
    assert len(linked) == 0


def test_caregiver_resend_and_cancel_pending_verification() -> None:
    settings.validate_twilio_signature = False
    caregiver_phone = "whatsapp:+15557770021"
    patient_phone = "whatsapp:+15557770022"
    _run_caregiver_onboarding(caregiver_phone, patient_phone)

    resend = _twilio(caregiver_phone, "resend", "SM-resend-1")
    assert "Verification" in resend

    cancel = _twilio(caregiver_phone, "cancel", "SM-cancel-1")
    assert "canceled" in cancel.lower()

    caregiver = context.store.find_participant_record_by_phone(caregiver_phone)
    assert caregiver is not None
    pending = context.store.get_pending_verification_for_caregiver(str(caregiver["id"]))
    assert pending is None


def test_pending_verification_expires_and_fails_closed() -> None:
    settings.validate_twilio_signature = False
    caregiver_phone = "whatsapp:+15557770031"
    patient_phone = "whatsapp:+15557770032"
    code = _run_caregiver_onboarding(caregiver_phone, patient_phone)

    caregiver = context.store.find_participant_record_by_phone(caregiver_phone)
    assert caregiver is not None
    pending = context.store.get_pending_verification_for_caregiver(str(caregiver["id"]))
    assert pending is not None

    context.store.update_verification_request(
        pending.id,
        status="pending",
        resolved_at=None,
        resolution_note="",
    )
    context.store.update_verification_request(
        pending.id,
        last_sent_at=datetime.now(UTC) - timedelta(days=2),
    )
    # force expiry by rewriting via onboarding-session save path equivalent
    if hasattr(context.store, "caregiver_verification_requests"):
        context.store.caregiver_verification_requests[pending.id]["expires_at"] = datetime.now(UTC) - timedelta(minutes=1)

    expired_msg = _twilio(caregiver_phone, "status", "SM-expire-1")
    assert "expired" in expired_msg.lower()

    patient_attempt = _twilio(patient_phone, f"APPROVE {code}", "SM-expire-2")
    assert "onboarding" in patient_attempt.lower() or "no" in patient_attempt.lower()
