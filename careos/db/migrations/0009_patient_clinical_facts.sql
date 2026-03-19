CREATE TABLE IF NOT EXISTS patient_clinical_facts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  actor_participant_id UUID NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
  fact_key TEXT NOT NULL,
  fact_value JSONB NOT NULL DEFAULT '{}'::jsonb,
  summary TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT 'caregiver_reported',
  effective_at TIMESTAMPTZ NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_patient_clinical_facts_active
  ON patient_clinical_facts (tenant_id, patient_id, status, created_at);

CREATE INDEX IF NOT EXISTS idx_patient_clinical_facts_key
  ON patient_clinical_facts (tenant_id, patient_id, lower(fact_key), status);
