CREATE TABLE IF NOT EXISTS product_telemetry_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE SET NULL,
  patient_id UUID REFERENCES patients(id) ON DELETE SET NULL,
  participant_id UUID REFERENCES participants(id) ON DELETE SET NULL,
  event_name TEXT NOT NULL,
  source TEXT NOT NULL,
  actor_role TEXT NOT NULL DEFAULT '',
  channel TEXT NOT NULL DEFAULT '',
  event_value TEXT NOT NULL DEFAULT '',
  structured_context JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_product_telemetry_events_created_at
  ON product_telemetry_events(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_product_telemetry_events_event_name_created_at
  ON product_telemetry_events(event_name, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_product_telemetry_events_patient_created_at
  ON product_telemetry_events(patient_id, created_at DESC);
