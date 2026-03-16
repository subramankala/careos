from types import SimpleNamespace

from careos.api.routes import internal
from careos.db.repositories.store import InMemoryStore
from careos.domain.enums.core import Role
from careos.domain.models.api import ParticipantCreate, PatientCreate, TenantCreate


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
    store.link_caregiver(primary["id"], patient["id"], preset="primary_caregiver")
    store.link_caregiver(observer["id"], patient["id"], preset="observer")
    return store, patient["id"], primary["id"], observer["id"]


def test_store_lists_and_updates_caregiver_presets() -> None:
    store, patient_id, _primary_id, observer_id = _seed_store()

    links = store.list_caregiver_links_for_patient(patient_id)
    assert len(links) == 2
    assert links[0]["preset"] == "primary_caregiver"
    assert links[1]["preset"] == "observer"

    updated = store.update_caregiver_link_preset(observer_id, patient_id, "primary_caregiver")
    assert updated is not None
    assert updated["preset"] == "primary_caregiver"
    assert updated["authorization_version"] == 2


def test_internal_caregiver_preset_update_requires_primary_actor(monkeypatch) -> None:
    store, patient_id, primary_id, observer_id = _seed_store()
    monkeypatch.setattr(internal, "context", SimpleNamespace(store=store))

    payload = internal.CaregiverPresetUpdateRequest(
        actor_id=primary_id,
        patient_id=patient_id,
        caregiver_participant_id=observer_id,
        preset="primary_caregiver",
    )
    result = internal.update_caregiver_link_preset(payload)

    assert result["preset"] == "primary_caregiver"
    assert result["authorization_version"] == 2
