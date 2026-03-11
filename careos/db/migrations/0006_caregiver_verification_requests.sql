CREATE TABLE IF NOT EXISTS caregiver_verification_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  caregiver_participant_id UUID NOT NULL REFERENCES participants(id),
  patient_id UUID NOT NULL REFERENCES patients(id),
  patient_participant_id UUID NOT NULL REFERENCES participants(id),
  caregiver_name TEXT NOT NULL,
  caregiver_phone_number TEXT NOT NULL,
  patient_name TEXT NOT NULL,
  patient_phone_number TEXT NOT NULL,
  relationship TEXT NOT NULL,
  approval_code TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  expires_at TIMESTAMPTZ NOT NULL,
  send_attempt_count INT NOT NULL DEFAULT 0,
  last_sent_at TIMESTAMPTZ NULL,
  resolved_at TIMESTAMPTZ NULL,
  resolution_note TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_caregiver_verification_code_unique
  ON caregiver_verification_requests(approval_code);

CREATE INDEX IF NOT EXISTS idx_caregiver_verification_patient_phone_status
  ON caregiver_verification_requests(patient_phone_number, status);

CREATE INDEX IF NOT EXISTS idx_caregiver_verification_caregiver_status
  ON caregiver_verification_requests(caregiver_participant_id, status);
