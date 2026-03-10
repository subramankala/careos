# CareOS Lite Implemented Spec

Last updated: 2026-03-10

This document describes what is implemented in the current codebase and VM deployment, not planned scope.

## 1) Objective Delivered

CareOS Lite is running as a multi-tenant WhatsApp care orchestration backend on a single GCP VM:

- Twilio webhook ingress to FastAPI control plane
- Deterministic command handling
- Postgres source of truth
- Scheduler-driven due reminder processing
- Policy-guided reminder behavior
- Proactive WhatsApp push delivery from scheduler
- Versioned care-plan delta edits with audit trace

## 2) Runtime Architecture

### Inbound conversation path

1. Twilio sends inbound webhook to `POST /twilio/webhook`.
2. FastAPI validates signature (if enabled).
3. FastAPI resolves participant context from sender phone.
4. FastAPI routes to deterministic conversation router.
5. FastAPI responds to Twilio with TwiML.

### Proactive reminder path

1. `careos-lite-scheduler.service` polls configured patient IDs.
2. Scheduler computes due wins for each patient.
3. Scheduler applies policy decision (`channel`, `tone`, offsets).
4. Scheduler writes idempotent outbound event row.
5. Scheduler sends WhatsApp via Twilio Messages API (if push enabled and Twilio config valid).
6. Send success/failure logged with structured logs.

### Core control rule

`Twilio -> FastAPI -> services/policy/conversation -> Twilio`

Conversation engine is behind FastAPI. Twilio never calls conversation engine directly.

## 3) Data Model Implemented

### Identity and tenancy

- `tenants`
- `patients`
- `participants`
- `caregiver_patient_links`

### Care orchestration

- `care_plans`
- `win_definitions`
- `win_instances`

### Audit/observability

- `message_events`
- `escalation_events`
- `care_plan_versions`
- `care_plan_change_events`

### Recurrence and supersede support

`win_definitions` includes:
- `recurrence_type` (`one_off|daily|weekly`)
- `recurrence_interval`
- `recurrence_days_of_week`
- `recurrence_until`
- `seed_start`
- `seed_duration_minutes`
- `temporary_start`
- `temporary_end`

`win_instances` includes:
- `superseded_by_change_id`
- `superseded_at`
- `superseded_reason`

## 4) API Surface Implemented

### Webhook + health

- `POST /twilio/webhook`
- `GET /health`

### Setup and identity

- `POST /tenants`
- `POST /patients`
- `POST /participants`
- `POST /caregivers`
- `POST /caregiver-links`

### Care plans and deltas

- `POST /care-plans`
- `PATCH /care-plans/{id}`
- `POST /care-plans/{id}/wins`
- `POST /care-plans/{id}/wins/add`
- `PATCH /care-plans/{id}/wins/{win_definition_id}`
- `DELETE /care-plans/{id}/wins/{win_definition_id}`
- `GET /care-plans/{id}/versions`
- `GET /care-plans/{id}/changes`

### Patient views and win actions

- `GET /patients/{id}/today`
- `GET /patients/{id}/timeline`
- `GET /patients/{id}/status`
- `GET /patients/{id}/adherence-summary`
- `POST /wins/{id}/complete`
- `POST /wins/{id}/delay`
- `POST /wins/{id}/skip`
- `POST /wins/{id}/escalate`

## 5) Deterministic WhatsApp Commands Implemented

- `help`
- `schedule` / `today`
- `next`
- `status`
- `whoami` / `profile`
- `done <item_no|win_id>`
- `skip <item_no|win_id>`
- `delay <item_no|win_id> <minutes>`

Behavior details:

- `schedule` is patient-local timezone, full list, numbered items.
- `done/skip/delay` accept list number references from schedule output.

## 6) Identity Resolution Rules

Inbound sender phone is normalized and matched to active participant.

Current fail-closed rule:
- participant must map to exactly one linked patient for webhook context.
- if no match or ambiguous mapping, webhook returns onboarding guidance.

Operational implication:
- one active participant phone should be linked to one active patient context for inbound command handling.

## 7) Recurrence and Scheduling Rules

Supported recurrence:
- one-off
- daily
- weekly

Scheduler ensures recurrence instances ahead of horizon and evaluates today timeline for due items.

Reminder creation guard:
- idempotency key per win-slot-recipient prevents duplicate writes from repeated polls.

## 8) Policy Engine (Current)

Inputs used now:
- criticality
- flexibility
- persona

Outputs used now:
- reminder offsets
- escalation delay metadata
- channel
- tone

Current channel path used in scheduler reminder sending:
- WhatsApp text

## 9) Proactive WhatsApp Push (Implemented)

Implemented components:
- `careos/integrations/twilio/sender.py` (Twilio REST sender)
- scheduler recipient resolution from active caregiver links
- idempotent outbound `message_events` row before send
- structured log events:
  - `scheduler_push_sent`
  - `scheduler_push_failed`
  - `scheduler_no_recipients`

Required env:
- `CAREOS_TWILIO_ACCOUNT_SID`
- `CAREOS_TWILIO_AUTH_TOKEN`
- `CAREOS_TWILIO_WHATSAPP_NUMBER`
- `CAREOS_ENABLE_SCHEDULER_WHATSAPP_PUSH=true`
- `CAREOS_SCHEDULER_PATIENT_IDS=<comma-separated patient ids>`

## 10) Delta Editing and Audit Rules

Delta edit behavior:

- Future instances affected by default.
- Historical completed instances are preserved.
- Active/due instances can be superseded when requested (`supersede_active_due=true`).
- Remove operations supersede instances; definitions remain for audit/version history.

Audit recorded:
- actor
- version bump
- action (`add|update|remove`)
- reason
- old/new values
- superseded/created instance IDs

## 11) Deployment Model Implemented (Single VM, No Docker)

Services:
- `careos-lite-api.service`
- `careos-lite-scheduler.service`

Docs and helpers:
- `DEPLOY_GCP_VM.md`
- `OPERATIONS_RUNBOOK.md`
- `scripts/install_systemd_units.sh`
- `.env.example`

## 12) Test Coverage (Implemented)

Repository tests include:
- multi-tenant webhook isolation
- risk fixes (signature/idempotency/timezone/identity/scheduler guardrails)
- recurrence behavior
- care-plan delta flows
- win action handling
- scheduler push idempotency path (mock sender)
- deterministic router behavior updates (timezone formatting, numbering, whoami)

## 13) OpenClaw Status

Current runtime status:
- OpenClaw is not actively wired into the request path.
- `openclaw_engine.py` exists as placeholder abstraction.
- App context currently binds deterministic router.

## 14) Known Limitations

- Inbound context resolution requires unambiguous single-patient mapping per sender participant.
- No clinician dashboard/UI.
- OCR ingestion flow not enabled.
- No active OpenClaw conversational orchestration in runtime path.
- Scheduler currently uses configured patient allowlist (`CAREOS_SCHEDULER_PATIENT_IDS`) for pilot control.

## 15) Documentation Sync Policy

For every behavioral or operational change:

1. Update this file (`IMPLEMENTED_SPEC.md`) with implemented behavior and constraints.
2. Update `OPERATIONS_RUNBOOK.md` with concrete command changes.
3. If env/service setup changes, update `README.md` and `DEPLOY_GCP_VM.md`.
