from __future__ import annotations

import json
from urllib.error import URLError
from urllib.request import Request, urlopen

from careos.conversation.engine_base import ConversationEngine
from careos.domain.models.api import CommandResult, ParticipantContext


class OpenClawConversationEngine(ConversationEngine):
    """OpenClaw fallback engine.

    Expected OpenClaw endpoint contract:
    - POST {base_url}/v1/careos/fallback
    - request JSON:
      {
        "text": "...",
        "participant_context": {...},
        "allowed_actions": ["read", "write_via_mcp"]
      }
    - response JSON:
      {
        "text": "user-facing reply",
        "action": "openclaw_fallback"
      }
    """

    def __init__(self, *, base_url: str, timeout_seconds: int = 15) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = max(int(timeout_seconds), 1)

    def handle(self, text: str, context: ParticipantContext) -> CommandResult:
        if not self.base_url:
            return CommandResult(action="unavailable", text="")

        payload = {
            "text": text,
            "participant_context": {
                "tenant_id": context.tenant_id,
                "participant_id": context.participant_id,
                "participant_role": context.participant_role.value,
                "patient_id": context.patient_id,
                "patient_timezone": context.patient_timezone,
                "patient_persona": context.patient_persona.value,
            },
            "allowed_actions": ["read", "write_via_mcp"],
        }
        req = Request(
            f"{self.base_url}/v1/careos/fallback",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(req, timeout=self.timeout_seconds) as resp:  # noqa: S310
                data = json.loads(resp.read().decode("utf-8"))
        except (URLError, OSError, ValueError):
            return CommandResult(action="unavailable", text="")

        text_reply = str(data.get("text", "")).strip() if isinstance(data, dict) else ""
        action = str(data.get("action", "openclaw_fallback")).strip() if isinstance(data, dict) else "openclaw_fallback"
        if not text_reply:
            return CommandResult(action="unavailable", text="")
        return CommandResult(action=action or "openclaw_fallback", text=text_reply)
