BEGIN;
ALTER TABLE auth_users ADD COLUMN email_verified_at TIMESTAMPTZ;
ALTER TABLE email_outbox ADD COLUMN expires_at TIMESTAMPTZ;
CREATE TABLE auth_action_tokens (
  token_hash CHAR(64) PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
  purpose TEXT NOT NULL CHECK (purpose IN ('reset', 'verify')),
  email TEXT NOT NULL,
  account_version INTEGER NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL,
  consumed_at TIMESTAMPTZ
);
CREATE INDEX auth_action_tokens_user_idx ON auth_action_tokens (user_id, purpose, created_at DESC);
CREATE TABLE auth_rate_limits (
  bucket CHAR(64) PRIMARY KEY,
  attempts INTEGER NOT NULL CHECK (attempts > 0),
  resets_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX auth_rate_limits_expiry_idx ON auth_rate_limits (resets_at);
INSERT INTO schema_migrations(version) VALUES ('022_account_recovery');
COMMIT;
