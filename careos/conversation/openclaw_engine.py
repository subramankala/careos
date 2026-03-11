from __future__ import annotations

import json
from urllib.parse import urlparse
from urllib.error import URLError
from urllib.request import Request, urlopen

from careos.conversation.fallback_bridge_logic import fallback_intent, resolve_fallback_text
from careos.conversation.engine_base import ConversationEngine
from careos.domain.models.api import CommandResult, ParticipantContext
from careos.logging import get_logger
from careos.settings import settings
from careos.services.win_service import WinService

logger = get_logger("openclaw_engine")


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

    def __init__(self, *, base_url: str, timeout_seconds: int = 15, win_service: WinService | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = max(int(timeout_seconds), 1)
        self.win_service = win_service

    def _is_local_bridge_url(self) -> bool:
        if not self.base_url:
            return False
        parsed = urlparse(self.base_url)
        host = (parsed.hostname or "").lower()
        port = parsed.port
        if host not in {"127.0.0.1", "localhost", "0.0.0.0"}:
            return False
        return port in {None, int(settings.api_port)}

    def handle(self, text: str, context: ParticipantContext) -> CommandResult:
        if not self.base_url:
            logger.warning("nl_fallback_unavailable", reason="missing_base_url")
            return CommandResult(action="unavailable", text="")
        if self._is_local_bridge_url() and self.win_service is not None:
            mapped_intent = fallback_intent(text)
            logger.info(
                "nl_fallback_used",
                source="inprocess_bridge",
                patient_id=context.patient_id,
                participant_id=context.participant_id,
                mapped_intent=mapped_intent,
            )
            local_text = resolve_fallback_text(text, context, self.win_service)
            if mapped_intent == "unmapped":
                logger.info(
                    "nl_fallback_unmapped",
                    source="inprocess_bridge",
                    patient_id=context.patient_id,
                    participant_id=context.participant_id,
                )
            return CommandResult(action="openclaw_fallback", text=local_text)

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
            logger.exception(
                "nl_fallback_unavailable",
                reason="remote_bridge_error",
                base_url=self.base_url,
                patient_id=context.patient_id,
                participant_id=context.participant_id,
            )
            return CommandResult(action="unavailable", text="")

        text_reply = str(data.get("text", "")).strip() if isinstance(data, dict) else ""
        action = str(data.get("action", "openclaw_fallback")).strip() if isinstance(data, dict) else "openclaw_fallback"
        if not text_reply:
            logger.warning(
                "nl_fallback_unavailable",
                reason="empty_text_reply",
                base_url=self.base_url,
                patient_id=context.patient_id,
                participant_id=context.participant_id,
            )
            return CommandResult(action="unavailable", text="")
        logger.info(
            "nl_fallback_used",
            source="remote_bridge",
            base_url=self.base_url,
            patient_id=context.patient_id,
            participant_id=context.participant_id,
            action=action or "openclaw_fallback",
        )
        return CommandResult(action=action or "openclaw_fallback", text=text_reply)
