import asyncio
from urllib.parse import urlencode

from careos.domain.models.api import CommandResult
from careos.gateway.careos_adapter import DashboardLinkError
from careos.gateway.routes import twilio_gateway
from careos.settings import settings


class _AdapterBase:
    def resolve_context(self, phone_number: str) -> dict | None:
        return {
            "tenant_id": "tenant-1",
            "participant_id": "participant-1",
            "participant_role": "caregiver",
            "patient_id": "patient-1",
            "patient_timezone": "Asia/Kolkata",
            "patient_persona": "caregiver_managed_elder",
        }

    def get_today(self, patient_id: str) -> dict:
        return {"patient_id": patient_id, "date": "2026-03-12", "timezone": "Asia/Kolkata", "timeline": []}

    def get_status(self, patient_id: str) -> dict:
        return {"completed_count": 0, "due_count": 1, "missed_count": 0, "skipped_count": 0, "adherence_score": 0.0}

    def generate_dashboard_view(
        self,
        *,
        tenant_id: str,
        patient_id: str,
        actor_id: str,
        role: str = "caregiver",
        view: str = "caregiver_dashboard",
    ) -> dict:
        return {"url": "https://careos.theginger.ai/v/test-token", "expires_in_seconds": 1800}


class _OpenClawOK:
    def handle(self, text: str, context) -> CommandResult:  # noqa: ANN001
        return CommandResult(action="openclaw_fallback", text="OpenClaw says hello.")


class _OpenClawUnavailable:
    def handle(self, text: str, context) -> CommandResult:  # noqa: ANN001
        return CommandResult(action="unavailable", text="")


class _FakeRequest:
    def __init__(self, form_body: str) -> None:
        self._body = form_body.encode("utf-8")

    async def body(self) -> bytes:
        return self._body


def _post_gateway(body: dict[str, str]):
    encoded = urlencode(body)
    return asyncio.run(twilio_gateway.twilio_gateway_webhook(_FakeRequest(encoded)))


def test_gateway_openclaw_first_uses_delegate(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "openclaw_first"
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        monkeypatch.setattr(twilio_gateway, "openclaw_delegate", _OpenClawOK())
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "what is next?",
                "MessageSid": "SM-gw-openclaw-1",
            }
        )
        assert response.status_code == 200
        assert b"OpenClaw says hello." in response.body
    finally:
        settings.gateway_conversation_mode = previous_mode


def test_gateway_openclaw_first_falls_back_to_deterministic(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "openclaw_first"
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        monkeypatch.setattr(twilio_gateway, "openclaw_delegate", _OpenClawUnavailable())
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "status",
                "MessageSid": "SM-gw-openclaw-2",
            }
        )
        assert response.status_code == 200
        assert b"Status: completed=0, due=1, missed=0, skipped=0, score=0.0%" in response.body
    finally:
        settings.gateway_conversation_mode = previous_mode


def test_gateway_dispatches_dashboard_intent_to_care_dash(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "give me the patient summary",
                "MessageSid": "SM-gw-openclaw-3",
            }
        )
        assert response.status_code == 200
        assert b"Open caregiver dashboard: https://careos.theginger.ai/v/test-token" in response.body
    finally:
        settings.gateway_conversation_mode = previous_mode


def test_gateway_dashboard_intent_returns_friendly_message_on_dash_failure(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "deterministic_first"

    class _BrokenAdapter(_AdapterBase):
        def generate_dashboard_view(self, **kwargs) -> dict:  # type: ignore[override]
            raise DashboardLinkError("dashboard_link_unavailable")

    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _BrokenAdapter())
        response = _post_gateway(
            {
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "how is my patient doing",
                "MessageSid": "SM-gw-openclaw-4",
            }
        )
        assert response.status_code == 200
        assert b"secure caregiver dashboard is temporarily unavailable" in response.body
    finally:
        settings.gateway_conversation_mode = previous_mode
