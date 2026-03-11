#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from careos.db.connection import get_connection


@dataclass
class Context:
    api_base: str
    database_url: str


def _normalize_whatsapp(phone: str) -> str:
    raw = phone.strip()
    if raw.lower().startswith("whatsapp:"):
        raw = raw.split(":", 1)[1].strip()
    return f"whatsapp:{raw}"


def _api_request(ctx: Context, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = Request(f"{ctx.api_base}{path}", data=body, method=method, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: {exc.code} {detail}") from exc


def _tenant_by_name(database_url: str, tenant_name: str) -> str | None:
    sql = """
    SELECT id
    FROM tenants
    WHERE name = %s
    ORDER BY created_at DESC
    LIMIT 1
    """
    with get_connection(database_url) as conn, conn.cursor() as cur:
        cur.execute(sql, (tenant_name,))
        row = cur.fetchone()
        return str(row[0]) if row else None


def _ensure_tenant(ctx: Context, tenant_cfg: dict[str, Any]) -> tuple[str, str]:
    tenant_id = str(tenant_cfg.get("id") or "").strip()
    tenant_name = str(tenant_cfg.get("name") or "Family Tenant").strip()
    tenant_timezone = str(tenant_cfg.get("timezone") or "Asia/Kolkata").strip()
    if tenant_id:
        return tenant_id, tenant_timezone

    existing_id = _tenant_by_name(ctx.database_url, tenant_name)
    if existing_id:
        return existing_id, tenant_timezone

    created = _api_request(
        ctx,
        "POST",
        "/tenants",
        {"name": tenant_name, "type": "family", "timezone": tenant_timezone, "status": "active"},
    )
    return str(created["id"]), tenant_timezone


def _participant_by_phone(database_url: str, tenant_id: str, phone_number: str) -> tuple[str, str] | None:
    sql = """
    SELECT id, role
    FROM participants
    WHERE tenant_id = %s AND phone_number = %s
    ORDER BY created_at DESC
    LIMIT 1
    """
    with get_connection(database_url) as conn, conn.cursor() as cur:
        cur.execute(sql, (tenant_id, phone_number))
        row = cur.fetchone()
        if not row:
            return None
        return str(row[0]), str(row[1])


def _set_participant_active(database_url: str, participant_id: str) -> None:
    with get_connection(database_url) as conn, conn.cursor() as cur:
        cur.execute("UPDATE participants SET active = true WHERE id = %s", (participant_id,))


def _ensure_participant(
    ctx: Context,
    *,
    tenant_id: str,
    role: str,
    display_name: str,
    phone_number: str,
) -> str:
    existing = _participant_by_phone(ctx.database_url, tenant_id, phone_number)
    if existing:
        participant_id, existing_role = existing
        if existing_role != role:
            raise RuntimeError(
                f"phone {phone_number} already exists as role={existing_role}; expected role={role} for bootstrap"
            )
        _set_participant_active(ctx.database_url, participant_id)
        return participant_id

    created = _api_request(
        ctx,
        "POST",
        "/participants",
        {
            "tenant_id": tenant_id,
            "role": role,
            "display_name": display_name,
            "phone_number": phone_number,
            "preferred_channel": "whatsapp",
            "preferred_language": "en",
            "active": True,
        },
    )
    return str(created["id"])


def _latest_linked_patient(database_url: str, participant_id: str) -> str | None:
    sql = """
    SELECT patient_id
    FROM caregiver_patient_links
    WHERE caregiver_participant_id = %s
    ORDER BY id DESC
    LIMIT 1
    """
    with get_connection(database_url) as conn, conn.cursor() as cur:
        cur.execute(sql, (participant_id,))
        row = cur.fetchone()
        return str(row[0]) if row else None


def _patient_by_name(database_url: str, tenant_id: str, display_name: str) -> str | None:
    sql = """
    SELECT id
    FROM patients
    WHERE tenant_id = %s AND display_name = %s
    ORDER BY created_at DESC
    LIMIT 1
    """
    with get_connection(database_url) as conn, conn.cursor() as cur:
        cur.execute(sql, (tenant_id, display_name))
        row = cur.fetchone()
        return str(row[0]) if row else None


def _ensure_patient(
    ctx: Context,
    *,
    tenant_id: str,
    patient_participant_id: str,
    display_name: str,
    timezone_name: str,
    persona_type: str,
) -> str:
    linked = _latest_linked_patient(ctx.database_url, patient_participant_id)
    if linked:
        return linked

    existing = _patient_by_name(ctx.database_url, tenant_id, display_name)
    if existing:
        return existing

    created = _api_request(
        ctx,
        "POST",
        "/patients",
        {
            "tenant_id": tenant_id,
            "display_name": display_name,
            "timezone": timezone_name,
            "primary_language": "en",
            "persona_type": persona_type,
            "risk_level": "medium",
            "status": "active",
        },
    )
    return str(created["id"])


def _ensure_caregiver_link(database_url: str, caregiver_participant_id: str, patient_id: str, relationship: str) -> None:
    sql = """
    INSERT INTO caregiver_patient_links
      (caregiver_participant_id, patient_id, relationship, notification_policy, can_edit_plan)
    SELECT %s, %s, %s, '{}'::jsonb, true
    WHERE NOT EXISTS (
      SELECT 1 FROM caregiver_patient_links
      WHERE caregiver_participant_id = %s AND patient_id = %s
    )
    """
    with get_connection(database_url) as conn, conn.cursor() as cur:
        cur.execute(sql, (caregiver_participant_id, patient_id, relationship, caregiver_participant_id, patient_id))


def _set_active_context(database_url: str, participant_id: str, patient_id: str, source: str) -> None:
    sql = """
    INSERT INTO participant_active_context (participant_id, patient_id, selection_source)
    VALUES (%s, %s, %s)
    ON CONFLICT (participant_id)
    DO UPDATE SET
      patient_id = EXCLUDED.patient_id,
      updated_at = now(),
      selection_source = EXCLUDED.selection_source
    """
    with get_connection(database_url) as conn, conn.cursor() as cur:
        cur.execute(sql, (participant_id, patient_id, source))


def _complete_any_active_onboarding(database_url: str, phone_number: str) -> None:
    sql = """
    UPDATE onboarding_sessions
    SET status = 'completed',
        state = 'completed',
        completion_note = CASE
          WHEN completion_note = '' THEN 'bootstrap_completed'
          ELSE completion_note
        END,
        completed_at = COALESCE(completed_at, now()),
        updated_at = now()
    WHERE phone_number = %s
      AND status = 'active'
    """
    with get_connection(database_url) as conn, conn.cursor() as cur:
        cur.execute(sql, (phone_number,))


def _activate_setup_session(database_url: str, phone_number: str, participant_id: str, patient_id: str, source: str) -> None:
    sql = """
    INSERT INTO onboarding_sessions
      (phone_number, state, status, data, expires_at, completion_note)
    VALUES
      (%s, 'setup_menu', 'active', %s::jsonb, now() + interval '24 hours', '')
    ON CONFLICT (phone_number)
    DO UPDATE SET
      state = 'setup_menu',
      status = 'active',
      data = EXCLUDED.data,
      expires_at = EXCLUDED.expires_at,
      completion_note = '',
      updated_at = now()
    """
    data = json.dumps(
        {
            "setup_state": "menu",
            "setup_patient_id": patient_id,
            "setup_participant_id": participant_id,
            "setup_source": source,
        }
    )
    with get_connection(database_url) as conn, conn.cursor() as cur:
        cur.execute(sql, (phone_number, data))


def _latest_care_plan_id(database_url: str, patient_id: str) -> str | None:
    sql = """
    SELECT id
    FROM care_plans
    WHERE patient_id = %s
    ORDER BY created_at DESC
    LIMIT 1
    """
    with get_connection(database_url) as conn, conn.cursor() as cur:
        cur.execute(sql, (patient_id,))
        row = cur.fetchone()
        return str(row[0]) if row else None


def _ensure_care_plan(ctx: Context, patient_id: str, created_by_participant_id: str) -> str:
    existing = _latest_care_plan_id(ctx.database_url, patient_id)
    if existing:
        return existing
    created = _api_request(
        ctx,
        "POST",
        "/care-plans",
        {
            "patient_id": patient_id,
            "created_by_participant_id": created_by_participant_id,
            "status": "active",
            "version": 1,
            "source_type": "manual",
        },
    )
    return str(created["id"])


def _active_definition_ids(database_url: str, care_plan_id: str) -> list[str]:
    sql = """
    SELECT DISTINCT wd.id
    FROM win_definitions wd
    JOIN win_instances wi ON wi.win_definition_id = wd.id
    WHERE wd.care_plan_id = %s
      AND wi.current_state <> 'superseded'
    """
    with get_connection(database_url) as conn, conn.cursor() as cur:
        cur.execute(sql, (care_plan_id,))
        return [str(row[0]) for row in cur.fetchall()]


def _criticality(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"critical", "high"}:
        return "high"
    if normalized in {"important", "medium"}:
        return "medium"
    return "low"


def _flexibility(is_medication: bool, criticality: str) -> str:
    if is_medication and criticality == "high":
        return "rigid"
    if criticality in {"high", "medium"}:
        return "windowed"
    return "flexible"


def _category(raw: str, is_medication: bool) -> str:
    if is_medication:
        return "medication"
    mapping = {
        "meal": "meal",
        "activity": "movement",
        "physio": "therapy",
        "wound_care": "therapy",
        "vitals_check": "vitals",
        "test": "lab",
        "hydration": "movement",
        "symptom_check": "mood",
        "sleep": "sleep",
        "appointment": "appointment",
    }
    return mapping.get(raw.strip().lower(), "movement")


def _recurrence(frequency: str) -> str:
    normalized = frequency.strip().lower()
    if normalized == "weekly":
        return "weekly"
    if normalized in {"daily", "every_day", "everyday"}:
        return "daily"
    return "one_off"


def _next_seed(time_str: str, timezone_name: str) -> tuple[datetime, datetime]:
    tz = ZoneInfo(timezone_name)
    now_local = datetime.now(tz)
    hour, minute = [int(part) for part in time_str.split(":", 1)]
    start_local = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if start_local <= now_local:
        start_local = start_local + timedelta(days=1)
    end_local = start_local + timedelta(minutes=30)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def _import_plan(
    ctx: Context,
    *,
    patient_id: str,
    actor_id: str,
    care_plan_id: str,
    timezone_name: str,
    plan_data: dict[str, Any],
    replace_existing: bool,
) -> int:
    if replace_existing:
        for definition_id in _active_definition_ids(ctx.database_url, care_plan_id):
            _api_request(
                ctx,
                "DELETE",
                f"/care-plans/{care_plan_id}/wins/{definition_id}",
                {
                    "actor_participant_id": actor_id,
                    "reason": "bootstrap replace existing",
                    "supersede_active_due": True,
                },
            )

    imported = 0
    tz = ZoneInfo(timezone_name)
    for med in list(plan_data.get("medications", [])):
        title = str(med.get("display_name") or med.get("medication_name") or "Medication")
        instructions = str(med.get("dose_instructions") or "Take as directed")
        why = str(med.get("monitoring_notes") or "")
        criticality = _criticality(str(med.get("criticality_level") or med.get("priority") or "medium"))
        flexibility = _flexibility(True, criticality)
        frequency = _recurrence(str(med.get("frequency") or "daily"))
        schedule = str(med.get("scheduled_time") or "09:00")
        start_utc, end_utc = _next_seed(schedule, timezone_name)
        recurrence_days = [start_utc.astimezone(tz).weekday()] if frequency == "weekly" else []

        _api_request(
            ctx,
            "POST",
            f"/care-plans/{care_plan_id}/wins/add",
            {
                "actor_participant_id": actor_id,
                "reason": "bootstrap import medication",
                "patient_id": patient_id,
                "definition": {
                    "category": "medication",
                    "title": title,
                    "instructions": instructions,
                    "why_it_matters": why,
                    "criticality": criticality,
                    "flexibility": flexibility,
                    "recurrence_type": frequency,
                    "recurrence_interval": 1,
                    "recurrence_days_of_week": recurrence_days,
                    "default_channel_policy": {},
                    "escalation_policy": {},
                },
                "future_instances": [
                    {"scheduled_start": start_utc.isoformat(), "scheduled_end": end_utc.isoformat()},
                ],
            },
        )
        imported += 1

    for act in list(plan_data.get("care_activities", [])):
        title = str(act.get("title") or "Care activity")
        instructions = str(act.get("instruction") or "Complete activity")
        why = str(act.get("escalation_policy") or "")
        criticality = _criticality(str(act.get("priority") or "medium"))
        flexibility = _flexibility(False, criticality)
        frequency = _recurrence(str(act.get("frequency") or "daily"))
        schedule = str(act.get("schedule") or "09:00")
        duration = max(int(act.get("duration_minutes") or 30), 5)
        start_utc, _ = _next_seed(schedule, timezone_name)
        end_utc = start_utc + timedelta(minutes=duration)
        recurrence_days = [start_utc.astimezone(tz).weekday()] if frequency == "weekly" else []

        _api_request(
            ctx,
            "POST",
            f"/care-plans/{care_plan_id}/wins/add",
            {
                "actor_participant_id": actor_id,
                "reason": "bootstrap import activity",
                "patient_id": patient_id,
                "definition": {
                    "category": _category(str(act.get("category") or "movement"), False),
                    "title": title,
                    "instructions": instructions,
                    "why_it_matters": why,
                    "criticality": criticality,
                    "flexibility": flexibility,
                    "recurrence_type": frequency,
                    "recurrence_interval": 1,
                    "recurrence_days_of_week": recurrence_days,
                    "default_channel_policy": {},
                    "escalation_policy": {},
                },
                "future_instances": [
                    {"scheduled_start": start_utc.isoformat(), "scheduled_end": end_utc.isoformat()},
                ],
            },
        )
        imported += 1
    return imported


def _load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise RuntimeError("manifest must be a JSON object")
    if not isinstance(data.get("patients"), list) or not data["patients"]:
        raise RuntimeError("manifest.patients must be a non-empty list")
    return data


def _resolve_plan_path(manifest_path: Path, value: str) -> Path:
    raw = Path(value).expanduser()
    if raw.is_absolute():
        return raw
    return (manifest_path.parent / raw).resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap many patients with preloaded care plans.")
    parser.add_argument("--manifest", required=True, help="Path to JSON manifest file.")
    parser.add_argument("--api-base", default="http://127.0.0.1:8115", help="CareOS API base URL.")
    parser.add_argument("--replace-existing", action="store_true", help="Supersede active plan items before import.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    database_url = os.getenv("CAREOS_DATABASE_URL", "").strip()
    if not database_url:
        print("ERROR: CAREOS_DATABASE_URL is required in environment.", file=sys.stderr)
        return 1

    manifest_path = Path(args.manifest).expanduser().resolve()
    if not manifest_path.exists():
        print(f"ERROR: manifest file not found: {manifest_path}", file=sys.stderr)
        return 1

    manifest = _load_manifest(manifest_path)
    ctx = Context(api_base=args.api_base.rstrip("/"), database_url=database_url)

    tenant_id, default_timezone = _ensure_tenant(ctx, manifest.get("tenant", {}))
    print(f"tenant_id={tenant_id}")

    for item in manifest["patients"]:
        patient_name = str(item.get("patient_name") or "").strip()
        patient_phone_raw = str(item.get("patient_phone") or "").strip()
        caregiver_name = str(item.get("caregiver_name") or "").strip()
        caregiver_phone_raw = str(item.get("caregiver_phone") or "").strip()
        plan_json = str(item.get("plan_json") or "").strip()
        if not patient_name or not patient_phone_raw or not caregiver_name or not caregiver_phone_raw or not plan_json:
            raise RuntimeError("each patient item needs patient_name, patient_phone, caregiver_name, caregiver_phone, plan_json")

        patient_phone = _normalize_whatsapp(patient_phone_raw)
        caregiver_phone = _normalize_whatsapp(caregiver_phone_raw)
        timezone_name = str(item.get("timezone") or default_timezone or "Asia/Kolkata")
        persona_type = str(item.get("persona_type") or "caregiver_managed_elder")
        relationship = str(item.get("relationship") or "family")
        replace_existing = bool(item.get("replace_existing", args.replace_existing))
        enable_setup_menu = bool(item.get("enable_setup_menu", False))

        plan_path = _resolve_plan_path(manifest_path, plan_json)
        if not plan_path.exists():
            raise RuntimeError(f"plan file not found for {patient_name}: {plan_path}")

        payload = json.loads(plan_path.read_text())
        workflow = dict(payload.get("plan", {}))

        caregiver_participant_id = _ensure_participant(
            ctx,
            tenant_id=tenant_id,
            role="caregiver",
            display_name=caregiver_name,
            phone_number=caregiver_phone,
        )
        patient_participant_id = _ensure_participant(
            ctx,
            tenant_id=tenant_id,
            role="patient",
            display_name=patient_name,
            phone_number=patient_phone,
        )
        patient_id = _ensure_patient(
            ctx,
            tenant_id=tenant_id,
            patient_participant_id=patient_participant_id,
            display_name=patient_name,
            timezone_name=timezone_name,
            persona_type=persona_type,
        )

        _ensure_caregiver_link(ctx.database_url, caregiver_participant_id, patient_id, relationship)
        _ensure_caregiver_link(ctx.database_url, patient_participant_id, patient_id, "self")
        _set_active_context(ctx.database_url, caregiver_participant_id, patient_id, "bootstrap_preload")
        _set_active_context(ctx.database_url, patient_participant_id, patient_id, "bootstrap_preload")
        _complete_any_active_onboarding(ctx.database_url, caregiver_phone)
        _complete_any_active_onboarding(ctx.database_url, patient_phone)
        if enable_setup_menu:
            _activate_setup_session(
                ctx.database_url,
                phone_number=patient_phone,
                participant_id=patient_participant_id,
                patient_id=patient_id,
                source="bootstrap_preload",
            )

        care_plan_id = _ensure_care_plan(ctx, patient_id, caregiver_participant_id)
        imported = _import_plan(
            ctx,
            patient_id=patient_id,
            actor_id=caregiver_participant_id,
            care_plan_id=care_plan_id,
            timezone_name=timezone_name,
            plan_data=workflow,
            replace_existing=replace_existing,
        )

        print(
            f"patient={patient_name} patient_id={patient_id} patient_participant_id={patient_participant_id} "
            f"caregiver_participant_id={caregiver_participant_id} care_plan_id={care_plan_id} imported={imported}"
        )

    print("bootstrap_done=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
