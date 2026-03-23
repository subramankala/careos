from __future__ import annotations

from datetime import UTC, datetime, timedelta

from careos.app_context import context
from careos.domain.enums.core import Criticality, Flexibility, PersonaType, Role
from careos.domain.models.api import AddWinsRequest, CarePlanCreate, ParticipantCreate, PatientCreate, TenantCreate, WinDefinitionCreate, WinInstanceCreate


def test_privacy_request_creation_and_listing() -> None:
    tenant = context.store.create_tenant(TenantCreate(name="Privacy Family"))
    participant = context.store.create_participant(
        ParticipantCreate(
            tenant_id=str(tenant["id"]),
            role=Role.CAREGIVER,
            display_name="Privacy User",
            phone_number="whatsapp:+15558880001",
        )
    )

    created = context.store.create_privacy_request(
        request_type="access",
        subject_participant_id=str(participant["id"]),
        jurisdiction="GDPR",
        reason="subject access request",
        structured_context={"channel": "support"},
    )
    listed = context.store.list_privacy_requests(subject_participant_id=str(participant["id"]))

    assert created["request_type"] == "access"
    assert created["jurisdiction"] == "GDPR"
    assert listed[0]["id"] == created["id"]


def test_subject_export_bundle_collects_related_records() -> None:
    tenant = context.store.create_tenant(TenantCreate(name="Export Family"))
    participant = context.store.create_participant(
        ParticipantCreate(
            tenant_id=str(tenant["id"]),
            role=Role.CAREGIVER,
            display_name="Export User",
            phone_number="whatsapp:+15558880002",
        )
    )
    patient = context.store.create_patient(
        PatientCreate(
            tenant_id=str(tenant["id"]),
            display_name="Export Patient",
            timezone="UTC",
            persona_type=PersonaType.CAREGIVER_MANAGED_ELDER,
        )
    )
    context.store.link_caregiver(str(participant["id"]), str(patient["id"]))
    context.store.save_onboarding_session(
        phone_number="whatsapp:+15558880002",
        state="completed",
        status="completed",
        data={"mode": "someone_i_care_for"},
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        completion_note="finished",
    )

    plan = context.store.create_care_plan(
        CarePlanCreate(
            patient_id=str(patient["id"]),
            created_by_participant_id=str(participant["id"]),
            status="active",
            version=1,
        )
    )
    start = datetime.now(UTC).replace(second=0, microsecond=0)
    context.store.add_wins(
        str(plan["id"]),
        AddWinsRequest(
            patient_id=str(patient["id"]),
            definitions=[
                WinDefinitionCreate(
                    category="medication",
                    title="Export medication",
                    instructions="Take tablet",
                    criticality=Criticality.MEDIUM,
                    flexibility=Flexibility.WINDOWED,
                )
            ],
            instances=[WinInstanceCreate(scheduled_start=start, scheduled_end=start + timedelta(minutes=30))],
        ),
    )
    context.messaging.log_inbound(
        tenant_id=str(tenant["id"]),
        patient_id=str(patient["id"]),
        participant_id=str(participant["id"]),
        body="schedule",
        correlation_id="privacy-export-1",
    )
    context.store.create_participant_feedback(
        tenant_id=str(tenant["id"]),
        patient_id=str(patient["id"]),
        participant_id=str(participant["id"]),
        source_channel="whatsapp",
        feedback_type="feedback",
        message="Need clearer meds list",
        structured_context={"role": "caregiver"},
    )
    context.store.create_privacy_request(
        request_type="export",
        subject_participant_id=str(participant["id"]),
        jurisdiction="CCPA",
        reason="know request",
    )

    bundle = context.store.export_subject_data(subject_participant_id=str(participant["id"]))

    assert bundle["participant"]["id"] == str(participant["id"])
    assert len(bundle["linked_patients"]) == 1
    assert len(bundle["message_events"]) == 1
    assert len(bundle["participant_feedback"]) == 1
    assert len(bundle["onboarding_sessions"]) == 1
    assert len(bundle["care_plans"]) == 1
    assert len(bundle["win_definitions"]) == 1
    assert len(bundle["win_instances"]) == 1
    assert len(bundle["privacy_requests"]) == 1
