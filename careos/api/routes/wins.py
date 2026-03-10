from fastapi import APIRouter

from careos.app_context import context
from careos.domain.models.api import WinActionRequest

router = APIRouter()


@router.post("/wins/{instance_id}/complete")
def complete_win(instance_id: str, payload: WinActionRequest) -> dict:
    context.win_service.complete(instance_id, payload.actor_participant_id)
    return {"ok": True}


@router.post("/wins/{instance_id}/delay")
def delay_win(instance_id: str, payload: WinActionRequest) -> dict:
    context.win_service.delay(instance_id, payload.actor_participant_id, payload.minutes)
    return {"ok": True}


@router.post("/wins/{instance_id}/skip")
def skip_win(instance_id: str, payload: WinActionRequest) -> dict:
    context.win_service.skip(instance_id, payload.actor_participant_id)
    return {"ok": True}


@router.post("/wins/{instance_id}/escalate")
def escalate_win(instance_id: str, payload: WinActionRequest) -> dict:
    context.win_service.escalate(instance_id, payload.actor_participant_id)
    return {"ok": True}
