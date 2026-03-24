from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from careos.app_context import context
from careos.domain.enums.core import PersonaType, Role
from careos.domain.models.api import ParticipantCreate, PatientCreate, TenantCreate
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
    assert "Welcome to CareOS." in first
    assert "Are you onboarding for:" in first

    second = _twilio(sender, "myself", "SM_onboard_self_2")
    assert "Please share patient full name." in second

    third = _twilio(sender, "Indira Devi", "SM_onboard_self_3")
    assert "Done. Profile created for Indira Devi." in third
    assert "You're set up for your own care." in third
    assert "Care setup menu:" in third

    finish = _twilio(sender, "4", "SM_onboard_self_4")
    assert "Setup saved." in finish
    assert "SCHEDULE" in finish

    help_text = _twilio(sender, "help", "SM_onboard_self_4b")
    assert "CareOS home" in help_text
    assert "Acting as: patient for Indira Devi" in help_text
    assert "remember I had a stent placed in February" in help_text

    rating = _twilio(sender, "somewhat", "SM_onboard_self_4c")
    assert "Thanks for the feedback." in rating
    assert hasattr(context.store, "participant_feedback")
    assert any(
        item.get("participant_id") is not None
        and item.get("feedback_type") == "onboarding_setup_rating"
        and item.get("message") == "somewhat"
        for item in context.store.participant_feedback
    )

    explicit = _twilio(sender, "feedback the setup was a bit long", "SM_onboard_self_4d")
    assert "Thanks. Your feedback was saved." in explicit
    assert any(
        item.get("feedback_type") == "feedback" and item.get("message") == "the setup was a bit long"
        for item in context.store.participant_feedback
    )

    schedule = _twilio(sender, "schedule", "SM_onboard_self_5")
    assert "No wins are scheduled for today." in schedule


def test_unknown_phone_caregiver_onboarding_reaches_verification_pending() -> None:
    settings.validate_twilio_signature = False
    sender = "whatsapp:+15556660002"

    _twilio(sender, "hello", "SM_onboard_care_1")
    _twilio(sender, "someone I care for", "SM_onboard_care_2")
    _twilio(sender, "Kumar", "SM_onboard_care_3")
    _twilio(sender, "Nageswara Rao", "SM_onboard_care_4")
    _twilio(sender, "+15556667777", "SM_onboard_care_5")
    done = _twilio(sender, "son", "SM_onboard_care_6")

    assert "Verification pending" in done

    session = context.store.get_onboarding_session(sender)
    assert session is not None
    assert session.state == "verification_pending"
    assert session.status == "active"


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
    assert "Welcome to CareOS." in first
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
    assert "Welcome to CareOS." in restarted
    assert "Are you onboarding for:" in restarted


def test_existing_user_support_menu_can_show_feedback_history() -> None:
    tenant = context.store.create_tenant(TenantCreate(name="Support Family"))
    participant = context.store.create_participant(
        ParticipantCreate(
            tenant_id=str(tenant["id"]),
            role=Role.CAREGIVER,
            display_name="Support User",
            phone_number="whatsapp:+15556660010",
        )
    )
    patient = context.store.create_patient(
        PatientCreate(
            tenant_id=str(tenant["id"]),
            display_name="Support Patient",
            timezone="UTC",
            persona_type=PersonaType.CAREGIVER_MANAGED_ELDER,
        )
    )
    context.store.link_caregiver(str(participant["id"]), str(patient["id"]))
    context.store.create_participant_feedback(
        tenant_id=str(tenant["id"]),
        patient_id=str(patient["id"]),
        participant_id=str(participant["id"]),
        source_channel="whatsapp",
        feedback_type="feedback",
        message="Need bigger reminder text",
        structured_context={"source": "test"},
    )
    identity = context.identity_service.resolve_participant_by_phone("whatsapp:+15556660010")
    assert identity is not None

    menu = context.onboarding.maybe_handle_message(
        sender_phone="whatsapp:+15556660010",
        body="support",
        identity=identity,
        linked_patient_count=1,
    )
    assert "Support options:" in menu
    assert "1) see my feedback" in menu

    feedback = context.onboarding.maybe_handle_message(
        sender_phone="whatsapp:+15556660010",
        body="1",
        identity=identity,
        linked_patient_count=1,
    )
    assert "Your recent feedback:" in feedback
    assert "Need bigger reminder text" in feedback


def test_existing_user_restart_onboarding_is_immediate_and_explicit_without_active_session() -> None:
    tenant = context.store.create_tenant(TenantCreate(name="Restart Family"))
    participant = context.store.create_participant(
        ParticipantCreate(
            tenant_id=str(tenant["id"]),
            role=Role.CAREGIVER,
            display_name="Restart User",
            phone_number="whatsapp:+15556660012",
        )
    )
    patient = context.store.create_patient(
        PatientCreate(
            tenant_id=str(tenant["id"]),
            display_name="Restart Patient",
            timezone="UTC",
            persona_type=PersonaType.CAREGIVER_MANAGED_ELDER,
        )
    )
    context.store.link_caregiver(str(participant["id"]), str(patient["id"]))
    identity = context.identity_service.resolve_participant_by_phone("whatsapp:+15556660012")
    assert identity is not None

    reply = context.onboarding.maybe_handle_message(
        sender_phone="whatsapp:+15556660012",
        body="Restart Onboarding",
        identity=identity,
        linked_patient_count=1,
    )

    assert reply is not None
    assert "Onboarding restarted. Starting over now." in reply
    assert "Welcome to CareOS." in reply
    session = context.store.get_onboarding_session("whatsapp:+15556660012")
    assert session is not None
    assert session.state == "choose_role"
    assert session.status == "active"


def test_existing_user_support_menu_can_create_erasure_request() -> None:
    tenant = context.store.create_tenant(TenantCreate(name="Deletion Family"))
    participant = context.store.create_participant(
        ParticipantCreate(
            tenant_id=str(tenant["id"]),
            role=Role.CAREGIVER,
            display_name="Deletion User",
            phone_number="whatsapp:+15556660011",
        )
    )
    patient = context.store.create_patient(
        PatientCreate(
            tenant_id=str(tenant["id"]),
            display_name="Deletion User",
            timezone="UTC",
            persona_type=PersonaType.CAREGIVER_MANAGED_ELDER,
        )
    )
    context.store.link_caregiver(str(participant["id"]), str(patient["id"]))
    identity = context.identity_service.resolve_participant_by_phone("whatsapp:+15556660011")
    assert identity is not None

    context.onboarding.maybe_handle_message(
        sender_phone="whatsapp:+15556660011",
        body="support",
        identity=identity,
        linked_patient_count=1,
    )
    deletion = context.onboarding.maybe_handle_message(
        sender_phone="whatsapp:+15556660011",
        body="2",
        identity=identity,
        linked_patient_count=1,
    )

    assert "I created a profile deletion request for review." in deletion
    requests = context.store.list_privacy_requests(subject_participant_id=str(participant["id"]))
    assert len(requests) == 1
    assert requests[0]["request_type"] == "erasure"
