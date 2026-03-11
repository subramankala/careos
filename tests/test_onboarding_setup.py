from __future__ import annotations

from fastapi.testclient import TestClient

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


def _self_onboard_until_setup(phone: str) -> None:
    _twilio(phone, "hi", f"{phone}-s1")
    _twilio(phone, "myself", f"{phone}-s2")
    done = _twilio(phone, "Indira Setup", f"{phone}-s3")
    assert "Care setup menu:" in done


def test_setup_add_medication_then_finish_allows_normal_commands() -> None:
    settings.validate_twilio_signature = False
    phone = "whatsapp:+15558880001"
    _self_onboard_until_setup(phone)

    _twilio(phone, "1", "SM-setup-med-1")
    _twilio(phone, "Pantoprazole 40mg", "SM-setup-med-2")
    _twilio(phone, "07:00", "SM-setup-med-3")
    _twilio(phone, "Before food", "SM-setup-med-4")
    done = _twilio(phone, "GI protection", "SM-setup-med-5")
    assert "Medication added:" in done

    finish = _twilio(phone, "4", "SM-setup-med-6")
    assert "Setup saved." in finish

    schedule = _twilio(phone, "schedule", "SM-setup-med-7")
    if "Pantoprazole 40mg" not in schedule:
        upcoming = _twilio(phone, "next", "SM-setup-med-8")
        assert "Pantoprazole 40mg" in upcoming


def test_setup_add_appointment_and_routine() -> None:
    settings.validate_twilio_signature = False
    phone = "whatsapp:+15558880002"
    _self_onboard_until_setup(phone)

    _twilio(phone, "2", "SM-setup-appt-1")
    _twilio(phone, "Follow-up Cardio", "SM-setup-appt-2")
    _twilio(phone, "2026-03-20", "SM-setup-appt-3")
    appt_done = _twilio(phone, "10:30", "SM-setup-appt-4")
    assert "Appointment added:" in appt_done

    _twilio(phone, "3", "SM-setup-rt-1")
    _twilio(phone, "2", "SM-setup-rt-2")
    _twilio(phone, "10:00-10:30", "SM-setup-rt-3")
    routine_done = _twilio(phone, "Walk 20 mins", "SM-setup-rt-4")
    assert "Routine added:" in routine_done


def test_caregiver_approval_continues_into_setup_menu() -> None:
    settings.validate_twilio_signature = False
    caregiver_phone = "whatsapp:+15558880003"
    patient_phone = "whatsapp:+15558880004"

    _twilio(caregiver_phone, "hi", "SM-cg-1")
    _twilio(caregiver_phone, "someone I care for", "SM-cg-2")
    _twilio(caregiver_phone, "Kumar", "SM-cg-3")
    _twilio(caregiver_phone, "Nageswara Rao", "SM-cg-4")
    _twilio(caregiver_phone, patient_phone, "SM-cg-5")
    pending = _twilio(caregiver_phone, "son", "SM-cg-6")
    assert "Verification pending" in pending

    # fetch approval code by asking patient side prompt
    prompt = _twilio(patient_phone, "hi", "SM-cg-7")
    assert "Reply APPROVE" in prompt
    code = prompt.split("APPROVE ", 1)[1].split(" ", 1)[0]

    approved = _twilio(patient_phone, f"APPROVE {code}", "SM-cg-8")
    assert "Approved" in approved

    menu = _twilio(caregiver_phone, "menu", "SM-cg-9")
    assert "Care setup menu:" in menu
