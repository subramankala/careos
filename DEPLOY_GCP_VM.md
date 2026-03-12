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
- `CAREOS_GATEWAY_MODE` (`disabled` or `external`)
- `CAREOS_GATEWAY_PORT` (default `8220`)
- `CAREOS_GATEWAY_OPENCLAW_BASE_URL` (optional external OpenClaw endpoint)
- `CAREOS_GATEWAY_OPENCLAW_FALLBACK_PATH` (optional OpenClaw fallback path override)
- `CAREOS_GATEWAY_PENDING_ACTION_TTL_MINUTES` (default `10`)
- `CAREOS_GATEWAY_CONVERSATION_MODE` (`openclaw_first` recommended, fallback `deterministic_first`)
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
psql "$CAREOS_DATABASE_URL" -f careos/db/migrations/0007_personalization_and_mediation.sql
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
- `deploy/systemd/careos-lite-mcp.service`
- `deploy/systemd/careos-lite-gateway.service`

## 5. Reload and start services

```bash
sudo systemctl daemon-reload
sudo systemctl enable careos-lite-api careos-lite-scheduler careos-lite-mcp careos-lite-gateway
sudo systemctl start careos-lite-api careos-lite-scheduler careos-lite-mcp careos-lite-gateway
sudo systemctl status careos-lite-api --no-pager
sudo systemctl status careos-lite-scheduler --no-pager
sudo systemctl status careos-lite-mcp --no-pager
sudo systemctl status careos-lite-gateway --no-pager
```

## 6. Twilio webhook cutover

If gateway mode is enabled (`CAREOS_GATEWAY_MODE=external`), point Twilio to gateway ingress:

`https://<your-domain>/gateway/twilio/webhook`

If gateway mode is disabled (`CAREOS_GATEWAY_MODE=disabled`), point Twilio directly to CareOS:

`https://<your-domain>/twilio/webhook`

Method: `POST`

### Cutover checklist

1. Verify gateway health:

```bash
curl -s http://127.0.0.1:8220/health
```

2. Verify API health:

```bash
curl -s http://127.0.0.1:8115/health
```

3. Send a local smoke webhook to gateway:

```bash
curl -s -X POST http://127.0.0.1:8220/gateway/twilio/webhook \
  -d "From=whatsapp:+15550001111" \
  -d "To=whatsapp:+14155238886" \
  -d "Body=schedule" \
  -d "MessageSid=SM_gateway_smoke_1"
```

4. Update Twilio inbound URL to `/gateway/twilio/webhook`.
5. Observe logs for first live messages.

### Rollback checklist

1. Update Twilio inbound URL back to `/twilio/webhook`.
2. Set `CAREOS_GATEWAY_MODE=disabled` in `.env`.
3. Restart API and gateway:

```bash
sudo systemctl restart careos-lite-api careos-lite-gateway
```

## 7. Validate and inspect logs

```bash
curl -s http://127.0.0.1:8115/health
curl -s http://127.0.0.1:8220/health
sudo journalctl -u careos-lite-api -n 100 --no-pager
sudo journalctl -u careos-lite-scheduler -n 100 --no-pager
sudo journalctl -u careos-lite-mcp -n 100 --no-pager
sudo journalctl -u careos-lite-gateway -n 100 --no-pager
```

## 8. MCP for OpenClaw/agents

Set in `.env`:

- `CAREOS_MCP_API_KEY=<strong-secret>`
- `CAREOS_MCP_CAREOS_BASE_URL=http://127.0.0.1:8115`
- `CAREOS_MCP_ALLOWED_WRITE_ROLES=caregiver,patient,clinician,admin`

Health check:

```bash
curl -s http://127.0.0.1:8110/health
```

Tool list:

```bash
curl -s http://127.0.0.1:8110/mcp/tools \
  -H "x-mcp-api-key: $CAREOS_MCP_API_KEY"
```

Example write tool call:

```bash
curl -s -X POST http://127.0.0.1:8110/mcp/call \
  -H "x-mcp-api-key: $CAREOS_MCP_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "tool":"careos_complete_win",
    "arguments":{
      "win_instance_id":"<win_instance_id>",
      "actor_id":"<participant_id>",
      "actor_role":"caregiver",
      "reason":"patient confirmed completion"
    }
  }'
```

Then send WhatsApp message from a mapped participant number:
- `schedule`
- `next`
- `status`

## Reusable operations

For onboarding new patients/caregivers, identity troubleshooting, and safe tenant cleanup:
[OPERATIONS_RUNBOOK.md](/Users/kumarmankala/code/Codex/Wellness-check/careos-lite/OPERATIONS_RUNBOOK.md)
