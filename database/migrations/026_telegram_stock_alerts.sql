BEGIN;
CREATE TABLE telegram_integrations (
  tenant_id text PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
  bot_token bytea,
  bot_username text NOT NULL DEFAULT '',
  enabled boolean NOT NULL DEFAULT false,
  revision bigint NOT NULL DEFAULT 0,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE telegram_stock_routes (
  tenant_id text NOT NULL REFERENCES telegram_integrations(tenant_id) ON DELETE CASCADE,
  branch_id text NOT NULL,
  chat_id bigint CHECK (chat_id < 0),
  thread_id bigint CHECK (thread_id > 0),
  enabled boolean NOT NULL DEFAULT false,
  revision bigint NOT NULL DEFAULT 0,
  notified_keys text[] NOT NULL DEFAULT '{}',
  next_attempt timestamptz NOT NULL DEFAULT now(),
  lease_id uuid,
  lease_until timestamptz,
  attempts integer NOT NULL DEFAULT 0,
  last_sent_at timestamptz,
  last_checked_at timestamptz,
  last_error text NOT NULL DEFAULT '',
  PRIMARY KEY (tenant_id, branch_id),
  CHECK (NOT enabled OR chat_id IS NOT NULL)
);
CREATE INDEX telegram_stock_routes_due ON telegram_stock_routes(next_attempt) WHERE enabled;
INSERT INTO schema_migrations(version) VALUES ('026_telegram_stock_alerts');
COMMIT;
