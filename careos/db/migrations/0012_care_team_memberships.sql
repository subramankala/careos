CREATE TABLE IF NOT EXISTS care_team_memberships (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  patient_id UUID NOT NULL REFERENCES patients(id),
  participant_id UUID NOT NULL REFERENCES participants(id),
  membership_type TEXT NOT NULL,
  relationship TEXT NOT NULL DEFAULT 'family',
  display_label TEXT NOT NULL DEFAULT '',
  authority_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  notification_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  source TEXT NOT NULL DEFAULT 'manual',
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (patient_id, participant_id)
);

CREATE INDEX IF NOT EXISTS idx_care_team_memberships_patient_active
  ON care_team_memberships (patient_id, status, created_at);

CREATE INDEX IF NOT EXISTS idx_care_team_memberships_participant_active
  ON care_team_memberships (participant_id, status, created_at);

CREATE INDEX IF NOT EXISTS idx_care_team_memberships_tenant_patient_active
  ON care_team_memberships (tenant_id, patient_id, status);
