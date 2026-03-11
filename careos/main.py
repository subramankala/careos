from fastapi import FastAPI

from careos.api.routes.care_plans import router as care_plans_router
from careos.api.routes.fallback_bridge import router as fallback_bridge_router
from careos.api.routes.health import router as health_router
from careos.api.routes.patients import router as patients_router
from careos.api.routes.twilio import router as twilio_router
from careos.api.routes.wins import router as wins_router
from careos.logging import configure_logging
from careos.settings import settings

configure_logging(settings.log_level)

app = FastAPI(title="careos-lite")
app.include_router(health_router)
app.include_router(fallback_bridge_router)
app.include_router(twilio_router)
app.include_router(patients_router)
app.include_router(care_plans_router)
app.include_router(wins_router)
