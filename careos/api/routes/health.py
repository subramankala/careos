from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"service": "careos-lite", "status": "ok"}
