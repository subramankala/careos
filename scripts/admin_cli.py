#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SESSION_PATH = Path.home() / ".careos-admin" / "session.json"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_PATH = REPO_ROOT / ".env"


def _load_dotenv() -> None:
    if not DEFAULT_ENV_PATH.exists():
        return
    for raw_line in DEFAULT_ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def _api_base() -> str:
    return (
        os.environ.get("CAREOS_ADMIN_API_BASE_URL")
        or os.environ.get("CAREOS_GATEWAY_CAREOS_BASE_URL")
        or "http://127.0.0.1:8115"
    ).rstrip("/")


def _expected_token() -> str:
    token = os.environ.get("CAREOS_ADMIN_CLI_TOKEN", "").strip()
    if not token:
        raise RuntimeError("CAREOS_ADMIN_CLI_TOKEN is not set. Source the CareOS .env first.")
    return token


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _read_session() -> dict[str, Any] | None:
    if not SESSION_PATH.exists():
        return None
    try:
        return json.loads(SESSION_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Admin session at {SESSION_PATH} is invalid. Delete it or run logout.") from exc


def _write_session(payload: dict[str, Any]) -> None:
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSION_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.chmod(SESSION_PATH, 0o600)


def _require_login() -> None:
    expected = _expected_token()
    session = _read_session()
    if session is None:
        raise RuntimeError("Not logged in. Run: python3 scripts/admin_cli.py login")
    if str(session.get("token_digest") or "") != _token_digest(expected):
        raise RuntimeError("Admin session no longer matches CAREOS_ADMIN_CLI_TOKEN. Log in again.")
    if str(session.get("api_base") or "") != _api_base():
        raise RuntimeError("Admin session API base no longer matches current environment. Log in again.")


def _api_request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    req = Request(f"{_api_base()}{path}", data=body, method=method, headers=headers)
    try:
        with urlopen(req, timeout=30) as resp:  # noqa: S310
            response_body = resp.read().decode("utf-8")
        return json.loads(response_body) if response_body else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: {exc.code} {detail}") from exc


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, default=str))


def _delete_plan(bundle: dict[str, Any]) -> dict[str, Any]:
    participant = dict(bundle.get("participant") or {})
    linked_patients = list(bundle.get("linked_patients") or [])
    patient_ids = [str(row.get("patient_id") or row.get("id") or "") for row in linked_patients if row]
    care_plans = list(bundle.get("care_plans") or [])
    care_plan_ids = [str(row.get("id") or "") for row in care_plans if row.get("id")]

    def _quoted_ids(values: list[str]) -> str:
        return ", ".join(f"'{value}'" for value in values if value)

    phone_number = str(participant.get("phone_number") or "")
    participant_id = str(participant.get("id") or "")
    sql_steps = ["BEGIN;"]
    sql_steps.append(f"DELETE FROM privacy_requests WHERE subject_participant_id = '{participant_id}' OR requested_by_participant_id = '{participant_id}';")
    sql_steps.append(f"DELETE FROM participant_feedback WHERE participant_id = '{participant_id}'" + (f" OR patient_id IN ({_quoted_ids(patient_ids)});" if patient_ids else ";"))
    sql_steps.append(f"DELETE FROM product_telemetry_events WHERE participant_id = '{participant_id}'" + (f" OR patient_id IN ({_quoted_ids(patient_ids)});" if patient_ids else ";"))
    sql_steps.append(f"DELETE FROM message_events WHERE participant_id = '{participant_id}'" + (f" OR patient_id IN ({_quoted_ids(patient_ids)});" if patient_ids else ";"))
    if phone_number:
        sql_steps.append(
            "DELETE FROM onboarding_sessions "
            f"WHERE regexp_replace(replace(phone_number, 'whatsapp:', ''), '[^0-9+]', '', 'g') = regexp_replace('{phone_number}', '[^0-9+]', '', 'g');"
        )
    if patient_ids:
        sql_steps.append(f"DELETE FROM patient_day_plans WHERE patient_id IN ({_quoted_ids(patient_ids)});")
        sql_steps.append(f"DELETE FROM patient_observations WHERE patient_id IN ({_quoted_ids(patient_ids)});")
        sql_steps.append(f"DELETE FROM patient_clinical_facts WHERE patient_id IN ({_quoted_ids(patient_ids)});")
        sql_steps.append(f"DELETE FROM win_instances WHERE patient_id IN ({_quoted_ids(patient_ids)});")
        if care_plan_ids:
            sql_steps.append(f"DELETE FROM win_definitions WHERE care_plan_id IN ({_quoted_ids(care_plan_ids)});")
            sql_steps.append(f"DELETE FROM care_plans WHERE id IN ({_quoted_ids(care_plan_ids)});")
        sql_steps.append(f"DELETE FROM caregiver_patient_links WHERE caregiver_participant_id = '{participant_id}' OR patient_id IN ({_quoted_ids(patient_ids)});")
        sql_steps.append(f"-- Review whether any other participants still need these patient records before deleting patients.")
        sql_steps.append(f"DELETE FROM patients WHERE id IN ({_quoted_ids(patient_ids)});")
    sql_steps.append(f"-- Review whether tenant cleanup is appropriate before deleting the participant.")
    sql_steps.append(f"DELETE FROM participants WHERE id = '{participant_id}';")
    sql_steps.append("COMMIT;")

    counts = {
        "linked_patients": len(linked_patients),
        "caregiver_links": len(bundle.get("caregiver_links") or []),
        "message_events": len(bundle.get("message_events") or []),
        "participant_feedback": len(bundle.get("participant_feedback") or []),
        "onboarding_sessions": len(bundle.get("onboarding_sessions") or []),
        "care_plans": len(care_plans),
        "win_definitions": len(bundle.get("win_definitions") or []),
        "win_instances": len(bundle.get("win_instances") or []),
        "patient_clinical_facts": len(bundle.get("patient_clinical_facts") or []),
        "patient_observations": len(bundle.get("patient_observations") or []),
        "patient_day_plans": len(bundle.get("patient_day_plans") or []),
        "privacy_requests": len(bundle.get("privacy_requests") or []),
    }
    return {
        "subject_participant_id": participant_id,
        "subject_phone_number": phone_number,
        "linked_patient_ids": patient_ids,
        "generated_at": datetime.now(UTC).isoformat(),
        "record_counts": counts,
        "warnings": [
            "This plan is generated from the exported bundle. Review carefully before executing.",
            "Hard deletion may conflict with legal retention, audit, or medical-record obligations.",
            "If other participants share the same patients or tenant, edit the SQL before running it.",
        ],
        "sql_steps": sql_steps,
    }


def _cmd_login(args: argparse.Namespace) -> int:
    token = args.token or getpass.getpass("Admin token: ")
    if token != _expected_token():
        raise RuntimeError("Invalid admin token.")
    _write_session(
        {
            "token_digest": _token_digest(token),
            "logged_in_at": datetime.now(UTC).isoformat(),
            "api_base": _api_base(),
        }
    )
    print(f"Logged in to CareOS admin CLI at {_api_base()}")
    return 0


def _cmd_logout(_args: argparse.Namespace) -> int:
    if SESSION_PATH.exists():
        SESSION_PATH.unlink()
    print("Logged out.")
    return 0


def _cmd_metrics_overview(args: argparse.Namespace) -> int:
    _require_login()
    query = {"days": int(args.days)}
    if args.patient_id:
        query["patient_id"] = args.patient_id
    payload = _api_request("GET", f"/internal/product-metrics/overview?{urlencode(query)}")
    _print_json(payload)
    return 0


def _cmd_feedback_list(args: argparse.Namespace) -> int:
    _require_login()
    query = {
        "participant_id": args.participant_id,
        "limit": int(args.limit),
    }
    payload = _api_request("GET", f"/internal/feedback?{urlencode(query)}")
    _print_json(payload)
    return 0


def _cmd_message_send(args: argparse.Namespace) -> int:
    _require_login()
    payload = _api_request(
        "POST",
        "/internal/admin/messages",
        {
            "participant_id": args.participant_id,
            "body": args.body,
            "patient_id": args.patient_id,
            "privacy_request_id": args.privacy_request_id,
            "operator_label": args.operator_label,
        },
    )
    _print_json(payload)
    return 0


def _cmd_privacy_requests_list(args: argparse.Namespace) -> int:
    _require_login()
    query = {}
    if args.subject_participant_id:
        query["subject_participant_id"] = args.subject_participant_id
    suffix = f"?{urlencode(query)}" if query else ""
    payload = _api_request("GET", f"/internal/privacy/requests{suffix}")
    _print_json(payload)
    return 0


def _cmd_privacy_requests_create(args: argparse.Namespace) -> int:
    _require_login()
    payload = _api_request(
        "POST",
        "/internal/privacy/requests",
        {
            "request_type": args.request_type,
            "subject_participant_id": args.subject_participant_id,
            "requested_by_participant_id": args.requested_by_participant_id,
            "jurisdiction": args.jurisdiction,
            "reason": args.reason,
            "structured_context": {"source": "admin_cli"},
        },
    )
    _print_json(payload)
    return 0


def _cmd_privacy_export(args: argparse.Namespace) -> int:
    _require_login()
    payload = _api_request("GET", f"/internal/privacy/export?{urlencode({'subject_participant_id': args.subject_participant_id})}")
    if args.out:
        Path(args.out).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print(f"Wrote export bundle to {args.out}")
        return 0
    _print_json(payload)
    return 0


def _cmd_privacy_delete_plan(args: argparse.Namespace) -> int:
    _require_login()
    payload = _api_request("GET", f"/internal/privacy/export?{urlencode({'subject_participant_id': args.subject_participant_id})}")
    plan = _delete_plan(dict(payload.get("bundle") or {}))
    if args.out:
        Path(args.out).write_text(json.dumps(plan, indent=2, default=str), encoding="utf-8")
        print(f"Wrote delete plan to {args.out}")
        return 0
    _print_json(plan)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CareOS admin CLI for metrics, privacy workflows, and deletion planning.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    login = subparsers.add_parser("login", help="Authenticate locally using CAREOS_ADMIN_CLI_TOKEN.")
    login.add_argument("--token", help="Admin token. If omitted, prompt securely.")
    login.set_defaults(func=_cmd_login)

    logout = subparsers.add_parser("logout", help="Clear the local admin CLI session.")
    logout.set_defaults(func=_cmd_logout)

    message = subparsers.add_parser("message", help="Operator outbound messaging commands.")
    message_sub = message.add_subparsers(dest="message_command", required=True)
    message_send = message_sub.add_parser("send", help="Send a WhatsApp message to a participant.")
    message_send.add_argument("--participant-id", required=True)
    message_send.add_argument("--body", required=True)
    message_send.add_argument("--patient-id")
    message_send.add_argument("--privacy-request-id")
    message_send.add_argument("--operator-label", default="admin_cli")
    message_send.set_defaults(func=_cmd_message_send)

    metrics = subparsers.add_parser("metrics", help="Metrics monitoring commands.")
    metrics_sub = metrics.add_subparsers(dest="metrics_command", required=True)
    overview = metrics_sub.add_parser("overview", help="Show product metrics overview.")
    overview.add_argument("--days", type=int, default=30)
    overview.add_argument("--patient-id")
    overview.set_defaults(func=_cmd_metrics_overview)

    feedback = subparsers.add_parser("feedback", help="Participant feedback review commands.")
    feedback_sub = feedback.add_subparsers(dest="feedback_command", required=True)
    feedback_list = feedback_sub.add_parser("list", help="List recent feedback for a participant.")
    feedback_list.add_argument("--participant-id", required=True)
    feedback_list.add_argument("--limit", type=int, default=20)
    feedback_list.set_defaults(func=_cmd_feedback_list)

    privacy = subparsers.add_parser("privacy", help="Privacy/admin operations.")
    privacy_sub = privacy.add_subparsers(dest="privacy_command", required=True)

    requests_parser = privacy_sub.add_parser("requests", help="List or create privacy requests.")
    requests_sub = requests_parser.add_subparsers(dest="requests_command", required=True)
    requests_list = requests_sub.add_parser("list", help="List privacy requests.")
    requests_list.add_argument("--subject-participant-id")
    requests_list.set_defaults(func=_cmd_privacy_requests_list)

    requests_create = requests_sub.add_parser("create", help="Create a privacy request.")
    requests_create.add_argument("--type", dest="request_type", required=True)
    requests_create.add_argument("--subject-participant-id", required=True)
    requests_create.add_argument("--requested-by-participant-id")
    requests_create.add_argument("--jurisdiction", default="")
    requests_create.add_argument("--reason", default="")
    requests_create.set_defaults(func=_cmd_privacy_requests_create)

    export_cmd = privacy_sub.add_parser("export", help="Export all known CareOS data for a participant.")
    export_cmd.add_argument("--subject-participant-id", required=True)
    export_cmd.add_argument("--out")
    export_cmd.set_defaults(func=_cmd_privacy_export)

    delete_plan = privacy_sub.add_parser("delete-plan", help="Generate a reviewable SQL delete plan from an export bundle.")
    delete_plan.add_argument("--subject-participant-id", required=True)
    delete_plan.add_argument("--out")
    delete_plan.set_defaults(func=_cmd_privacy_delete_plan)
    return parser


def main() -> int:
    _load_dotenv()
    parser = _build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
