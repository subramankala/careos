from __future__ import annotations

import pytest
from fastapi import HTTPException

from careos import mcp_server


def test_mcp_tools_requires_api_key(monkeypatch) -> None:
    monkeypatch.setenv("CAREOS_MCP_API_KEY", "secret-key")
    with pytest.raises(HTTPException) as exc_info:
        mcp_server.list_tools()
    assert exc_info.value.status_code == 401

    authorized = mcp_server.list_tools(x_mcp_api_key="secret-key")
    assert any(tool["name"] == "careos_add_win" for tool in authorized["tools"])


def test_mcp_read_tool_routes_to_careos(monkeypatch) -> None:
    monkeypatch.setenv("CAREOS_MCP_API_KEY", "")

    calls: list[tuple[str, str, dict | None]] = []

    def _fake_request(path: str, *, method: str = "GET", payload=None):
        calls.append((path, method, payload))
        return {"ok": True}

    monkeypatch.setattr(mcp_server, "_request_json", _fake_request)

    response = mcp_server.call_tool(
        mcp_server.ToolCallRequest(tool="careos_get_status", arguments={"patient_id": "p-123"})
    )
    assert response.ok is True
    assert calls == [("/patients/p-123/status", "GET", None)]


def test_mcp_dashboard_read_tools_route_to_internal_endpoints(monkeypatch) -> None:
    monkeypatch.setenv("CAREOS_MCP_API_KEY", "")

    calls: list[tuple[str, str, dict | None]] = []

    def _fake_request(path: str, *, method: str = "GET", payload=None):
        calls.append((path, method, payload))
        return {"ok": True}

    monkeypatch.setattr(mcp_server, "_request_json", _fake_request)

    response = mcp_server.call_tool(
        mcp_server.ToolCallRequest(tool="careos_get_patient_summary", arguments={"patient_id": "p-123"})
    )
    assert response.ok is True
    assert calls == [("/internal/dashboard/patient-summary?patient_id=p-123", "GET", None)]


def test_mcp_dashboard_access_tool_routes_to_internal_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("CAREOS_MCP_API_KEY", "")

    calls: list[tuple[str, str, dict | None]] = []

    def _fake_request(path: str, *, method: str = "GET", payload=None):
        calls.append((path, method, payload))
        return {"ok": True}

    monkeypatch.setattr(mcp_server, "_request_json", _fake_request)

    response = mcp_server.call_tool(
        mcp_server.ToolCallRequest(
            tool="careos_get_view_access",
            arguments={
                "actor_id": "actor-1",
                "patient_id": "patient-1",
                "tenant_id": "tenant-1",
                "view": "caregiver_dashboard",
            },
        )
    )
    assert response.ok is True
    assert calls == [
        (
            "/internal/dashboard/access?actor_id=actor-1&patient_id=patient-1&tenant_id=tenant-1&view=caregiver_dashboard",
            "GET",
            None,
        )
    ]


def test_mcp_context_tool_urlencodes_phone_number(monkeypatch) -> None:
    monkeypatch.setenv("CAREOS_MCP_API_KEY", "")

    calls: list[tuple[str, str, dict | None]] = []

    def _fake_request(path: str, *, method: str = "GET", payload=None):
        calls.append((path, method, payload))
        return {"ok": True}

    monkeypatch.setattr(mcp_server, "_request_json", _fake_request)

    response = mcp_server.call_tool(
        mcp_server.ToolCallRequest(
            tool="careos_resolve_caregiver_context",
            arguments={"phone_number": "whatsapp:+15551112222"},
        )
    )
    assert response.ok is True
    assert calls == [("/internal/resolve-context?phone_number=whatsapp%3A%2B15551112222", "GET", None)]


def test_mcp_write_tool_requires_actor_role_and_reason(monkeypatch) -> None:
    monkeypatch.setenv("CAREOS_MCP_API_KEY", "")
    monkeypatch.setenv("CAREOS_MCP_ALLOWED_WRITE_ROLES", "caregiver")

    with pytest.raises(HTTPException) as bad:
        mcp_server.call_tool(
            mcp_server.ToolCallRequest(
                tool="careos_complete_win",
                arguments={"win_instance_id": "w1", "actor_id": "a1", "actor_role": "patient", "reason": "done"},
            )
        )
    assert bad.value.status_code == 403

    with pytest.raises(HTTPException) as missing_reason:
        mcp_server.call_tool(
            mcp_server.ToolCallRequest(
                tool="careos_complete_win",
                arguments={"win_instance_id": "w1", "actor_id": "a1", "actor_role": "caregiver"},
            )
        )
    assert missing_reason.value.status_code == 400


def test_mcp_write_tool_delay_routes_payload(monkeypatch) -> None:
    monkeypatch.setenv("CAREOS_MCP_API_KEY", "")
    monkeypatch.setenv("CAREOS_MCP_ALLOWED_WRITE_ROLES", "caregiver,patient")

    calls: list[tuple[str, str, dict | None]] = []

    def _fake_request(path: str, *, method: str = "GET", payload=None):
        calls.append((path, method, payload))
        return {"ok": True}

    monkeypatch.setattr(mcp_server, "_request_json", _fake_request)

    response = mcp_server.call_tool(
        mcp_server.ToolCallRequest(
            tool="careos_delay_win",
            arguments={
                "win_instance_id": "w-1",
                "actor_id": "actor-1",
                "actor_role": "caregiver",
                "reason": "patient requested delay",
                "minutes": 30,
            },
        )
    )
    assert response.ok is True
    assert calls == [
        (
            "/wins/w-1/delay",
            "POST",
            {"actor_participant_id": "actor-1", "reason": "patient requested delay", "minutes": 30},
        )
    ]
