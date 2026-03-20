CREATE TABLE IF NOT EXISTS patient_observations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  actor_participant_id UUID NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
  observation_key TEXT NOT NULL,
  observation_value JSONB NOT NULL DEFAULT '{}'::jsonb,
  summary TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT 'caregiver_reported',
  observed_at TIMESTAMPTZ NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_patient_observations_active
  ON patient_observations (tenant_id, patient_id, status, expires_at, created_at);

CREATE INDEX IF NOT EXISTS idx_patient_observations_key
  ON patient_observations (tenant_id, patient_id, lower(observation_key), status, observed_at);
