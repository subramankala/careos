CREATE TABLE IF NOT EXISTS patient_day_plans (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  actor_participant_id UUID NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
  plan_key TEXT NOT NULL,
  plan_value JSONB NOT NULL DEFAULT '{}'::jsonb,
  summary TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT 'caregiver_reported',
  plan_date DATE NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_patient_day_plans_active
  ON patient_day_plans (tenant_id, patient_id, plan_date, status, expires_at, created_at);

CREATE INDEX IF NOT EXISTS idx_patient_day_plans_key
  ON patient_day_plans (tenant_id, patient_id, lower(plan_key), plan_date, status);
