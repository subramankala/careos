from __future__ import annotations

from careos.db.repositories.store import InMemoryStore
from careos.domain.enums.core import Role
from careos.domain.models.api import ParticipantCreate, TenantCreate
from careos.services.onboarding_service import OnboardingService
from careos.settings import settings


def _send(service: OnboardingService, store: InMemoryStore, phone_number: str, body: str) -> str:
    identity = store.resolve_participant_by_phone(phone_number)
    linked_patient_count = 0
    if identity is not None:
        linked_patient_count = len(store.list_linked_patients(identity.participant_id))
    reply = service.maybe_handle_message(
        sender_phone=phone_number,
        body=body,
        identity=identity,
        linked_patient_count=linked_patient_count,
    )
    assert reply is not None
    return reply


def _onboard_self_patient(service: OnboardingService, store: InMemoryStore, phone_number: str, patient_name: str) -> dict:
    welcome = _send(service, store, phone_number, "hi")
    assert "onboarding" in welcome.lower()
    assert "patient full name" in _send(service, store, phone_number, "myself").lower()
    done = _send(service, store, phone_number, patient_name)
    assert "Profile created" in done

    participant = store.find_participant_record_by_phone(phone_number)
    assert participant is not None
    linked = store.list_linked_patients(str(participant["id"]))
    assert len(linked) == 1
    return {
        "participant_id": str(participant["id"]),
        "patient_id": linked[0].patient_id,
    }


def test_patient_invite_flow_creates_observer_link_after_approval() -> None:
    settings.twilio_account_sid = ""
    settings.twilio_auth_token = ""
    settings.twilio_whatsapp_number = ""

    store = InMemoryStore()
    service = OnboardingService(store)
    patient_phone = "whatsapp:+15558880001"
    caregiver_phone = "whatsapp:+15558880002"

    seeded = _onboard_self_patient(service, store, patient_phone, "Invite Unit Patient")

    assert "Inviting a caregiver" in _send(service, store, patient_phone, "invite caregiver")
    assert "Choose caregiver preset" in _send(service, store, patient_phone, caregiver_phone)
    sent = _send(service, store, patient_phone, "observer")
    assert "Invite sent" in sent
    assert "observer" in sent.lower()

    pending = store.list_pending_verifications_for_caregiver_phone(caregiver_phone)
    assert len(pending) == 1

    approved = _send(service, store, caregiver_phone, f"APPROVE {pending[0].approval_code}")
    assert "Caregiver access" in approved

    caregiver = store.find_participant_record_by_phone(caregiver_phone)
    assert caregiver is not None
    linked = store.get_caregiver_link(str(caregiver["id"]), seeded["patient_id"])
    assert linked is not None
    assert str(linked.get("notification_policy", {}).get("preset")) == "observer"


def test_patient_can_list_and_cancel_pending_invites() -> None:
    settings.twilio_account_sid = ""
    settings.twilio_auth_token = ""
    settings.twilio_whatsapp_number = ""

    store = InMemoryStore()
    service = OnboardingService(store)
    patient_phone = "whatsapp:+15558880011"
    first_caregiver_phone = "whatsapp:+15558880012"
    second_caregiver_phone = "whatsapp:+15558880013"

    seeded = _onboard_self_patient(service, store, patient_phone, "Invite Queue Patient")

    _send(service, store, patient_phone, "invite caregiver")
    _send(service, store, patient_phone, first_caregiver_phone)
    _send(service, store, patient_phone, "observer")

    _send(service, store, patient_phone, "invite caregiver")
    _send(service, store, patient_phone, second_caregiver_phone)
    _send(service, store, patient_phone, "primary caregiver")

    pending = [
        request
        for request in store.list_pending_verifications_for_patient_phone(patient_phone)
        if request.patient_id == seeded["patient_id"]
    ]
    assert len(pending) == 2

    listed = _send(service, store, patient_phone, "pending invites")
    assert "Pending caregiver invites:" in listed
    assert first_caregiver_phone in listed
    assert second_caregiver_phone in listed
    assert pending[0].approval_code in listed
    assert pending[1].approval_code in listed

    cancelled = _send(service, store, patient_phone, f"cancel invite {pending[0].approval_code}")
    assert f"Cancelled invite for {pending[0].caregiver_phone_number}." in cancelled

    remaining = [
        request
        for request in store.list_pending_verifications_for_patient_phone(patient_phone)
        if request.patient_id == seeded["patient_id"]
    ]
    assert len(remaining) == 1
    assert remaining[0].approval_code == pending[1].approval_code

    cancelled_request = store.get_verification_request(pending[0].id)
    assert cancelled_request is not None
    assert cancelled_request.status == "canceled"


def test_patient_invite_explains_cross_tenant_phone_conflict() -> None:
    settings.twilio_account_sid = ""
    settings.twilio_auth_token = ""
    settings.twilio_whatsapp_number = ""

    store = InMemoryStore()
    service = OnboardingService(store)
    patient_phone = "whatsapp:+15558880021"
    caregiver_phone = "whatsapp:+15558880022"

    tenant = store.create_tenant(TenantCreate(name="Other Family", type="family", timezone="UTC", status="active"))
    store.create_participant(
        ParticipantCreate(
            tenant_id=str(tenant["id"]),
            role=Role.CAREGIVER,
            display_name="Other Tenant Caregiver",
            phone_number=caregiver_phone,
            preferred_channel="whatsapp",
            preferred_language="en",
            active=True,
        )
    )

    _onboard_self_patient(service, store, patient_phone, "Cross Tenant Patient")
    _send(service, store, patient_phone, "invite caregiver")
    _send(service, store, patient_phone, caregiver_phone)
    reply = _send(service, store, patient_phone, "observer")
    assert "different CareOS family workspace" in reply
    assert "one phone can only belong to one tenant" in reply
