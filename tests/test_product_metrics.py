from __future__ import annotations

from careos.app_context import context


def test_product_metrics_overview_tracks_onboarding_and_feedback() -> None:
    service = context.onboarding
    sender = "whatsapp:+15557770001"

    first = service.maybe_handle_message(sender_phone=sender, body="hi", identity=None, linked_patient_count=0)
    assert first is not None and "Welcome to CareOS." in first

    second = service.maybe_handle_message(sender_phone=sender, body="myself", identity=None, linked_patient_count=0)
    assert second == "Please share patient full name."

    third = service.maybe_handle_message(sender_phone=sender, body="Metrics Patient", identity=None, linked_patient_count=0)
    assert third is not None and "Done. Profile created for Metrics Patient." in third

    identity = context.identity_service.resolve_participant_by_phone(sender)
    assert identity is not None
    linked_patients = context.identity_service.list_linked_patients(identity.participant_id)
    assert len(linked_patients) == 1
    patient_id = linked_patients[0].patient_id

    finish = service.maybe_handle_message(
        sender_phone=sender,
        body="4",
        identity=identity,
        linked_patient_count=len(linked_patients),
    )
    assert finish is not None and "Setup saved." in finish

    rating = service.maybe_handle_message(
        sender_phone=sender,
        body="somewhat",
        identity=identity,
        linked_patient_count=len(linked_patients),
    )
    assert rating == "Thanks for the feedback."

    explicit = service.maybe_capture_participant_feedback(
        identity=identity,
        patient_id=patient_id,
        body="feedback setup was mostly clear",
        source_channel="whatsapp_direct",
        active_flow="direct_chat",
    )
    assert explicit == "Thanks. Your feedback was saved."

    context.messaging.log_inbound(
        tenant_id=identity.tenant_id,
        patient_id=patient_id,
        participant_id=identity.participant_id,
        body="help",
        correlation_id="metrics-help",
    )
    context.messaging.log_inbound(
        tenant_id=identity.tenant_id,
        patient_id=patient_id,
        participant_id=identity.participant_id,
        body="feedback setup was mostly clear",
        correlation_id="metrics-feedback",
    )

    payload = context.store.get_product_metrics_overview(days=7)

    assert payload["onboarding"]["started"] == 1
    assert payload["onboarding"]["self_completed"] == 1
    assert payload["onboarding"]["setup_started"] == 1
    assert payload["onboarding"]["setup_completed"] == 1
    assert payload["feedback"]["total"] == 2
    assert payload["feedback"]["setup_ratings"]["somewhat"] == 1
    assert any(item["command"] == "feedback" for item in payload["usage"]["top_commands"])
    assert any(item["command"] == "help" for item in payload["usage"]["top_commands"])
    assert any(item["event_name"] == "participant_feedback_captured" for item in payload["telemetry"]["events_by_name"])
