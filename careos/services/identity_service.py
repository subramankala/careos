from careos.db.repositories.store import Store
from careos.domain.models.api import ParticipantContext


class IdentityService:
    def __init__(self, store: Store) -> None:
        self.store = store

    def resolve_by_phone(self, phone_number: str) -> ParticipantContext | None:
        return self.store.resolve_participant_context(phone_number)
