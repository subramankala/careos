CREATE TABLE IF NOT EXISTS participant_feedback (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  participant_id UUID NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
  source_channel TEXT NOT NULL,
  feedback_type TEXT NOT NULL,
  message TEXT NOT NULL,
  structured_context JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'new',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_participant_feedback_patient_created_at
  ON participant_feedback(patient_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_participant_feedback_participant_created_at
  ON participant_feedback(participant_id, created_at DESC);
