\set ON_ERROR_STOP on
BEGIN;
CREATE TABLE connection_requests (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 2 AND 100),
    company TEXT NOT NULL CHECK (length(company) BETWEEN 2 AND 160),
    phone TEXT NOT NULL CHECK (phone ~ '^[0-9]{7,15}$'),
    plan TEXT NOT NULL CHECK (plan IN ('canteen','restaurant')),
    status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','contacted')),
    fingerprint TEXT NOT NULL,
    peer_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX connection_requests_created_idx ON connection_requests (created_at DESC);
CREATE INDEX connection_requests_peer_idx ON connection_requests (peer_key, created_at);
CREATE INDEX connection_requests_phone_idx ON connection_requests (phone, created_at);
INSERT INTO schema_migrations (version) VALUES ('017_connection_requests');
COMMIT;
