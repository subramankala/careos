from types import SimpleNamespace

import pytest

from careos.api.routes import internal
from careos.app_context import context
from careos.db.repositories.store import InMemoryStore
from careos.domain.enums.core import Role
from careos.domain.models.api import ParticipantCreate, PatientCreate, TenantCreate
from careos.services.care_team_service import CareTeamService


def _seed_store() -> tuple[InMemoryStore, str, str, str]:
    store = InMemoryStore()
    tenant = store.create_tenant(TenantCreate(name="Family"))
    patient = store.create_patient(PatientCreate(tenant_id=tenant["id"], display_name="Patient One", timezone="Asia/Kolkata"))
    primary = store.create_participant(
        ParticipantCreate(
            tenant_id=tenant["id"],
            role=Role.CAREGIVER,
            display_name="Primary Caregiver",
            phone_number="whatsapp:+15550001111",
        )
    )
    observer = store.create_participant(
        ParticipantCreate(
            tenant_id=tenant["id"],
            role=Role.CAREGIVER,
            display_name="Observer Caregiver",
            phone_number="whatsapp:+15550002222",
        )
    )
    return store, patient["id"], primary["id"], observer["id"]


def test_care_team_service_creates_and_lists_membership() -> None:
    store, patient_id, primary_id, _observer_id = _seed_store()
    service = CareTeamService(store)
    patient = store.get_patient_profile(patient_id)
    assert patient is not None

    created = service.create_membership(
        tenant_id=str(patient["tenant_id"]),
        patient_id=patient_id,
        participant_id=primary_id,
        membership_type="family caregiver",
        display_label="Primary family caregiver",
        authority_policy={"can_edit_plan": True},
        notification_policy={"preset": "primary_caregiver", "notification_preferences": {"due_reminders": True}},
    )

    assert created["membership_type"] == "family_caregiver"
    assert created["authority_policy"]["can_view_dashboard"] is True
    assert created["authority_policy"]["can_edit_plan"] is True
    assert created["notification_policy"]["preset"] == "primary_caregiver"

    team = service.list_team_for_patient(patient_id=patient_id)
    assert len(team) == 1
    assert team[0]["participant_id"] == primary_id
    assert team[0]["display_name"] == "Primary Caregiver"


def test_care_team_service_rejects_tenant_mismatch() -> None:
    store, patient_id, primary_id, _observer_id = _seed_store()
    service = CareTeamService(store)

    wrong_tenant = store.create_tenant(TenantCreate(name="Other"))

    with pytest.raises(ValueError):
        service.create_membership(
            tenant_id=str(wrong_tenant["id"]),
            patient_id=patient_id,
            participant_id=primary_id,
            membership_type="family_caregiver",
        )


def test_store_syncs_care_team_membership_from_caregiver_link() -> None:
    store, patient_id, primary_id, observer_id = _seed_store()
    store.link_caregiver(primary_id, patient_id, preset="primary_caregiver")
    store.link_caregiver(observer_id, patient_id, preset="observer")

    primary_row = store.upsert_care_team_membership_from_caregiver_link(primary_id, patient_id)
    observer_row = store.upsert_care_team_membership_from_caregiver_link(observer_id, patient_id)

    assert primary_row is not None
    assert observer_row is not None
    assert primary_row["membership_type"] == "family_caregiver"
    assert primary_row["authority_policy"]["can_edit_plan"] is True
    assert observer_row["membership_type"] == "observer"
    assert observer_row["authority_policy"]["can_edit_plan"] is False


def test_store_sync_does_not_overwrite_manual_care_team_membership() -> None:
    store, patient_id, primary_id, _observer_id = _seed_store()
    patient = store.get_patient_profile(patient_id)
    assert patient is not None
    store.link_caregiver(primary_id, patient_id, preset="primary_caregiver")

    manual = store.create_care_team_membership(
        tenant_id=str(patient["tenant_id"]),
        patient_id=patient_id,
        participant_id=primary_id,
        membership_type="professional_caregiver",
        relationship="care_manager",
        display_label="Manual override",
        authority_policy={"can_edit_plan": False},
        notification_policy={"preset": "observer", "notification_preferences": {"due_reminders": False}},
        source="manual",
    )

    synced = store.upsert_care_team_membership_from_caregiver_link(primary_id, patient_id)

    assert synced is not None
    assert synced["membership_id"] if "membership_id" in synced else synced["id"]
    assert synced["membership_type"] == "professional_caregiver"
    assert synced["display_label"] == "Manual override"
    assert synced["source"] == "manual"
    assert manual["id"] == (synced.get("membership_id") or synced.get("id"))


def test_internal_care_team_routes_create_list_update_and_deactivate(monkeypatch) -> None:
    store, patient_id, primary_id, _observer_id = _seed_store()
    patient = store.get_patient_profile(patient_id)
    assert patient is not None
    monkeypatch.setattr(internal, "context", SimpleNamespace(store=store, care_team=CareTeamService(store)))

    created = internal.create_care_team_membership(
        internal.CareTeamMembershipCreateRequest(
            tenant_id=str(patient["tenant_id"]),
            patient_id=patient_id,
            participant_id=primary_id,
            membership_type="family_caregiver",
            display_label="Primary family caregiver",
            authority_policy={"can_edit_plan": True},
            notification_policy={"preset": "primary_caregiver", "notification_preferences": {"due_reminders": True}},
        )
    )
    assert created["membership_type"] == "family_caregiver"

    listing = internal.list_care_team_memberships(patient_id=patient_id)
    assert len(listing["team"]) == 1
    membership_id = listing["team"][0]["membership_id"]

    updated = internal.update_care_team_membership(
        internal.CareTeamMembershipUpdateRequest(
            membership_id=membership_id,
            display_label="Updated label",
            authority_policy={"can_view_dashboard": True, "can_edit_plan": False, "can_manage_team": False},
        )
    )
    assert updated["display_label"] == "Updated label"
    assert updated["authority_policy"]["can_edit_plan"] is False

    deactivated = internal.deactivate_care_team_membership(membership_id=membership_id)
    assert deactivated["status"] == "inactive"


def test_internal_care_team_sync_from_caregiver_links(monkeypatch) -> None:
    store, patient_id, primary_id, observer_id = _seed_store()
    store.link_caregiver(primary_id, patient_id, preset="primary_caregiver")
    store.link_caregiver(observer_id, patient_id, preset="observer")
    monkeypatch.setattr(internal, "context", SimpleNamespace(store=store, care_team=CareTeamService(store)))

    synced = internal.sync_care_team_from_caregiver_links(patient_id=patient_id)

    assert len(synced["team"]) == 2
    assert {row["membership_type"] for row in synced["team"]} == {"family_caregiver", "observer"}


def test_care_team_service_is_wired_into_app_context_fixture() -> None:
    assert isinstance(context.store, InMemoryStore)
    assert context.care_team.store is context.store
