CREATE TABLE IF NOT EXISTS care_responsibility_assignments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  patient_id UUID NOT NULL REFERENCES patients(id),
  team_member_id UUID NOT NULL REFERENCES care_team_memberships(id),
  assignment_type TEXT NOT NULL,
  responsibility_role TEXT NOT NULL,
  target_category TEXT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_care_responsibility_assignments_category_unique
  ON care_responsibility_assignments (patient_id, team_member_id, assignment_type, lower(coalesce(target_category, '')))
  WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_care_responsibility_assignments_patient_active
  ON care_responsibility_assignments (patient_id, status, assignment_type, responsibility_role, created_at);

CREATE INDEX IF NOT EXISTS idx_care_responsibility_assignments_member_active
  ON care_responsibility_assignments (team_member_id, status, created_at);
