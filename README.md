# CareOS Lite (Multi-Tenant Pilot)

Production-oriented, multi-tenant CareOS backend for WhatsApp + voice orchestration.

## What this repo includes

- FastAPI control plane (`Twilio -> FastAPI -> services -> Twilio`)
- Multi-tenant identity resolution by inbound sender phone number
- Postgres-first schema + SQL migration for tenant/patient/participant/care-plan/wins/messages/escalations
- Deterministic command router (`schedule`, `next`, `status`, `done`, `delay`, `skip`, `help`)
- Policy engine for criticality + flexibility + persona behavior
- Idempotent outbound message event logging
- Scheduler worker loop for due reminders + escalation checks
- Tests for patient isolation across shared business number traffic

## Quick start

```bash
cd /Users/kumarmankala/code/Codex/Wellness-check/careos-lite
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn careos.main:app --host 0.0.0.0 --port 8115 --reload
```

## One-command onboarding/import

Use the onboarding helper to create or update a patient from a support-plan JSON:

```bash
cd /Users/kumarmankala/code/Codex/Wellness-check/careos-lite
set -a; source .env; set +a
python3 scripts/onboard_support_plan.py \
  --plan-json /absolute/path/to/patient_daily_support_plan.json \
  --tenant-id <existing_tenant_id> \
  --caregiver-phone whatsapp:+919949353918
```

To refresh an existing patient's plan from a revised JSON:

```bash
python3 scripts/onboard_support_plan.py \
  --plan-json /absolute/path/to/patient_daily_support_plan.json \
  --tenant-id <tenant_id> \
  --patient-id <patient_id> \
  --care-plan-id <care_plan_id> \
  --caregiver-phone whatsapp:+919949353918 \
  --replace-existing
```

## Production VM setup order (no Docker)

1. Copy env template and fill values:
```bash
cp .env.example .env
```
2. Apply schema:
```bash
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0001_initial.sql
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0002_care_plan_deltas.sql
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0003_recurrence_support.sql
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0004_participant_active_context.sql
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0005_onboarding_sessions.sql
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0006_caregiver_verification_requests.sql
```
3. Review and install systemd units:
```bash
./scripts/install_systemd_units.sh
./scripts/install_systemd_units.sh --apply
```
4. Reload and start services:
```bash
sudo systemctl daemon-reload
sudo systemctl enable careos-lite-api careos-lite-scheduler
sudo systemctl start careos-lite-api careos-lite-scheduler
```
5. Verify:
```bash
curl -s http://127.0.0.1:8115/health
sudo systemctl status careos-lite-api --no-pager
sudo systemctl status careos-lite-scheduler --no-pager
```

## Env vars

- `CAREOS_DATABASE_URL` (required for Postgres mode, e.g. `postgresql://user:pass@host:5432/careos`)
- `CAREOS_USE_IN_MEMORY=true|false` (default `false`; set `true` for local quick testing)
- `CAREOS_TWILIO_AUTH_TOKEN` (required when signature validation is enabled)
- `CAREOS_TWILIO_ACCOUNT_SID` (required for proactive scheduler WhatsApp pushes)
- `CAREOS_TWILIO_WHATSAPP_NUMBER` (required for proactive scheduler WhatsApp pushes)
- `CAREOS_VALIDATE_TWILIO_SIGNATURE=true|false` (default `true`)
- `CAREOS_PUBLIC_WEBHOOK_BASE_URL` (optional; recommended in production)
- `CAREOS_ONBOARDING_SESSION_TTL_HOURS` (default `24`; WhatsApp onboarding session resume window)
- `CAREOS_ONBOARDING_VERIFICATION_TTL_HOURS` (default `48`; caregiver verification request expiry)
- `CAREOS_ENABLE_SCHEDULER_WHATSAPP_PUSH=true|false` (default `false`; opt-in)
- `CAREOS_LOG_LEVEL` (default `INFO`)
- Full template: [.env.example](/Users/kumarmankala/code/Codex/Wellness-check/careos-lite/.env.example)

## Migration

Apply:

```bash
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0001_initial.sql
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0002_care_plan_deltas.sql
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0003_recurrence_support.sql
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0004_participant_active_context.sql
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0005_onboarding_sessions.sql
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0006_caregiver_verification_requests.sql
```

## Core endpoints

- `POST /twilio/webhook`
- `POST /patients`
- `POST /participants`
- `POST /care-plans`
- `PATCH /care-plans/{id}`
- `POST /care-plans/{id}/wins`
- `POST /care-plans/{id}/wins/add`
- `PATCH /care-plans/{id}/wins/{win_definition_id}`
- `DELETE /care-plans/{id}/wins/{win_definition_id}`
- `GET /care-plans/{id}/versions`
- `GET /care-plans/{id}/changes`
- `GET /patients/{id}/today`
- `GET /patients/{id}/status`
- `GET /patients/{id}/timeline`
- `POST /wins/{id}/complete`
- `POST /wins/{id}/delay`
- `POST /wins/{id}/skip`
- `POST /wins/{id}/escalate`
- `GET /patients/{id}/adherence-summary`

WhatsApp command additions for multi-patient caregiver flow:
- `patients`
- `switch`
- `use <n|patient_id>`
- `whoami` (now reports active context status)

WhatsApp onboarding (unknown/incomplete sender):
- entry asks: `myself` or `someone I care for`
- self flow captures patient name and completes profile creation
- caregiver flow captures caregiver name, patient name, patient phone, relationship and enters verification-pending state
- patient must reply `APPROVE <code>` or `DECLINE <code>` before caregiver link is activated
- caregiver can use `status`, `resend`, `cancel` while verification is pending
- after self-onboarding or caregiver approval, setup continues to a compact menu:
  - `1` add medications
  - `2` add appointments
  - `3` add routines
  - `4` finish for now

## Architecture doc

See [ARCHITECTURE.md](/Users/kumarmankala/code/Codex/Wellness-check/careos-lite/ARCHITECTURE.md).
Implemented behavior reference:
[IMPLEMENTED_SPEC.md](/Users/kumarmankala/code/Codex/Wellness-check/careos-lite/IMPLEMENTED_SPEC.md)

## Operations runbook

Reusable onboarding and cleanup commands:
[OPERATIONS_RUNBOOK.md](/Users/kumarmankala/code/Codex/Wellness-check/careos-lite/OPERATIONS_RUNBOOK.md)

DB reset helper:
- `scripts/reset_db.sh` (safe review mode by default; use `--apply` to execute)

## Control-plane rule

The deployment path remains:
`Twilio -> FastAPI -> services/policy/conversation -> Twilio`.
The conversation engine is intentionally behind FastAPI and must not call Twilio directly.

## Pilot safety notes

- Twilio signature verification is fail-closed when enabled (`CAREOS_VALIDATE_TWILIO_SIGNATURE=true`).
- Inbound webhook retries are idempotent by `MessageSid`; duplicate inbound payloads are ignored.
- Scheduler reminder writes are idempotent by win instance + scheduled slot to prevent double-send on accidental dual workers.
- Timeline day boundaries are computed in patient timezone before querying UTC ranges.
- Identity resolution fails closed for ambiguous caregiver-to-patient mappings (multiple linked patients on one sender number).

## Care plan delta edit rules

- By default, delta edits affect only future instances (`scheduled_start > now`).
- Historical completed instances are never modified.
- Active/due instances are preserved by default; set `supersede_active_due=true` to supersede them with audit trace.
- Superseded instances are represented by `current_state='superseded'` plus supersede metadata in storage.
- Recurrence is configured on win definitions:
  - `recurrence_type`: `one_off | daily | weekly`
  - `recurrence_interval`: integer cadence
  - `recurrence_days_of_week`: optional list for weekly (`0=Mon..6=Sun`)
  - `recurrence_until`: optional stop date
  - seed schedule is inferred from the first provided instance.
