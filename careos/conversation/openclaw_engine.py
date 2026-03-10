from careos.conversation.engine_base import ConversationEngine
from careos.domain.models.api import CommandResult, ParticipantContext


class OpenClawConversationEngine(ConversationEngine):
    """Placeholder pluggable engine.

    Production integration should call MCP-backed tools and return structured intents.
    """

    def handle(self, text: str, context: ParticipantContext) -> CommandResult:
        return CommandResult(action="unavailable", text="Natural language engine is not enabled in this environment.")
