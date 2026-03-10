from careos.db.repositories.store import Store
from careos.domain.models.api import LinkedPatientSummary, ParticipantContext, ParticipantIdentity


class IdentityService:
    def __init__(self, store: Store) -> None:
        self.store = store

    def resolve_by_phone(self, phone_number: str) -> ParticipantContext | None:
        return self.store.resolve_participant_context(phone_number)

    def resolve_participant_by_phone(self, phone_number: str) -> ParticipantIdentity | None:
        return self.store.resolve_participant_by_phone(phone_number)

    def list_linked_patients(self, participant_id: str) -> list[LinkedPatientSummary]:
        return self.store.list_linked_patients(participant_id)

    def get_active_patient_context(self, participant_id: str) -> str | None:
        return self.store.get_active_patient_context(participant_id)

    def set_active_patient_context(self, participant_id: str, patient_id: str, selection_source: str) -> None:
        self.store.set_active_patient_context(participant_id, patient_id, selection_source)

    def clear_active_patient_context(self, participant_id: str) -> None:
        self.store.clear_active_patient_context(participant_id)
