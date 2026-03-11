from careos.conversation.deterministic_router import DeterministicRouter
from careos.db.repositories.store import InMemoryStore, PostgresStore, Store
from careos.services.care_plan_edit_service import CarePlanEditService
from careos.services.identity_service import IdentityService
from careos.services.messaging_service import MessageOrchestrator
from careos.services.onboarding_service import OnboardingService
from careos.services.policy_engine import PolicyEngine
from careos.services.win_service import WinService
from careos.settings import settings


def build_store() -> Store:
    if settings.use_in_memory or not settings.database_url:
        return InMemoryStore()
    return PostgresStore(settings.database_url)


class AppContext:
    def __init__(self) -> None:
        self.store = build_store()
        self.identity_service = IdentityService(self.store)
        self.win_service = WinService(self.store)
        self.care_plan_edits = CarePlanEditService(self.store)
        self.policy_engine = PolicyEngine()
        self.messaging = MessageOrchestrator(self.store)
        self.onboarding = OnboardingService(self.store)
        self.router = DeterministicRouter(self.win_service)


context = AppContext()
