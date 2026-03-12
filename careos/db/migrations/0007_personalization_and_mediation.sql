CREATE TABLE IF NOT EXISTS personalization_rules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  patient_id UUID NOT NULL REFERENCES patients(id),
  actor_participant_id UUID NOT NULL REFERENCES participants(id),
  rule_type TEXT NOT NULL,
  rule_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_personalization_rules_active
  ON personalization_rules (tenant_id, patient_id, expires_at);

CREATE TABLE IF NOT EXISTS mediation_decisions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id TEXT NOT NULL,
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  patient_id UUID NOT NULL REFERENCES patients(id),
  participant_id UUID NULL REFERENCES participants(id),
  action TEXT NOT NULL,
  reason TEXT NOT NULL,
  policy_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  personalization_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  rendered_text TEXT NOT NULL DEFAULT '',
  correlation_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_mediation_decisions_patient_created
  ON mediation_decisions (tenant_id, patient_id, created_at DESC);
