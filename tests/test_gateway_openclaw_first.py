from fastapi.testclient import TestClient

from careos.domain.models.api import CommandResult
from careos.gateway.main import app
from careos.gateway.routes import twilio_gateway
from careos.settings import settings


client = TestClient(app)


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


class _OpenClawOK:
    def handle(self, text: str, context) -> CommandResult:  # noqa: ANN001
        return CommandResult(action="openclaw_fallback", text="OpenClaw says hello.")


class _OpenClawUnavailable:
    def handle(self, text: str, context) -> CommandResult:  # noqa: ANN001
        return CommandResult(action="unavailable", text="")


def test_gateway_openclaw_first_uses_delegate(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "openclaw_first"
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        monkeypatch.setattr(twilio_gateway, "openclaw_delegate", _OpenClawOK())
        response = client.post(
            "/gateway/twilio/webhook",
            data={
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "what is next?",
                "MessageSid": "SM-gw-openclaw-1",
            },
        )
        assert response.status_code == 200
        assert "OpenClaw says hello." in response.text
    finally:
        settings.gateway_conversation_mode = previous_mode


def test_gateway_openclaw_first_falls_back_to_deterministic(monkeypatch) -> None:
    previous_mode = settings.gateway_conversation_mode
    settings.gateway_conversation_mode = "openclaw_first"
    try:
        monkeypatch.setattr(twilio_gateway, "adapter", _AdapterBase())
        monkeypatch.setattr(twilio_gateway, "openclaw_delegate", _OpenClawUnavailable())
        response = client.post(
            "/gateway/twilio/webhook",
            data={
                "From": "whatsapp:+15550001111",
                "To": "whatsapp:+14155238886",
                "Body": "status",
                "MessageSid": "SM-gw-openclaw-2",
            },
        )
        assert response.status_code == 200
        assert "Status: completed=0, due=1, missed=0, skipped=0, score=0.0%" in response.text
    finally:
        settings.gateway_conversation_mode = previous_mode
