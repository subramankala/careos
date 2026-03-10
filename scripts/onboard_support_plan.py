#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from careos.db.connection import get_connection


@dataclass
class Context:
    api_base: str
    database_url: str


def _normalize_whatsapp(phone: str) -> str:
    text = phone.strip()
    if text.lower().startswith("whatsapp:"):
        return f"whatsapp:{text.split(':', 1)[1]}"
    return f"whatsapp:{text}"


def _api_request(ctx: Context, method: str, path: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = Request(f"{ctx.api_base}{path}", data=body, method=method, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: {exc.code} {detail}") from exc


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


def _participant_by_phone(database_url: str, phone_number: str, tenant_id: str) -> str | None:
    sql = """
    SELECT id
    FROM participants
    WHERE phone_number = %s AND tenant_id = %s
    ORDER BY created_at DESC
    LIMIT 1
    """
    with get_connection(database_url) as conn, conn.cursor() as cur:
        cur.execute(sql, (phone_number, tenant_id))
        row = cur.fetchone()
        return str(row[0]) if row else None


def _set_participant_active(database_url: str, participant_id: str) -> None:
    with get_connection(database_url) as conn, conn.cursor() as cur:
        cur.execute("UPDATE participants SET active = true WHERE id = %s", (participant_id,))


def _link_participant_to_patient_only(database_url: str, participant_id: str, patient_id: str) -> None:
    with get_connection(database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM caregiver_patient_links WHERE caregiver_participant_id = %s AND patient_id <> %s",
            (participant_id, patient_id),
        )


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


def _ensure_tenant(ctx: Context, *, tenant_id: str | None, tenant_name: str, timezone_name: str) -> str:
    if tenant_id:
        return tenant_id
    created = _api_request(
        ctx,
        "POST",
        "/tenants",
        {"name": tenant_name, "type": "family", "timezone": timezone_name, "status": "active"},
    )
    return str(created["id"])


def _ensure_patient(
    ctx: Context,
    *,
    tenant_id: str,
    patient_id: str | None,
    display_name: str,
    timezone_name: str,
    persona_type: str,
) -> str:
    if patient_id:
        return patient_id
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


def _ensure_participant(
    ctx: Context,
    *,
    tenant_id: str,
    display_name: str,
    phone_number: str,
) -> str:
    existing = _participant_by_phone(ctx.database_url, phone_number, tenant_id)
    if existing:
        _set_participant_active(ctx.database_url, existing)
        return existing
    created = _api_request(
        ctx,
        "POST",
        "/participants",
        {
            "tenant_id": tenant_id,
            "role": "caregiver",
            "display_name": display_name,
            "phone_number": phone_number,
            "preferred_channel": "whatsapp",
            "preferred_language": "en",
            "active": True,
        },
    )
    return str(created["id"])


def _ensure_care_plan(ctx: Context, *, patient_id: str, actor_id: str, care_plan_id: str | None) -> str:
    if care_plan_id:
        return care_plan_id
    existing = _latest_care_plan_id(ctx.database_url, patient_id)
    if existing:
        return existing
    created = _api_request(
        ctx,
        "POST",
        "/care-plans",
        {
            "patient_id": patient_id,
            "created_by_participant_id": actor_id,
            "status": "active",
            "version": 1,
            "source_type": "manual",
        },
    )
    return str(created["id"])


def _add_or_update_plan(
    ctx: Context,
    *,
    plan_data: dict,
    patient_id: str,
    actor_id: str,
    care_plan_id: str,
    timezone_name: str,
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
                    "reason": "support plan re-import",
                    "supersede_active_due": True,
                },
            )

    count = 0
    medications = list(plan_data.get("medications", []))
    activities = list(plan_data.get("care_activities", []))

    for med in medications:
        title = str(med.get("display_name") or med.get("medication_name") or "Medication")
        instructions = str(med.get("dose_instructions") or "Take as directed")
        why = str(med.get("monitoring_notes") or "")
        criticality = _criticality(str(med.get("criticality_level") or med.get("priority") or "medium"))
        flexibility = _flexibility(True, criticality)
        frequency = _recurrence(str(med.get("frequency") or "daily"))
        schedule = str(med.get("scheduled_time") or "09:00")
        start_utc, end_utc = _next_seed(schedule, timezone_name)
        recurrence_days = [start_utc.astimezone(ZoneInfo(timezone_name)).weekday()] if frequency == "weekly" else []

        _api_request(
            ctx,
            "POST",
            f"/care-plans/{care_plan_id}/wins/add",
            {
                "actor_participant_id": actor_id,
                "reason": "support plan import",
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
        count += 1

    for act in activities:
        title = str(act.get("title") or "Care activity")
        instructions = str(act.get("instruction") or "Complete activity")
        why = str(act.get("escalation_policy") or "")
        criticality = _criticality(str(act.get("priority") or "medium"))
        flexibility = _flexibility(False, criticality)
        frequency = _recurrence(str(act.get("frequency") or "daily"))
        schedule = str(act.get("schedule") or "09:00")
        duration = int(act.get("duration_minutes") or 30)
        start_utc, _ = _next_seed(schedule, timezone_name)
        end_utc = start_utc + timedelta(minutes=max(duration, 5))
        recurrence_days = [start_utc.astimezone(ZoneInfo(timezone_name)).weekday()] if frequency == "weekly" else []

        _api_request(
            ctx,
            "POST",
            f"/care-plans/{care_plan_id}/wins/add",
            {
                "actor_participant_id": actor_id,
                "reason": "support plan import",
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
        count += 1
    return count


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="One-command onboarding/import for CareOS support-plan JSON.")
    parser.add_argument("--plan-json", required=True, help="Path to support-plan JSON file.")
    parser.add_argument("--api-base", default="http://127.0.0.1:8115", help="CareOS API base URL.")
    parser.add_argument("--tenant-id", default="", help="Existing tenant ID. If omitted, a tenant is created.")
    parser.add_argument("--tenant-name", default="Family Tenant", help="Tenant name when creating a new tenant.")
    parser.add_argument("--patient-id", default="", help="Existing patient ID to update instead of creating.")
    parser.add_argument("--care-plan-id", default="", help="Existing care plan ID to update.")
    parser.add_argument("--caregiver-phone", default="", help="Caregiver WhatsApp phone (E.164).")
    parser.add_argument("--caregiver-name", default="", help="Caregiver display name override.")
    parser.add_argument("--patient-name", default="", help="Patient display name override.")
    parser.add_argument("--timezone", default="", help="Timezone override.")
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="Supersede currently active instances in target care plan before importing.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    database_url = os.getenv("CAREOS_DATABASE_URL", "").strip()
    if not database_url:
        print("ERROR: CAREOS_DATABASE_URL is required in environment.", file=sys.stderr)
        return 1

    plan_path = Path(args.plan_json).expanduser().resolve()
    if not plan_path.exists():
        print(f"ERROR: plan file not found: {plan_path}", file=sys.stderr)
        return 1
    plan_obj = json.loads(plan_path.read_text())
    patient_obj = dict(plan_obj.get("patient", {}))
    workflow = dict(plan_obj.get("plan", {}))

    timezone_name = str(args.timezone or patient_obj.get("timezone") or workflow.get("timezone") or "UTC")
    patient_name = str(args.patient_name or patient_obj.get("display_name") or "Patient")
    caregiver_name = str(args.caregiver_name or patient_obj.get("caregiver_name") or "Primary Caregiver")
    caregiver_phone = _normalize_whatsapp(str(args.caregiver_phone or patient_obj.get("caregiver_contact") or ""))
    if caregiver_phone == "whatsapp:":
        print("ERROR: caregiver phone is required (--caregiver-phone or patient.caregiver_contact).", file=sys.stderr)
        return 1

    ctx = Context(api_base=args.api_base.rstrip("/"), database_url=database_url)
    tenant_id = _ensure_tenant(
        ctx,
        tenant_id=args.tenant_id.strip() or None,
        tenant_name=args.tenant_name,
        timezone_name=timezone_name,
    )
    patient_id = _ensure_patient(
        ctx,
        tenant_id=tenant_id,
        patient_id=args.patient_id.strip() or None,
        display_name=patient_name,
        timezone_name=timezone_name,
        persona_type="caregiver_managed_elder",
    )
    participant_id = _ensure_participant(
        ctx,
        tenant_id=tenant_id,
        display_name=caregiver_name,
        phone_number=caregiver_phone,
    )
    _api_request(
        ctx,
        "POST",
        "/caregiver-links",
        {
            "caregiver_participant_id": participant_id,
            "patient_id": patient_id,
            "relationship": "family",
            "notification_policy": {},
            "can_edit_plan": True,
        },
    )
    _link_participant_to_patient_only(ctx.database_url, participant_id, patient_id)
    care_plan_id = _ensure_care_plan(
        ctx,
        patient_id=patient_id,
        actor_id=participant_id,
        care_plan_id=args.care_plan_id.strip() or None,
    )

    imported_count = _add_or_update_plan(
        ctx,
        plan_data=workflow,
        patient_id=patient_id,
        actor_id=participant_id,
        care_plan_id=care_plan_id,
        timezone_name=timezone_name,
        replace_existing=args.replace_existing,
    )
    print("Imported.")
    print(f"tenant_id={tenant_id}")
    print(f"patient_id={patient_id}")
    print(f"caregiver_id={participant_id}")
    print(f"care_plan_id={care_plan_id}")
    print(f"wins_imported={imported_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
