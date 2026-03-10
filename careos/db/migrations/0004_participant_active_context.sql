CREATE TABLE IF NOT EXISTS participant_active_context (
  participant_id UUID PRIMARY KEY REFERENCES participants(id),
  patient_id UUID NOT NULL REFERENCES patients(id),
  selected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  selection_source TEXT NOT NULL DEFAULT 'whatsapp_command'
);

CREATE INDEX IF NOT EXISTS idx_participant_active_context_patient
  ON participant_active_context(patient_id);
