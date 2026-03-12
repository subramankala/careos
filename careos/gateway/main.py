from fastapi import FastAPI

from careos.gateway.routes.health import router as health_router
from careos.gateway.routes.twilio_gateway import router as twilio_gateway_router
from careos.logging import configure_logging
from careos.settings import settings

configure_logging(settings.log_level)

app = FastAPI(title="careos-lite-gateway")
app.include_router(health_router)
app.include_router(twilio_gateway_router)

