from __future__ import annotations

from fastapi.testclient import TestClient

from careos.gateway.main import app
from careos.gateway.routes import events_gateway


client = TestClient(app)


class _Adapter:
    def __init__(self) -> None:
        self.keys: set[str] = set()

    def list_active_personalization_rules(self, *, tenant_id: str, patient_id: str) -> dict:
        return {"rules": [{"rule_type": "critical_only_today"}]}

    def log_mediation_decision(self, **kwargs) -> dict:  # noqa: ANN003
        key = str(kwargs["idempotency_key"])
        if key in self.keys:
            return {"ok": True, "inserted": False}
        self.keys.add(key)
        return {"ok": True, "inserted": True}


class _Sender:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def send_text(self, *, to_number: str, body: str) -> str:
        self.calls.append((to_number, body))
        return "SM_TEST_GATEWAY"


def test_gateway_events_suppresses_class_c_with_active_critical_only_rule(monkeypatch) -> None:
    monkeypatch.setattr(events_gateway, "adapter", _Adapter())
    sender = _Sender()
    monkeypatch.setattr(events_gateway, "build_sender", lambda: sender)

    response = client.post(
        "/gateway/careos/events",
        json={
            "event_id": "evt-c-1",
            "tenant_id": "tenant-1",
            "patient_id": "patient-1",
            "participant_id": "participant-1",
            "event_type": "walk_reminder",
            "due_at": "2026-03-12T10:00:00Z",
            "to_number": "whatsapp:+15550000001",
            "suppression_policy": {
                "criticality_class": "C",
                "suppression_allowed": True,
                "delay_allowed": True,
                "transformation_allowed": True,
                "reroute_allowed": True,
            },
            "message_payload": {"body": "Time for a walk."},
            "correlation_id": "corr-c-1",
        },
    )
    assert response.status_code == 200
    assert response.json()["action"] == "suppress"
    assert sender.calls == []


def test_gateway_events_sends_class_a_and_is_idempotent(monkeypatch) -> None:
    adapter = _Adapter()
    monkeypatch.setattr(events_gateway, "adapter", adapter)
    sender = _Sender()
    monkeypatch.setattr(events_gateway, "build_sender", lambda: sender)

    payload = {
        "event_id": "evt-a-1",
        "tenant_id": "tenant-1",
        "patient_id": "patient-1",
        "participant_id": "participant-1",
        "event_type": "medication_due",
        "due_at": "2026-03-12T10:00:00Z",
        "to_number": "whatsapp:+15550000002",
        "suppression_policy": {
            "criticality_class": "A",
            "suppression_allowed": False,
            "delay_allowed": False,
            "transformation_allowed": True,
            "reroute_allowed": True,
        },
        "message_payload": {"body": "Critical medication due now."},
        "correlation_id": "corr-a-1",
    }

    first = client.post("/gateway/careos/events", json=payload)
    second = client.post("/gateway/careos/events", json=payload)

    assert first.status_code == 200
    assert first.json()["action"] == "send"
    assert second.status_code == 200
    assert second.json()["deduped"] is True
    assert len(sender.calls) == 1
