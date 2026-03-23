CREATE TABLE IF NOT EXISTS privacy_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  request_type TEXT NOT NULL,
  subject_participant_id UUID NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
  requested_by_participant_id UUID NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
  jurisdiction TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL DEFAULT '',
  structured_context JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'open',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_privacy_requests_subject_created_at
  ON privacy_requests(subject_participant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_privacy_requests_status_created_at
  ON privacy_requests(status, created_at DESC);
