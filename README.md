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
- `CAREOS_VALIDATE_TWILIO_SIGNATURE=true|false` (default `true`)
- `CAREOS_PUBLIC_WEBHOOK_BASE_URL` (optional; recommended in production)
- `CAREOS_LOG_LEVEL` (default `INFO`)
- Full template: [.env.example](/Users/kumarmankala/code/Codex/Wellness-check/careos-lite/.env.example)

## Migration

Apply:

```bash
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0001_initial.sql
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

## Architecture doc

See [ARCHITECTURE.md](/Users/kumarmankala/code/Codex/Wellness-check/careos-lite/ARCHITECTURE.md).

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
