from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


app = FastAPI(title="careos-lite-mcp")


def _careos_base_url() -> str:
    return os.getenv("CAREOS_MCP_CAREOS_BASE_URL", "http://127.0.0.1:8115").rstrip("/")


def _mcp_api_key() -> str:
    return os.getenv("CAREOS_MCP_API_KEY", "").strip()


def _allowed_write_roles() -> set[str]:
    raw = os.getenv("CAREOS_MCP_ALLOWED_WRITE_ROLES", "caregiver,patient,clinician,admin")
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def _request_json(
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any] | list[Any]:
    body = None
    headers: dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(f"{_careos_base_url()}{path}", method=method, data=body, headers=headers)
    with urlopen(req) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _query_path(path: str, **params: Any) -> str:
    return f"{path}?{urlencode(params, doseq=True)}"


def _require_write_role(arguments: dict[str, Any]) -> tuple[str, str]:
    actor_id = str(arguments.get("actor_id", "")).strip()
    actor_role = str(arguments.get("actor_role", "")).strip().lower()
    reason = str(arguments.get("reason", "")).strip()
    if not actor_id:
        raise HTTPException(status_code=400, detail="actor_id is required for write tools")
    if actor_role not in _allowed_write_roles():
        raise HTTPException(status_code=403, detail=f"actor_role '{actor_role}' not allowed for write tools")
    if not reason:
        raise HTTPException(status_code=400, detail="reason is required for write tools")
    return actor_id, reason


def _optional_dedupe(arguments: dict[str, Any]) -> dict[str, Any] | None:
    key = str(arguments.get("idempotency_key", "")).strip()
    if not key:
        return None
    if key in _WRITE_DEDUPE:
        return {"ok": True, "deduped": True, "idempotency_key": key}
    _WRITE_DEDUPE.add(key)
    return None


def _read_tool(tool: str, args: dict[str, Any]) -> dict[str, Any] | list[Any]:
    if tool == "careos_resolve_caregiver_context":
        phone_number = str(args.get("phone_number", "")).strip()
        if not phone_number:
            raise HTTPException(status_code=400, detail="phone_number is required")
        return _request_json(_query_path("/internal/resolve-context", phone_number=phone_number))

    if tool == "careos_get_view_access":
        actor_id = str(args.get("actor_id", "")).strip()
        patient_id = str(args.get("patient_id", "")).strip()
        tenant_id = str(args.get("tenant_id", "")).strip()
        view = str(args.get("view", "caregiver_dashboard")).strip()
        if not actor_id or not patient_id or not tenant_id:
            raise HTTPException(status_code=400, detail="actor_id, patient_id, tenant_id are required")
        return _request_json(
            _query_path(
                "/internal/dashboard/access",
                actor_id=actor_id,
                patient_id=patient_id,
                tenant_id=tenant_id,
                view=view,
            )
        )

    if tool == "careos_get_patient_summary":
        patient_id = str(args.get("patient_id", "")).strip()
        if not patient_id:
            raise HTTPException(status_code=400, detail="patient_id is required")
        return _request_json(_query_path("/internal/dashboard/patient-summary", patient_id=patient_id))

    if tool == "careos_get_escalations":
        patient_id = str(args.get("patient_id", "")).strip()
        if not patient_id:
            raise HTTPException(status_code=400, detail="patient_id is required")
        return _request_json(_query_path("/internal/dashboard/escalations", patient_id=patient_id))

    if tool == "careos_get_medications":
        patient_id = str(args.get("patient_id", "")).strip()
        if not patient_id:
            raise HTTPException(status_code=400, detail="patient_id is required")
        return _request_json(_query_path("/internal/dashboard/medications", patient_id=patient_id))

    if tool == "careos_get_clinical_facts":
        patient_id = str(args.get("patient_id", "")).strip()
        tenant_id = str(args.get("tenant_id", "")).strip()
        if not patient_id or not tenant_id:
            raise HTTPException(status_code=400, detail="tenant_id and patient_id are required")
        return _request_json(
            _query_path("/internal/patient-context/clinical-facts/active", tenant_id=tenant_id, patient_id=patient_id)
        )

    if tool == "careos_get_observations":
        patient_id = str(args.get("patient_id", "")).strip()
        tenant_id = str(args.get("tenant_id", "")).strip()
        if not patient_id or not tenant_id:
            raise HTTPException(status_code=400, detail="tenant_id and patient_id are required")
        return _request_json(
            _query_path("/internal/patient-context/observations/active", tenant_id=tenant_id, patient_id=patient_id)
        )

    if tool == "careos_get_day_plans":
        patient_id = str(args.get("patient_id", "")).strip()
        tenant_id = str(args.get("tenant_id", "")).strip()
        plan_date = str(args.get("plan_date", "")).strip()
        if not patient_id or not tenant_id:
            raise HTTPException(status_code=400, detail="tenant_id and patient_id are required")
        params: dict[str, Any] = {"tenant_id": tenant_id, "patient_id": patient_id}
        if plan_date:
            params["plan_date"] = plan_date
        return _request_json(_query_path("/internal/patient-context/day-plans/active", **params))

    if tool == "careos_get_recent_events":
        patient_id = str(args.get("patient_id", "")).strip()
        limit = int(args.get("limit", 10) or 10)
        if not patient_id:
            raise HTTPException(status_code=400, detail="patient_id is required")
        return _request_json(_query_path("/internal/dashboard/recent-events", patient_id=patient_id, limit=limit))

    if tool == "careos_get_task_criticality":
        patient_id = str(args.get("patient_id", "")).strip()
        if not patient_id:
            raise HTTPException(status_code=400, detail="patient_id is required")
        return _request_json(_query_path("/internal/dashboard/task-criticality", patient_id=patient_id))

    if tool in {"careos_get_today", "careos_get_status", "careos_get_timeline", "careos_get_adherence_summary"}:
        patient_id = str(args.get("patient_id", "")).strip()
        if not patient_id:
            raise HTTPException(status_code=400, detail="patient_id is required")
        if tool == "careos_get_today":
            return _request_json(f"/patients/{patient_id}/today")
        if tool == "careos_get_status":
            return _request_json(f"/patients/{patient_id}/status")
        if tool == "careos_get_timeline":
            return _request_json(f"/patients/{patient_id}/timeline")
        return _request_json(f"/patients/{patient_id}/adherence-summary")

    if tool in {"careos_list_care_plan_versions", "careos_list_care_plan_changes"}:
        care_plan_id = str(args.get("care_plan_id", "")).strip()
        if not care_plan_id:
            raise HTTPException(status_code=400, detail="care_plan_id is required")
        if tool == "careos_list_care_plan_versions":
            return _request_json(f"/care-plans/{care_plan_id}/versions")
        return _request_json(f"/care-plans/{care_plan_id}/changes")

    raise HTTPException(status_code=404, detail=f"unknown read tool '{tool}'")


def _write_tool(tool: str, args: dict[str, Any]) -> dict[str, Any] | list[Any]:
    deduped = _optional_dedupe(args)
    if deduped is not None:
        return deduped
    actor_id, reason = _require_write_role(args)

    if tool == "careos_add_win":
        care_plan_id = str(args.get("care_plan_id", "")).strip()
        patient_id = str(args.get("patient_id", "")).strip()
        definition = args.get("definition")
        if not care_plan_id or not patient_id or not isinstance(definition, dict):
            raise HTTPException(status_code=400, detail="care_plan_id, patient_id, definition are required")
        future_instances = args.get("future_instances", [])
        if not isinstance(future_instances, list):
            raise HTTPException(status_code=400, detail="future_instances must be a list")
        payload = {
            "actor_participant_id": actor_id,
            "reason": reason,
            "supersede_active_due": bool(args.get("supersede_active_due", False)),
            "patient_id": patient_id,
            "definition": definition,
            "future_instances": future_instances,
        }
        return _request_json(f"/care-plans/{care_plan_id}/wins/add", method="POST", payload=payload)

    if tool == "careos_update_win":
        care_plan_id = str(args.get("care_plan_id", "")).strip()
        win_definition_id = str(args.get("win_definition_id", "")).strip()
        if not care_plan_id or not win_definition_id:
            raise HTTPException(status_code=400, detail="care_plan_id and win_definition_id are required")
        patch = dict(args.get("patch") or {})
        payload = {
            "actor_participant_id": actor_id,
            "reason": reason,
            "supersede_active_due": bool(args.get("supersede_active_due", False)),
            **patch,
        }
        return _request_json(
            f"/care-plans/{care_plan_id}/wins/{win_definition_id}",
            method="PATCH",
            payload=payload,
        )

    if tool == "careos_remove_win":
        care_plan_id = str(args.get("care_plan_id", "")).strip()
        win_definition_id = str(args.get("win_definition_id", "")).strip()
        if not care_plan_id or not win_definition_id:
            raise HTTPException(status_code=400, detail="care_plan_id and win_definition_id are required")
        payload = {
            "actor_participant_id": actor_id,
            "reason": reason,
            "supersede_active_due": bool(args.get("supersede_active_due", True)),
        }
        return _request_json(
            f"/care-plans/{care_plan_id}/wins/{win_definition_id}",
            method="DELETE",
            payload=payload,
        )

    if tool in {"careos_complete_win", "careos_skip_win", "careos_delay_win", "careos_escalate_win"}:
        win_instance_id = str(args.get("win_instance_id", "")).strip()
        if not win_instance_id:
            raise HTTPException(status_code=400, detail="win_instance_id is required")
        route = {
            "careos_complete_win": "complete",
            "careos_skip_win": "skip",
            "careos_delay_win": "delay",
            "careos_escalate_win": "escalate",
        }[tool]
        payload = {
            "actor_participant_id": actor_id,
            "reason": reason,
            "minutes": int(args.get("minutes", 0)),
        }
        return _request_json(f"/wins/{win_instance_id}/{route}", method="POST", payload=payload)

    raise HTTPException(status_code=404, detail=f"unknown write tool '{tool}'")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    write: bool
    description: str


TOOLS: list[ToolSpec] = [
    ToolSpec("careos_resolve_caregiver_context", False, "Resolve caregiver/patient context from phone number."),
    ToolSpec("careos_get_view_access", False, "Resolve caregiver dashboard access for actor and patient."),
    ToolSpec("careos_get_patient_summary", False, "Get caregiver dashboard patient summary."),
    ToolSpec("careos_get_escalations", False, "Get caregiver dashboard escalations."),
    ToolSpec("careos_get_medications", False, "Get caregiver dashboard medications."),
    ToolSpec("careos_get_clinical_facts", False, "Get active durable clinical facts for a patient."),
    ToolSpec("careos_get_observations", False, "Get active short-lived patient observations."),
    ToolSpec("careos_get_day_plans", False, "Get active day-scoped plans for a patient."),
    ToolSpec("careos_get_recent_events", False, "Get caregiver dashboard recent events."),
    ToolSpec("careos_get_task_criticality", False, "Get caregiver dashboard task criticality."),
    ToolSpec("careos_get_today", False, "Get patient's today timeline."),
    ToolSpec("careos_get_status", False, "Get patient status counts/adherence."),
    ToolSpec("careos_get_timeline", False, "Get today's timeline entries."),
    ToolSpec("careos_get_adherence_summary", False, "Get adherence summary."),
    ToolSpec("careos_list_care_plan_versions", False, "List care-plan version history."),
    ToolSpec("careos_list_care_plan_changes", False, "List care-plan change/audit history."),
    ToolSpec("careos_add_win", True, "Add a win definition and future instances."),
    ToolSpec("careos_update_win", True, "Update an existing win definition."),
    ToolSpec("careos_remove_win", True, "Remove/supersede a win definition."),
    ToolSpec("careos_complete_win", True, "Mark a win instance completed."),
    ToolSpec("careos_skip_win", True, "Mark a win instance skipped."),
    ToolSpec("careos_delay_win", True, "Delay a win instance by minutes."),
    ToolSpec("careos_escalate_win", True, "Escalate a win instance."),
]


_WRITE_DEDUPE: set[str] = set()


class ToolCallRequest(BaseModel):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolCallResponse(BaseModel):
    ok: bool
    tool: str
    result: dict[str, Any] | list[Any] | None = None
    error: str | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"service": "careos-lite-mcp", "status": "ok"}


@app.get("/mcp/tools")
def list_tools(x_mcp_api_key: str = Header(default="")) -> dict[str, Any]:
    if _mcp_api_key() and x_mcp_api_key != _mcp_api_key():
        raise HTTPException(status_code=401, detail="invalid mcp api key")
    return {
        "tools": [{"name": t.name, "write": t.write, "description": t.description} for t in TOOLS]
    }


@app.post("/mcp/call", response_model=ToolCallResponse)
def call_tool(payload: ToolCallRequest, x_mcp_api_key: str = Header(default="")) -> ToolCallResponse:
    if _mcp_api_key() and x_mcp_api_key != _mcp_api_key():
        raise HTTPException(status_code=401, detail="invalid mcp api key")

    tool = payload.tool.strip()
    args = payload.arguments
    spec = next((t for t in TOOLS if t.name == tool), None)
    if spec is None:
        return ToolCallResponse(ok=False, tool=tool, error=f"unknown tool '{tool}'")
    try:
        if spec.write:
            result = _write_tool(tool, args)
        else:
            result = _read_tool(tool, args)
        return ToolCallResponse(ok=True, tool=tool, result=result)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive fallback for transport/runtime failures
        return ToolCallResponse(ok=False, tool=tool, error=str(exc))
