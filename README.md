# CareOS Lite

Production-oriented CareOS backend for WhatsApp-first care coordination, grounded OpenClaw conversations, patient context, and care-team management.

## What this repo includes

- FastAPI API service for care plans, timelines, adherence, internal APIs, and MCP-backed operations
- WhatsApp gateway for Twilio mediation, onboarding, deterministic commands, structured action planning, and OpenClaw-grounded conversations
- Postgres-first schema and SQL migrations for identities, care plans, wins, message events, patient context, and care-team state
- Deterministic WhatsApp flows for schedule/status/done/delay plus medication edit/delete
- Patient context capture for:
  - durable clinical facts with `remember`, `facts`, `forget`
  - short-lived observations with `note`, `observations`
  - day-scoped plans with `plan`, `plans`, `forget plan`
- Care team management for:
  - explicit team memberships
  - category-level responsibility assignments
  - WhatsApp commands `team`, `assign ...`, `who handles ...`
- OpenClaw grounding with active medications, PRNs, patient context, and MCP tool hints
- Scheduler worker and policy engine for due reminders and escalation checks
- MCP server for authenticated agent tool-calling (`Agent/OpenClaw -> MCP -> CareOS API`)

## Quick start

```bash
cd /home/kumarmankala/careos
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn careos.main:app --host 0.0.0.0 --port 8115 --reload
```

## One-command onboarding/import

Use the onboarding helper to create or update a patient from a support-plan JSON:

```bash
cd /home/kumarmankala/careos
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
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0010_patient_observations.sql
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0011_patient_day_plans.sql
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0012_care_team_memberships.sql
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0013_care_responsibility_assignments.sql
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
- Full template: [.env.example](/home/kumarmankala/careos/.env.example)

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
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0010_patient_observations.sql
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0011_patient_day_plans.sql
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0012_care_team_memberships.sql
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0013_care_responsibility_assignments.sql
```

## Current product surface

WhatsApp currently supports:

- operational commands such as `schedule`, `status`, `done`, `delay`, `skip`, `patients`, `switch`, and `whoami`
- support/privacy self-service:
  - `support` or `privacy`
  - `1` see my feedback
  - `2` delete my profile
  - `3` export my data
  - `4` see my privacy requests
- medication edit/delete flows from the schedule menu
- patient-context capture:
  - `remember <key>: <fact>` or `remember <fact>`
  - `facts`
  - `forget <key|number>`
  - `note <observation>`
  - `observations`
  - `plan <day-scoped plan>`
  - `plans`
  - `forget plan <key|number>`
- care-team commands:
  - `team`
  - `assign <category> to <number> as responsible|informed`
  - `who handles <category>`
- non-operational questions routed through OpenClaw with grounding from:
  - active medication list
  - PRN medications
  - durable clinical facts
  - short-lived observations
  - day-scoped plans
  - care-team context when relevant

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
- `support` / `privacy` (opens privacy/self-service support menu)

Patient-context commands:
- `remember <key>: <fact>`
- `remember <fact>`
- `facts`
- `forget <key|number>`
- `note <observation>`
- `observations`
- `plan <day-scoped plan>`
- `plans`
- `forget plan <key|number>`

Care-team commands:
- `team`
- `assign <category> to <number> as responsible|informed`
- `who handles <category>`

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

See [ARCHITECTURE.md](/home/kumarmankala/careos/ARCHITECTURE.md).
Implemented behavior reference:
[IMPLEMENTED_SPEC.md](/home/kumarmankala/careos/IMPLEMENTED_SPEC.md)

## Operations runbook

Reusable onboarding and cleanup commands:
[OPERATIONS_RUNBOOK.md](/home/kumarmankala/careos/OPERATIONS_RUNBOOK.md)

Product and engineering backlog:
[BACKLOG.md](/home/kumarmankala/careos/BACKLOG.md)

Lightweight implementation process:
[IMPLEMENTATION_PIPELINE.md](/home/kumarmankala/careos/IMPLEMENTATION_PIPELINE.md)

Additional design docs:
- [CARE_TEAM_DESIGN.md](/home/kumarmankala/careos/CARE_TEAM_DESIGN.md)
- [CARE_TEAM_PHASE1_PLAN.md](/home/kumarmankala/careos/CARE_TEAM_PHASE1_PLAN.md)
- [SOVEREIGN_AGENT_ARCHITECTURE.md](/home/kumarmankala/careos/SOVEREIGN_AGENT_ARCHITECTURE.md)
- [SOVEREIGN_AGENT_PHASED_PLAN.md](/home/kumarmankala/careos/SOVEREIGN_AGENT_PHASED_PLAN.md)
- [SOVEREIGN_AGENT_UX_MANUAL.md](/home/kumarmankala/careos/SOVEREIGN_AGENT_UX_MANUAL.md)

DB reset helper:
- `scripts/reset_db.sh` (safe review mode by default; use `--apply` to execute)

## Admin CLI

Local operator workflow for metrics monitoring, privacy requests, subject export, and manual deletion planning:

1. Set `CAREOS_ADMIN_CLI_TOKEN` in `.env` to a strong random value.
2. Source the environment:
```bash
set -a
source .env
set +a
```
3. Log in locally:
```bash
python3 scripts/admin_cli.py login
```

Common commands:
```bash
python3 scripts/admin_cli.py metrics overview --days 30
python3 scripts/admin_cli.py message send --participant-id <participant-id> --body "We received your request and have a follow-up question."
python3 scripts/admin_cli.py privacy requests list
python3 scripts/admin_cli.py privacy requests create --type access --subject-participant-id <participant-id> --jurisdiction GDPR
python3 scripts/admin_cli.py privacy export --subject-participant-id <participant-id> --out export.json
python3 scripts/admin_cli.py privacy delete-plan --subject-participant-id <participant-id> --out delete-plan.json
```

Notes:
- `login` is local CLI authentication only; it checks the token already present in your environment and stores a hashed session at `~/.careos-admin/session.json`.
- `privacy delete-plan` does not delete anything. It generates a reviewable JSON plan with ordered SQL steps for manual execution after operator review.
- The CLI talks to `CAREOS_ADMIN_API_BASE_URL`, or falls back to `CAREOS_GATEWAY_CAREOS_BASE_URL`, or `http://127.0.0.1:8115`.

## Privacy and Compliance Surface

Current product behavior:
- users can reply `support` in WhatsApp to access privacy/self-service options
- `delete my profile` creates a tracked deletion request for manual operator review; it does not immediately hard-delete records
- `export my data` creates a tracked export request
- `see my privacy requests` shows recent request status
- `see my feedback` shows recent feedback submitted by that participant

Current operator/admin tooling:
- `POST /internal/admin/messages`
- `GET /internal/privacy/requests`
- `POST /internal/privacy/requests`
- `GET /internal/privacy/export?subject_participant_id=<id>`
- `python3 scripts/admin_cli.py message send ...`
- `python3 scripts/admin_cli.py privacy ...`

Scope boundary:
- this codebase now includes operational support for access/export and deletion-request intake
- hard deletion remains a manual reviewed operator workflow via export bundle + delete plan
- legal/policy/process work needed for HIPAA, GDPR, and CCPA still extends beyond code alone

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
