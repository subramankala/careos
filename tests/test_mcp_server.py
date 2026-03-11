from __future__ import annotations

from fastapi.testclient import TestClient

from careos import mcp_server


client = TestClient(mcp_server.app)


def test_mcp_tools_requires_api_key(monkeypatch) -> None:
    monkeypatch.setenv("CAREOS_MCP_API_KEY", "secret-key")
    unauthorized = client.get("/mcp/tools")
    assert unauthorized.status_code == 401

    authorized = client.get("/mcp/tools", headers={"x-mcp-api-key": "secret-key"})
    assert authorized.status_code == 200
    body = authorized.json()
    assert any(tool["name"] == "careos_add_win" for tool in body["tools"])


def test_mcp_read_tool_routes_to_careos(monkeypatch) -> None:
    monkeypatch.setenv("CAREOS_MCP_API_KEY", "")

    calls: list[tuple[str, str, dict | None]] = []

    def _fake_request(path: str, *, method: str = "GET", payload=None):
        calls.append((path, method, payload))
        return {"ok": True}

    monkeypatch.setattr(mcp_server, "_request_json", _fake_request)

    response = client.post(
        "/mcp/call",
        json={"tool": "careos_get_status", "arguments": {"patient_id": "p-123"}},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert calls == [("/patients/p-123/status", "GET", None)]


def test_mcp_write_tool_requires_actor_role_and_reason(monkeypatch) -> None:
    monkeypatch.setenv("CAREOS_MCP_API_KEY", "")
    monkeypatch.setenv("CAREOS_MCP_ALLOWED_WRITE_ROLES", "caregiver")

    bad = client.post(
        "/mcp/call",
        json={
            "tool": "careos_complete_win",
            "arguments": {"win_instance_id": "w1", "actor_id": "a1", "actor_role": "patient", "reason": "done"},
        },
    )
    assert bad.status_code == 403

    missing_reason = client.post(
        "/mcp/call",
        json={
            "tool": "careos_complete_win",
            "arguments": {"win_instance_id": "w1", "actor_id": "a1", "actor_role": "caregiver"},
        },
    )
    assert missing_reason.status_code == 400


def test_mcp_write_tool_delay_routes_payload(monkeypatch) -> None:
    monkeypatch.setenv("CAREOS_MCP_API_KEY", "")
    monkeypatch.setenv("CAREOS_MCP_ALLOWED_WRITE_ROLES", "caregiver,patient")

    calls: list[tuple[str, str, dict | None]] = []

    def _fake_request(path: str, *, method: str = "GET", payload=None):
        calls.append((path, method, payload))
        return {"ok": True}

    monkeypatch.setattr(mcp_server, "_request_json", _fake_request)

    response = client.post(
        "/mcp/call",
        json={
            "tool": "careos_delay_win",
            "arguments": {
                "win_instance_id": "w-1",
                "actor_id": "actor-1",
                "actor_role": "caregiver",
                "reason": "patient requested delay",
                "minutes": 30,
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert calls == [
        (
            "/wins/w-1/delay",
            "POST",
            {"actor_participant_id": "actor-1", "reason": "patient requested delay", "minutes": 30},
        )
    ]
