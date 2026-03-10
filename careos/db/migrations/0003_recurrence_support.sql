ALTER TABLE win_definitions
  ADD COLUMN IF NOT EXISTS recurrence_type TEXT NOT NULL DEFAULT 'one_off',
  ADD COLUMN IF NOT EXISTS recurrence_interval INT NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS recurrence_days_of_week INT[] NOT NULL DEFAULT ARRAY[]::INT[],
  ADD COLUMN IF NOT EXISTS recurrence_until TIMESTAMPTZ NULL,
  ADD COLUMN IF NOT EXISTS seed_start TIMESTAMPTZ NULL,
  ADD COLUMN IF NOT EXISTS seed_duration_minutes INT NULL;

CREATE INDEX IF NOT EXISTS idx_win_definitions_recurrence
  ON win_definitions(care_plan_id, recurrence_type);

CREATE INDEX IF NOT EXISTS idx_win_instances_definition_start
  ON win_instances(win_definition_id, scheduled_start);
