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
- MCP server for authenticated agent tool-calling (`Agent/OpenClaw -> MCP -> FastAPI`)
- Gateway app scaffold for external Twilio mediation (`Twilio -> Gateway -> CareOS`)
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
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0007_personalization_and_mediation.sql
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0008_person_identity_and_memberships.sql
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0009_patient_clinical_facts.sql
```
3. Review and install systemd units:
```bash
./scripts/install_systemd_units.sh
./scripts/install_systemd_units.sh --apply
```
4. Reload and start services:
```bash
sudo systemctl daemon-reload
sudo systemctl enable careos-lite-api careos-lite-scheduler careos-lite-mcp careos-lite-gateway
sudo systemctl start careos-lite-api careos-lite-scheduler careos-lite-mcp careos-lite-gateway
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
- `CAREOS_GATEWAY_MODE=disabled|external` (default `disabled`)
- `CAREOS_GATEWAY_CAREOS_BASE_URL` (default `http://127.0.0.1:8115`)
- `CAREOS_GATEWAY_DASHBOARD_BASE_URL` (default `http://127.0.0.1:8000`)
- `CAREOS_GATEWAY_OPENCLAW_BASE_URL` (optional upstream OpenClaw base URL)
- `CAREOS_GATEWAY_OPENCLAW_FALLBACK_PATH` (optional OpenClaw fallback path override)
- `CAREOS_GATEWAY_OPENCLAW_RESPONSES_PATH` (optional OpenClaw Responses API path, default `/v1/responses`)
- `CAREOS_GATEWAY_OPENCLAW_TOKEN` (Bearer token for OpenClaw gateway HTTP auth)
- `CAREOS_GATEWAY_PENDING_ACTION_TTL_MINUTES` (default `10`)
- `CAREOS_GATEWAY_CONVERSATION_MODE` (`openclaw_first` or `deterministic_first`)
- `CAREOS_LOG_LEVEL` (default `INFO`)
- `CAREOS_MCP_API_KEY` (required when exposing MCP)
- `CAREOS_MCP_CAREOS_BASE_URL` (default `http://127.0.0.1:8115`)
- `CAREOS_MCP_ALLOWED_WRITE_ROLES` (default `caregiver,patient,clinician,admin`)
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
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0007_personalization_and_mediation.sql
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0008_person_identity_and_memberships.sql
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0009_patient_clinical_facts.sql
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

MCP endpoints:
- `GET /health` (on MCP service port)
- `GET /mcp/tools`
- `POST /mcp/call`

WhatsApp command additions for multi-patient caregiver flow:
- `patients`
- `switch`
- `use <n|patient_id>`
- `whoami` (now reports active context status)

Plain-English fallback mode:
- Keep deterministic commands as primary path.
- Set `CAREOS_CONVERSATION_ENGINE=openclaw` to enable fallback only when deterministic routing returns unknown command.
- `CAREOS_GATEWAY_MODE=disabled|external` controls whether Twilio is terminated directly by CareOS or by an external gateway service.
- Gateway NL mode is controlled by `CAREOS_GATEWAY_CONVERSATION_MODE`:
  - `openclaw_first` delegates to OpenClaw first, then falls back to deterministic on unavailable/error.
  - `deterministic_first` uses deterministic gateway parser only.
- FastAPI calls fallback endpoint: `POST {CAREOS_OPENCLAW_BASE_URL}/v1/careos/fallback`.
- `CAREOS_OPENCLAW_FALLBACK_PATH` overrides the default fallback path when needed.
- If fallback endpoints are unavailable, CareOS can call OpenClaw Responses HTTP (`/v1/responses`) using `CAREOS_OPENCLAW_GATEWAY_TOKEN` / `CAREOS_GATEWAY_OPENCLAW_TOKEN`.
- `careos-lite` now exposes a local bridge endpoint at `/v1/careos/fallback` that maps common plain-English requests to deterministic commands.
- Recommended VM setting for local bridge: `CAREOS_OPENCLAW_BASE_URL=http://127.0.0.1:8115`.
- External OpenClaw can still be used by pointing `CAREOS_OPENCLAW_BASE_URL` at that service URL.
- Compatibility mode tries multiple paths (`/v1/careos/fallback`, `/careos/fallback`, `/api/v1/careos/fallback`, `/v1/fallback`) and response shapes.
- For free-form LLM interpretation (instead of only rules), set:
  - `CAREOS_OPENAI_API_KEY`
  - `CAREOS_OPENAI_MODEL` (default `gpt-4o-mini`)
  - `CAREOS_OPENAI_TIMEOUT_SECONDS`
- If OpenClaw is unavailable/error, FastAPI returns the normal deterministic fallback text.

Gateway endpoints (new scaffold):
- `GET /health` (gateway service port)
- `POST /gateway/twilio/webhook`
- `POST /gateway/careos/events` (policy-bounded outbound mediation)

Single-webhook dashboard dispatch:
- Keep Twilio pointed at `POST /gateway/twilio/webhook`.
- The gateway now treats dashboard-like caregiver requests as a separate intent and issues a Care-Dash link through `CAREOS_GATEWAY_DASHBOARD_BASE_URL`.
- Supported phrasing is broader than the original exact command and includes requests resembling:
  - `show caregiver dashboard`
  - `patient summary`
  - `show patient status`
  - typo variants close to `dashboard`

Twilio cutover:
- direct mode: `/twilio/webhook`
- gateway mode: `/gateway/twilio/webhook`

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

Product and engineering backlog:
[BACKLOG.md](BACKLOG.md)

Lightweight implementation process:
[IMPLEMENTATION_PIPELINE.md](IMPLEMENTATION_PIPELINE.md)

DB reset helper:
- `scripts/reset_db.sh` (safe review mode by default; use `--apply` to execute)

## Control-plane rule

The deployment path remains:
`Twilio -> FastAPI -> services/policy/conversation -> Twilio`.
The conversation engine is intentionally behind FastAPI and must not call Twilio directly.
Agent path is:
`Agent/OpenClaw -> MCP server -> FastAPI -> services/policy/conversation -> Postgres`.

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
