# CareOS Lite Operations Runbook

Reusable VM commands for onboarding, identity troubleshooting, and safe cleanup.

Spec companion:
[IMPLEMENTED_SPEC.md](/Users/kumarmankala/code/Codex/Wellness-check/careos-lite/IMPLEMENTED_SPEC.md)

Documentation sync rule:
- Any change to runtime behavior must update both this runbook and `IMPLEMENTED_SPEC.md`.

## Preconditions

```bash
cd ~/careos
set -a; source .env; set +a
BASE="http://127.0.0.1:8115"
```

## ID Glossary

- `tenant_id`: account boundary (family/clinic)
- `patient_id`: care recipient within a tenant
- `participant_id`: WhatsApp identity (patient/caregiver/admin user)
- `care_plan_id`: plan attached to one patient

## Find Existing Tenants/Patients

```bash
psql "$CAREOS_DATABASE_URL" -c "SELECT id, name FROM tenants ORDER BY created_at DESC;"
psql "$CAREOS_DATABASE_URL" -c "SELECT id, display_name, tenant_id FROM patients ORDER BY created_at DESC;"
```

## Onboard New Patient + WhatsApp Caregiver

1) Create patient:

```bash
TENANT_ID="<tenant_id>"
curl -s -X POST "$BASE/patients" \
  -H "Content-Type: application/json" \
  -d "{
    \"tenant_id\":\"$TENANT_ID\",
    \"display_name\":\"<patient_name>\",
    \"timezone\":\"Asia/Kolkata\",
    \"primary_language\":\"en\",
    \"persona_type\":\"caregiver_managed_elder\",
    \"risk_level\":\"medium\",
    \"status\":\"active\"
  }" | python3 -m json.tool
```

2) Create WhatsApp participant:

```bash
curl -s -X POST "$BASE/participants" \
  -H "Content-Type: application/json" \
  -d "{
    \"tenant_id\":\"$TENANT_ID\",
    \"role\":\"caregiver\",
    \"display_name\":\"<caregiver_name>\",
    \"phone_number\":\"whatsapp:+<countrycode><number>\",
    \"preferred_channel\":\"whatsapp\",
    \"preferred_language\":\"en\",
    \"active\": true
  }" | python3 -m json.tool
```

3) Link participant to patient:

```bash
PATIENT_ID="<patient_id>"
PARTICIPANT_ID="<participant_id>"
curl -s -X POST "$BASE/caregiver-links" \
  -H "Content-Type: application/json" \
  -d "{
    \"caregiver_participant_id\":\"$PARTICIPANT_ID\",
    \"patient_id\":\"$PATIENT_ID\",
    \"relationship\":\"family\",
    \"notification_policy\": {},
    \"can_edit_plan\": true
  }" | python3 -m json.tool
```

### Faster path: one script for onboarding and re-import

```bash
cd ~/careos
set -a; source .env; set +a
python3 scripts/onboard_support_plan.py \
  --plan-json /absolute/path/patient_daily_support_plan.json \
  --tenant-id <tenant_id> \
  --caregiver-phone whatsapp:+<countrycode><number>
```

To update an existing patient's plan from a revised JSON:

```bash
python3 scripts/onboard_support_plan.py \
  --plan-json /absolute/path/patient_daily_support_plan.json \
  --tenant-id <tenant_id> \
  --patient-id <patient_id> \
  --care-plan-id <care_plan_id> \
  --caregiver-phone whatsapp:+<countrycode><number> \
  --replace-existing
```

## Identity Resolution Debug (When WhatsApp Shows Wrong/No Schedule)

```bash
PHONE="whatsapp:+<countrycode><number>"

psql "$CAREOS_DATABASE_URL" -c "
SELECT id, tenant_id, role, display_name, phone_number, active, created_at
FROM participants
WHERE phone_number='$PHONE'
ORDER BY created_at DESC;
"

psql "$CAREOS_DATABASE_URL" -c "
SELECT p.id AS participant_id, p.phone_number, p.active, c.patient_id, pa.display_name AS patient_name
FROM participants p
LEFT JOIN caregiver_patient_links c ON c.caregiver_participant_id = p.id
LEFT JOIN patients pa ON pa.id = c.patient_id
WHERE p.phone_number = '$PHONE'
ORDER BY p.created_at DESC;
"
```

If duplicate participant rows exist for same phone, keep one active:

```bash
KEEP="<participant_id_to_keep>"
psql "$CAREOS_DATABASE_URL" -c "
UPDATE participants
SET active = CASE WHEN id='$KEEP' THEN true ELSE false END
WHERE phone_number='$PHONE';
"
```

Restart API after identity fixes:

```bash
sudo systemctl restart careos-lite-api
```

## Verify Schedule Data for a Patient

```bash
PATIENT_ID="<patient_id>"
curl -s "$BASE/patients/$PATIENT_ID/today" | python3 -m json.tool
curl -s "$BASE/patients/$PATIENT_ID/status" | python3 -m json.tool

psql "$CAREOS_DATABASE_URL" -c "
SELECT wd.title,
       wi.current_state,
       wi.scheduled_start AT TIME ZONE 'Asia/Kolkata' AS ist_start
FROM win_instances wi
JOIN win_definitions wd ON wd.id = wi.win_definition_id
WHERE wi.patient_id = '$PATIENT_ID'
  AND wi.current_state <> 'superseded'
ORDER BY wi.scheduled_start
LIMIT 200;
"
```

## Safe Delete of a Tenant (FK-Safe)

Use only for cleanup/non-production data. This operation is destructive.

```bash
TENANT_ID="<tenant_id_to_delete>"
psql "$CAREOS_DATABASE_URL" <<SQL
BEGIN;

UPDATE win_instances wi
SET completed_by = NULL
WHERE completed_by IN (
  SELECT id FROM participants WHERE tenant_id = '$TENANT_ID'
);

DELETE FROM escalation_events
WHERE patient_id IN (SELECT id FROM patients WHERE tenant_id = '$TENANT_ID');

DELETE FROM message_events
WHERE tenant_id = '$TENANT_ID';

DELETE FROM care_plan_change_events
WHERE patient_id IN (SELECT id FROM patients WHERE tenant_id = '$TENANT_ID');

DELETE FROM care_plan_versions
WHERE care_plan_id IN (
  SELECT cp.id
  FROM care_plans cp
  JOIN patients p ON p.id = cp.patient_id
  WHERE p.tenant_id = '$TENANT_ID'
);

DELETE FROM win_instances
WHERE patient_id IN (SELECT id FROM patients WHERE tenant_id = '$TENANT_ID');

DELETE FROM win_definitions
WHERE care_plan_id IN (
  SELECT cp.id
  FROM care_plans cp
  JOIN patients p ON p.id = cp.patient_id
  WHERE p.tenant_id = '$TENANT_ID'
);

DELETE FROM care_plans
WHERE patient_id IN (SELECT id FROM patients WHERE tenant_id = '$TENANT_ID');

DELETE FROM caregiver_patient_links
WHERE patient_id IN (SELECT id FROM patients WHERE tenant_id = '$TENANT_ID')
   OR caregiver_participant_id IN (SELECT id FROM participants WHERE tenant_id = '$TENANT_ID');

DELETE FROM participants
WHERE tenant_id = '$TENANT_ID';

DELETE FROM patients
WHERE tenant_id = '$TENANT_ID';

DELETE FROM tenants
WHERE id = '$TENANT_ID';

COMMIT;
SQL
```

Verify:

```bash
psql "$CAREOS_DATABASE_URL" -c "SELECT id, name FROM tenants ORDER BY created_at DESC;"
```

## Current Product Constraint

Inbound WhatsApp identity resolution currently requires one active participant phone number to map to exactly one linked patient.
If one number is linked to multiple patients, webhook resolution fails closed.

## WhatsApp context check

Send `whoami` on WhatsApp to see:
- participant role
- active patient id
- timezone

## Enable Proactive WhatsApp Push (Scheduler)

1) Configure in `.env`:

```bash
CAREOS_TWILIO_ACCOUNT_SID=AC...
CAREOS_TWILIO_AUTH_TOKEN=...
CAREOS_TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886
CAREOS_ENABLE_SCHEDULER_WHATSAPP_PUSH=true
CAREOS_SCHEDULER_PATIENT_IDS=<patient_id_1>,<patient_id_2>
```

2) Restart scheduler:

```bash
sudo systemctl restart careos-lite-scheduler
sudo journalctl -u careos-lite-scheduler -n 50 --no-pager
```

3) Verify outbound attempts:

```bash
psql "$CAREOS_DATABASE_URL" -c "
SELECT created_at, patient_id, participant_id, message_type, body, structured_payload
FROM message_events
WHERE direction='outbound'
ORDER BY created_at DESC
LIMIT 30;
"
```
