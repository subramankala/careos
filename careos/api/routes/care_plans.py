from fastapi import APIRouter, HTTPException

from careos.app_context import context
from careos.db.repositories.store import CarePlanPatch
from careos.domain.models.api import (
    AddWinsRequest,
    CarePlanChangeRecord,
    CarePlanCreate,
    CarePlanDeltaResult,
    CarePlanVersionRecord,
    CarePlanWinAddRequest,
    CarePlanWinRemoveRequest,
    CarePlanWinUpdateRequest,
)

router = APIRouter()


@router.post("/care-plans")
def create_care_plan(payload: CarePlanCreate) -> dict:
    return context.store.create_care_plan(payload)


@router.patch("/care-plans/{care_plan_id}")
def patch_care_plan(care_plan_id: str, payload: dict) -> dict:
    patch = CarePlanPatch(status=payload.get("status"), effective_end=payload.get("effective_end"))
    return context.store.patch_care_plan(care_plan_id, patch)


@router.post("/care-plans/{care_plan_id}/wins")
def add_wins(care_plan_id: str, payload: AddWinsRequest) -> dict:
    return context.store.add_wins(care_plan_id, payload)


@router.post("/care-plans/{care_plan_id}/wins/add", response_model=CarePlanDeltaResult)
def add_single_win(care_plan_id: str, payload: CarePlanWinAddRequest) -> CarePlanDeltaResult:
    try:
        return context.care_plan_edits.add_win(care_plan_id, payload)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/care-plans/{care_plan_id}/wins/{win_definition_id}", response_model=CarePlanDeltaResult)
def update_win(
    care_plan_id: str,
    win_definition_id: str,
    payload: CarePlanWinUpdateRequest,
) -> CarePlanDeltaResult:
    try:
        return context.care_plan_edits.update_win(care_plan_id, win_definition_id, payload)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/care-plans/{care_plan_id}/wins/{win_definition_id}", response_model=CarePlanDeltaResult)
def remove_win(
    care_plan_id: str,
    win_definition_id: str,
    payload: CarePlanWinRemoveRequest,
) -> CarePlanDeltaResult:
    try:
        return context.care_plan_edits.remove_win(care_plan_id, win_definition_id, payload)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/care-plans/{care_plan_id}/versions", response_model=list[CarePlanVersionRecord])
def list_versions(care_plan_id: str) -> list[CarePlanVersionRecord]:
    return context.care_plan_edits.list_versions(care_plan_id)


@router.get("/care-plans/{care_plan_id}/changes", response_model=list[CarePlanChangeRecord])
def list_changes(care_plan_id: str) -> list[CarePlanChangeRecord]:
    return context.care_plan_edits.list_changes(care_plan_id)
