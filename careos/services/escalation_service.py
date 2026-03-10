from careos.db.repositories.store import Store
from careos.domain.enums.core import WinState


class EscalationService:
    def __init__(self, store: Store) -> None:
        self.store = store

    def escalate_if_required(self, win_instance_id: str, actor_id: str) -> None:
        self.store.mark_win(win_instance_id, actor_id, state=WinState.ESCALATED)
