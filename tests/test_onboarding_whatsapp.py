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


def test_unknown_phone_self_onboarding_completes_and_can_use_schedule() -> None:
    settings.validate_twilio_signature = False
    sender = "whatsapp:+15556660001"

    first = _twilio(sender, "hi", "SM_onboard_self_1")
    assert "Are you onboarding for:" in first

    second = _twilio(sender, "myself", "SM_onboard_self_2")
    assert "Please share patient full name." in second

    third = _twilio(sender, "Indira Devi", "SM_onboard_self_3")
    assert "Done. Profile created for Indira Devi." in third

    schedule = _twilio(sender, "schedule", "SM_onboard_self_4")
    assert "No wins are scheduled for today." in schedule


def test_unknown_phone_caregiver_onboarding_reaches_handoff_pending() -> None:
    settings.validate_twilio_signature = False
    sender = "whatsapp:+15556660002"

    _twilio(sender, "hello", "SM_onboard_care_1")
    _twilio(sender, "someone I care for", "SM_onboard_care_2")
    _twilio(sender, "Kumar", "SM_onboard_care_3")
    _twilio(sender, "Nageswara Rao", "SM_onboard_care_4")
    _twilio(sender, "+15556667777", "SM_onboard_care_5")
    done = _twilio(sender, "son", "SM_onboard_care_6")

    assert "Handoff pending" in done

    session = context.store.get_onboarding_session(sender)
    assert session is not None
    assert session.state == "handoff_pending"
    assert session.status == "handoff_pending"


def test_incomplete_user_enters_onboarding_and_resume_state() -> None:
    settings.validate_twilio_signature = False

    tenant = client.post(
        "/tenants",
        json={"name": "Incomplete", "type": "family", "timezone": "UTC", "status": "active"},
    ).json()
    client.post(
        "/participants",
        json={
            "tenant_id": tenant["id"],
            "role": "caregiver",
            "display_name": "No Link User",
            "phone_number": "whatsapp:+15556660003",
            "preferred_channel": "whatsapp",
            "preferred_language": "en",
            "active": True,
        },
    )

    first = _twilio("whatsapp:+15556660003", "schedule", "SM_onboard_inc_1")
    assert "Are you onboarding for:" in first

    second = _twilio("whatsapp:+15556660003", "myself", "SM_onboard_inc_2")
    assert "Please share patient full name." in second

    session = context.store.get_onboarding_session("whatsapp:+15556660003")
    assert session is not None
    assert session.state == "self_patient_name"


def test_onboarding_expired_session_restarts_from_role_prompt() -> None:
    settings.validate_twilio_signature = False
    sender = "whatsapp:+15556660004"

    _twilio(sender, "hi", "SM_onboard_exp_1")
    _twilio(sender, "myself", "SM_onboard_exp_2")

    session = context.store.get_onboarding_session(sender)
    assert session is not None
    context.store.save_onboarding_session(
        phone_number=sender,
        state=session.state,
        status="active",
        data=session.data,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
        completion_note="",
    )

    restarted = _twilio(sender, "anything", "SM_onboard_exp_3")
    assert "Previous onboarding session expired." in restarted
    assert "Are you onboarding for:" in restarted
