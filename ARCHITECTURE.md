# CareOS Lite Architecture

## Request Flow

1. Twilio sends inbound webhook to `POST /twilio/webhook`.
2. FastAPI validates signature and parses sender (`From`) + message text (`Body`).
3. Unknown or incomplete senders enter `OnboardingService` state machine (`myself` vs `someone I care for`) with persisted session state.
4. Known senders resolve through `IdentityService` with active patient context rules.
5. Inbound message is persisted in `message_events` only after patient context is resolved.
6. `DeterministicRouter` executes command using `WinService`.
7. Outbound response is persisted in `message_events` with idempotency key.
8. FastAPI returns TwiML response.

## Scheduler Flow

1. `scheduler_worker.py` polls due win instances on cadence.
2. `PolicyEngine` computes strategy from criticality + flexibility + persona.
3. Reminder or escalation actions are emitted via `MessageOrchestrator`.
4. Outbound sends are idempotent (unique idempotency key in `message_events`).
5. Escalations are persisted in `escalation_events`.

## Escalation Flow

1. Win remains unresolved past policy threshold.
2. Escalation rule determines recipient (caregiver first for pilot).
3. Escalation event is recorded with reason and level.
4. Notification message is sent/logged idempotently.

## Current Risk Controls

- `POST /twilio/webhook` validates Twilio signatures before command handling when enabled.
- Inbound message dedupe is keyed by `MessageSid` (or a deterministic fallback hash if absent).
- Outbound replies are idempotent per inbound correlation id.
- Scheduler reminders are idempotent per `win_instance_id + scheduled_start`.
- Patient day windows are resolved in patient timezone and converted to UTC for storage/query.
- Identity resolution returns no context on ambiguous caregiver links instead of guessing a patient.

## Care Plan Delta Update Model

- Edits are versioned (`care_plan_versions`) and auditable (`care_plan_change_events`).
- Each change captures actor, timestamp, old value, new value, reason, superseded instance ids, and created instance ids.
- Future-instance regeneration rule:
  1. Preserve historical completions/skips.
  2. Preserve active/due unless `supersede_active_due=true`.
  3. Supersede targeted future instances.
  4. Insert replacement future instances from confirmed payload.
- Temporary wins/medications are represented by optional `temporary_start` and `temporary_end` on `win_definitions`.
- Recurrence model is definition-driven:
  - `one_off`: only explicit instances are used.
  - `daily` / `weekly`: future instances are generated from `seed_start`, `seed_duration_minutes`, and recurrence settings.
  - Generation horizon is rolling (default 30 days) and runs during patient reads and scheduler scans.

## Known Pilot Limitations

- Caregiver onboarding currently ends in `handoff_pending`; patient approval/verification workflow is not yet enforced.
- Onboarding sessions expire by TTL and restart from role selection; there is no admin endpoint yet to inspect or override sessions.
- If upstream proxy/TLS URL configuration is wrong, Twilio signature checks will fail closed until `CAREOS_PUBLIC_WEBHOOK_BASE_URL` is corrected.
- Scheduler uses idempotent writes for duplicate protection, but does not yet include advisory locking/leader election.

## Deployment Notes (GCP VM)

- Run FastAPI app and scheduler worker as separate systemd services.
- Use managed Postgres (or VM Postgres) and daily backups.
- Keep Twilio auth token in secret manager or restricted env file.
- Ensure TLS termination on ingress (Nginx/Caddy/Cloud LB).
- Configure Twilio webhook URL to `/twilio/webhook`.
