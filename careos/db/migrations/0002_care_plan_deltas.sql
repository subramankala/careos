ALTER TABLE win_definitions
  ADD COLUMN IF NOT EXISTS temporary_start TIMESTAMPTZ NULL,
  ADD COLUMN IF NOT EXISTS temporary_end TIMESTAMPTZ NULL;

ALTER TABLE win_instances
  ADD COLUMN IF NOT EXISTS superseded_by_change_id UUID NULL,
  ADD COLUMN IF NOT EXISTS superseded_at TIMESTAMPTZ NULL,
  ADD COLUMN IF NOT EXISTS superseded_reason TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS care_plan_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  care_plan_id UUID NOT NULL REFERENCES care_plans(id),
  version INT NOT NULL,
  actor_participant_id UUID NOT NULL REFERENCES participants(id),
  reason TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS care_plan_change_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  change_id UUID NOT NULL UNIQUE,
  care_plan_id UUID NOT NULL REFERENCES care_plans(id),
  patient_id UUID NOT NULL REFERENCES patients(id),
  version INT NOT NULL,
  actor_participant_id UUID NOT NULL REFERENCES participants(id),
  action TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_id UUID NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  old_value JSONB NOT NULL DEFAULT '{}'::jsonb,
  new_value JSONB NOT NULL DEFAULT '{}'::jsonb,
  superseded_instance_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
  created_instance_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_care_plan_versions_plan
  ON care_plan_versions(care_plan_id, version);

CREATE INDEX IF NOT EXISTS idx_care_plan_changes_plan
  ON care_plan_change_events(care_plan_id, created_at);

CREATE INDEX IF NOT EXISTS idx_win_instances_superseded_change
  ON win_instances(superseded_by_change_id)
  WHERE superseded_by_change_id IS NOT NULL;
