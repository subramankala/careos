from __future__ import annotations

import pytest

from careos.app_context import context
from careos.db.repositories.store import InMemoryStore
from careos.settings import settings


@pytest.fixture(autouse=True)
def reset_in_memory_store() -> None:
    previous_use_in_memory = settings.use_in_memory
    settings.use_in_memory = True
    store = InMemoryStore()
    context.store = store
    context.identity_service.store = store
    context.win_service.store = store
    context.care_plan_edits.store = store
    context.messaging.store = store
    yield
    settings.use_in_memory = previous_use_in_memory
