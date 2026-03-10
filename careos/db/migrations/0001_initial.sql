CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS tenants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  type TEXT NOT NULL,
  timezone TEXT NOT NULL DEFAULT 'UTC',
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS patients (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  display_name TEXT NOT NULL,
  dob DATE NULL,
  timezone TEXT NOT NULL DEFAULT 'UTC',
  primary_language TEXT NOT NULL DEFAULT 'en',
  persona_type TEXT NOT NULL,
  risk_level TEXT NOT NULL DEFAULT 'medium',
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS participants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  role TEXT NOT NULL,
  display_name TEXT NOT NULL,
  phone_number TEXT NOT NULL UNIQUE,
  preferred_channel TEXT NOT NULL DEFAULT 'whatsapp',
  preferred_language TEXT NOT NULL DEFAULT 'en',
  active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS caregiver_patient_links (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  caregiver_participant_id UUID NOT NULL REFERENCES participants(id),
  patient_id UUID NOT NULL REFERENCES patients(id),
  relationship TEXT NOT NULL DEFAULT 'family',
  notification_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  can_edit_plan BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS care_plans (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id UUID NOT NULL REFERENCES patients(id),
  created_by_participant_id UUID NOT NULL REFERENCES participants(id),
  status TEXT NOT NULL DEFAULT 'active',
  version INT NOT NULL DEFAULT 1,
  effective_start TIMESTAMPTZ NULL,
  effective_end TIMESTAMPTZ NULL,
  source_type TEXT NOT NULL DEFAULT 'manual',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS win_definitions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  care_plan_id UUID NOT NULL REFERENCES care_plans(id),
  category TEXT NOT NULL,
  title TEXT NOT NULL,
  instructions TEXT NOT NULL,
  why_it_matters TEXT NOT NULL DEFAULT '',
  criticality TEXT NOT NULL,
  flexibility TEXT NOT NULL,
  default_channel_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  escalation_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS win_instances (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  win_definition_id UUID NOT NULL REFERENCES win_definitions(id),
  patient_id UUID NOT NULL REFERENCES patients(id),
  scheduled_start TIMESTAMPTZ NOT NULL,
  scheduled_end TIMESTAMPTZ NOT NULL,
  current_state TEXT NOT NULL DEFAULT 'pending',
  completion_time TIMESTAMPTZ NULL,
  completed_by UUID NULL REFERENCES participants(id),
  response_mode TEXT NOT NULL DEFAULT 'system',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_win_instances_patient_time
  ON win_instances(patient_id, scheduled_start);

CREATE TABLE IF NOT EXISTS message_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  patient_id UUID NOT NULL REFERENCES patients(id),
  participant_id UUID NULL REFERENCES participants(id),
  direction TEXT NOT NULL,
  channel TEXT NOT NULL,
  message_type TEXT NOT NULL,
  body TEXT NOT NULL,
  structured_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  correlation_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(idempotency_key)
);

CREATE TABLE IF NOT EXISTS escalation_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  win_instance_id UUID NOT NULL REFERENCES win_instances(id),
  patient_id UUID NOT NULL REFERENCES patients(id),
  trigger_reason TEXT NOT NULL,
  escalation_level TEXT NOT NULL,
  channel_used TEXT NOT NULL,
  recipient_participant_id UUID NULL REFERENCES participants(id),
  resolved_at TIMESTAMPTZ NULL,
  resolution_note TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
