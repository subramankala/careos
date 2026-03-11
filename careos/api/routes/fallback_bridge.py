from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from careos.app_context import context
from careos.conversation.fallback_bridge_logic import resolve_fallback_text
from careos.domain.models.api import ParticipantContext

router = APIRouter()


class FallbackBridgeRequest(BaseModel):
    text: str
    participant_context: ParticipantContext
    allowed_actions: list[str] = Field(default_factory=list)


class FallbackBridgeResponse(BaseModel):
    text: str
    action: str = "openclaw_fallback"


@router.post("/v1/careos/fallback", response_model=FallbackBridgeResponse)
def fallback_bridge(payload: FallbackBridgeRequest) -> FallbackBridgeResponse:
    return FallbackBridgeResponse(
        text=resolve_fallback_text(payload.text, payload.participant_context, context.win_service)
    )
