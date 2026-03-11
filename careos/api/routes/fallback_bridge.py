from __future__ import annotations

import re

from fastapi import APIRouter
from pydantic import BaseModel, Field

from careos.app_context import context
from careos.domain.models.api import ParticipantContext

router = APIRouter()


class FallbackBridgeRequest(BaseModel):
    text: str
    participant_context: ParticipantContext
    allowed_actions: list[str] = Field(default_factory=list)


class FallbackBridgeResponse(BaseModel):
    text: str
    action: str = "openclaw_fallback"


def _map_plain_english_to_command(text: str) -> str | None:
    raw = text.strip()
    lower = raw.lower()

    if not raw:
        return "help"
    if lower in {"help", "?"} or "what can you do" in lower:
        return "help"
    if "schedule" in lower or "pending today" in lower or "left today" in lower:
        return "schedule"
    if "next" in lower:
        return "next"
    if "status" in lower or "adherence" in lower or "how am i doing" in lower:
        return "status"

    done_match = re.search(r"\b(?:done|complete|completed|took|taken|mark)\s+(\d+)\b", lower)
    if done_match:
        return f"done {done_match.group(1)}"
    done_mark_match = re.search(r"\bmark\s+(\d+)\s+as?\s+done\b", lower)
    if done_mark_match:
        return f"done {done_mark_match.group(1)}"

    skip_match = re.search(r"\b(?:skip|skipped)\s+(\d+)\b", lower)
    if skip_match:
        return f"skip {skip_match.group(1)}"

    delay_match = re.search(r"\b(?:delay|snooze)\s+(\d+)\s+(\d+)\b", lower)
    if delay_match:
        return f"delay {delay_match.group(1)} {delay_match.group(2)}"

    return None


@router.post("/v1/careos/fallback", response_model=FallbackBridgeResponse)
def fallback_bridge(payload: FallbackBridgeRequest) -> FallbackBridgeResponse:
    mapped = _map_plain_english_to_command(payload.text)
    if mapped is None:
        return FallbackBridgeResponse(
            text=(
                "I can help with schedule, next, status, done <item>, delay <item> <minutes>, and skip <item>. "
                "Try: 'schedule' or 'done 1'."
            )
        )

    result = context.router.handle(mapped, payload.participant_context)
    return FallbackBridgeResponse(text=result.text)
