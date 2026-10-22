\set ON_ERROR_STOP on
BEGIN;
CREATE TABLE trial_registrations (
    id UUID PRIMARY KEY,
    tenant_id TEXT NOT NULL UNIQUE REFERENCES tenants(id) ON DELETE CASCADE,
    email TEXT NOT NULL UNIQUE,
    phone TEXT NOT NULL UNIQUE,
    peer_key TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX trial_registrations_peer_idx ON trial_registrations (peer_key, created_at);
INSERT INTO schema_migrations (version) VALUES ('018_trial_registration');
COMMIT;
