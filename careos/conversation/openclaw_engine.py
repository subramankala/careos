from __future__ import annotations

import json
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
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

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: int = 15,
        win_service: WinService | None = None,
        fallback_path: str = "/v1/careos/fallback",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = max(int(timeout_seconds), 1)
        self.win_service = win_service
        self.fallback_path = fallback_path if fallback_path.startswith("/") else f"/{fallback_path}"

    def _is_local_bridge_url(self) -> bool:
        if not self.base_url:
            return False
        parsed = urlparse(self.base_url)
        host = (parsed.hostname or "").lower()
        port = parsed.port
        if host not in {"127.0.0.1", "localhost", "0.0.0.0"}:
            return False
        return port in {None, int(settings.api_port)}

    def _candidate_paths(self) -> list[str]:
        paths = [
            self.fallback_path,
            "/v1/careos/fallback",
            "/careos/fallback",
            "/api/v1/careos/fallback",
            "/v1/fallback",
        ]
        seen: set[str] = set()
        ordered: list[str] = []
        for path in paths:
            cleaned = path.strip()
            if not cleaned or not cleaned.startswith("/") or cleaned in seen:
                continue
            seen.add(cleaned)
            ordered.append(cleaned)
        return ordered

    @staticmethod
    def _extract_text(data: object) -> tuple[str, str]:
        if isinstance(data, dict):
            text = str(data.get("text", "")).strip()
            action = str(data.get("action", "openclaw_fallback")).strip() or "openclaw_fallback"
            if text:
                return text, action
            message = data.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip(), action
            response = data.get("response")
            if isinstance(response, str) and response.strip():
                return response.strip(), action
            choices = data.get("choices")
            if isinstance(choices, list) and choices:
                first = choices[0]
                if isinstance(first, dict):
                    msg = first.get("message")
                    if isinstance(msg, dict):
                        content = msg.get("content")
                        if isinstance(content, str) and content.strip():
                            return content.strip(), action
                    text_out = first.get("text")
                    if isinstance(text_out, str) and text_out.strip():
                        return text_out.strip(), action
        return "", "openclaw_fallback"

    def _call_remote(self, payload: dict, context: ParticipantContext) -> CommandResult:
        last_error_reason = "unknown"
        for path in self._candidate_paths():
            req = Request(
                f"{self.base_url}{path}",
                data=json.dumps(payload).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            try:
                with urlopen(req, timeout=self.timeout_seconds) as resp:  # noqa: S310
                    data = json.loads(resp.read().decode("utf-8"))
            except HTTPError as exc:
                last_error_reason = f"http_{exc.code}"
                if exc.code in {404, 405}:
                    continue
                logger.exception(
                    "nl_fallback_unavailable",
                    reason=last_error_reason,
                    base_url=self.base_url,
                    path=path,
                    patient_id=context.patient_id,
                    participant_id=context.participant_id,
                )
                return CommandResult(action="unavailable", text="")
            except (URLError, OSError, ValueError):
                last_error_reason = "transport_or_parse_error"
                logger.exception(
                    "nl_fallback_unavailable",
                    reason=last_error_reason,
                    base_url=self.base_url,
                    path=path,
                    patient_id=context.patient_id,
                    participant_id=context.participant_id,
                )
                return CommandResult(action="unavailable", text="")

            text_reply, action = self._extract_text(data)
            if text_reply:
                logger.info(
                    "nl_fallback_used",
                    source="remote_bridge",
                    base_url=self.base_url,
                    path=path,
                    patient_id=context.patient_id,
                    participant_id=context.participant_id,
                    action=action,
                )
                return CommandResult(action=action, text=text_reply)

        logger.warning(
            "nl_fallback_unavailable",
            reason=last_error_reason,
            base_url=self.base_url,
            patient_id=context.patient_id,
            participant_id=context.participant_id,
        )
        return CommandResult(action="unavailable", text="")

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
        return self._call_remote(payload, context)
