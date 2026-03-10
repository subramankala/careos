from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from careos.app_context import context
from careos.domain.models.api import AdherenceSummaryResponse, ParticipantCreate, PatientCreate, TenantCreate

router = APIRouter()


@router.post("/patients")
def create_patient(payload: PatientCreate) -> dict:
    return context.store.create_patient(payload)


@router.post("/tenants")
def create_tenant(payload: TenantCreate) -> dict:
    return context.store.create_tenant(payload)


@router.post("/participants")
def create_participant(payload: ParticipantCreate) -> dict:
    return context.store.create_participant(payload)


@router.post("/caregivers")
def create_caregiver(payload: ParticipantCreate) -> dict:
    if payload.role.value != "caregiver":
        raise HTTPException(status_code=400, detail="role must be caregiver for /caregivers")
    return context.store.create_participant(payload)


@router.post("/caregiver-links")
def link_caregiver(payload: dict) -> dict:
    return context.store.link_caregiver(payload["caregiver_participant_id"], payload["patient_id"])


@router.get("/patients/{patient_id}/today")
def patient_today(patient_id: str) -> dict:
    return context.win_service.today(patient_id).model_dump()


@router.get("/patients/{patient_id}/timeline")
def patient_timeline(patient_id: str) -> list[dict]:
    return [item.model_dump() for item in context.win_service.today(patient_id).timeline]


@router.get("/patients/{patient_id}/status")
def patient_status(patient_id: str) -> dict:
    return context.win_service.status(patient_id).model_dump()


@router.get("/patients/{patient_id}/adherence-summary", response_model=AdherenceSummaryResponse)
def adherence_summary(patient_id: str) -> AdherenceSummaryResponse:
    return context.win_service.adherence_summary(patient_id, datetime.now(UTC).date())
