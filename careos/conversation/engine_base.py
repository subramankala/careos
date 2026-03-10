from __future__ import annotations

from abc import ABC, abstractmethod

from careos.domain.models.api import CommandResult, ParticipantContext


class ConversationEngine(ABC):
    @abstractmethod
    def handle(self, text: str, context: ParticipantContext) -> CommandResult:
        raise NotImplementedError
