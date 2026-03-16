CREATE TABLE IF NOT EXISTS person_identities (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  primary_phone_number TEXT NOT NULL,
  normalized_phone_number TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL DEFAULT '',
  preferred_channel TEXT NOT NULL DEFAULT 'whatsapp',
  preferred_language TEXT NOT NULL DEFAULT 'en',
  active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tenant_memberships (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  person_identity_id UUID NOT NULL REFERENCES person_identities(id),
  membership_type TEXT NOT NULL DEFAULT 'mixed_member',
  display_name TEXT NOT NULL,
  membership_status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, person_identity_id)
);

ALTER TABLE participants
  ADD COLUMN IF NOT EXISTS person_identity_id UUID NULL REFERENCES person_identities(id);

ALTER TABLE participants
  ADD COLUMN IF NOT EXISTS tenant_membership_id UUID NULL REFERENCES tenant_memberships(id);

CREATE INDEX IF NOT EXISTS idx_person_identities_normalized_phone
  ON person_identities(normalized_phone_number);

CREATE INDEX IF NOT EXISTS idx_tenant_memberships_person_identity
  ON tenant_memberships(person_identity_id);

CREATE INDEX IF NOT EXISTS idx_participants_person_identity
  ON participants(person_identity_id);

CREATE INDEX IF NOT EXISTS idx_participants_tenant_membership
  ON participants(tenant_membership_id);
