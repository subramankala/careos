# Deploy CareOS Lite on GCP VM

## Assumptions

- Ubuntu-like VM with `systemd`, `python3`, `psql`, and network access to Postgres.
- Repo path is `/opt/careos-lite` (update commands if you choose a different path).
- Systemd units default to `User=ubuntu` and `Group=ubuntu`; change if your VM uses a different runtime user.
- Twilio webhook will target FastAPI (`/twilio/webhook`) and not any conversation-engine endpoint.

## 1. Clone and install

```bash
cd /opt
sudo git clone <your-new-repo-url> careos-lite
cd careos-lite
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

## 2. Configure environment

Create `/opt/careos-lite/.env` from template:

```bash
cp .env.example .env
```

Required vars to review before start:

- `CAREOS_DATABASE_URL`
- `CAREOS_TWILIO_ACCOUNT_SID`
- `CAREOS_TWILIO_AUTH_TOKEN`
- `CAREOS_TWILIO_WHATSAPP_NUMBER`
- `CAREOS_PUBLIC_WEBHOOK_BASE_URL`
- `CAREOS_VALIDATE_TWILIO_SIGNATURE` (keep `true` in production)
- `CAREOS_CONVERSATION_ENGINE` (`deterministic` or `openclaw`)
- `CAREOS_ENABLE_SCHEDULER_WHATSAPP_PUSH` (`true` to enable proactive push)

Optional but recommended:

- `CAREOS_DEFAULT_TIMEZONE`
- `CAREOS_SCHEDULER_POLL_SECONDS`
- `CAREOS_SCHEDULER_PATIENT_IDS` (pilot allowlist)

## 3. Apply migration

```bash
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0001_initial.sql
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0002_care_plan_deltas.sql
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0003_recurrence_support.sql
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0004_participant_active_context.sql
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0005_onboarding_sessions.sql
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0006_caregiver_verification_requests.sql
```

## 4. Review and install systemd unit files

Dry run:

```bash
./scripts/install_systemd_units.sh
```

Apply copy into `/etc/systemd/system/`:

```bash
./scripts/install_systemd_units.sh --apply
```

Unit sources in repo:

- `deploy/systemd/careos-lite-api.service`
- `deploy/systemd/careos-lite-scheduler.service`

## 5. Reload and start services

```bash
sudo systemctl daemon-reload
sudo systemctl enable careos-lite-api careos-lite-scheduler
sudo systemctl start careos-lite-api careos-lite-scheduler
sudo systemctl status careos-lite-api --no-pager
sudo systemctl status careos-lite-scheduler --no-pager
```

## 6. Twilio webhook config

Set incoming WhatsApp webhook URL to:

`https://<your-domain>/twilio/webhook`

Method: `POST`

## 7. Validate and inspect logs

```bash
curl -s http://127.0.0.1:8115/health
sudo journalctl -u careos-lite-api -n 100 --no-pager
sudo journalctl -u careos-lite-scheduler -n 100 --no-pager
```

Then send WhatsApp message from a mapped participant number:
- `schedule`
- `next`
- `status`

## Reusable operations

For onboarding new patients/caregivers, identity troubleshooting, and safe tenant cleanup:
[OPERATIONS_RUNBOOK.md](/Users/kumarmankala/code/Codex/Wellness-check/careos-lite/OPERATIONS_RUNBOOK.md)
