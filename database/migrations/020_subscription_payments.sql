\set ON_ERROR_STOP on
BEGIN;
CREATE TABLE subscription_payments (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id),
    owner_user_id BIGINT REFERENCES auth_users(id),
    request_id UUID NOT NULL,
    plan_code TEXT NOT NULL,
    amount NUMERIC(12,2) NOT NULL CHECK (amount > 0),
    currency TEXT NOT NULL DEFAULT 'KGS' CHECK (currency='KGS'),
    max_branches INTEGER NOT NULL CHECK (max_branches > 0),
    merchant_id TEXT NOT NULL,
    testing BOOLEAN NOT NULL,
    status TEXT NOT NULL DEFAULT 'creating' CHECK (status IN ('creating','pending','paid','failed','review','refunded')),
    provider_payment_id TEXT,
    checkout_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    checked_at TIMESTAMPTZ,
    applied_at TIMESTAMPTZ,
    service_starts_at TIMESTAMPTZ,
    service_ends_at TIMESTAMPTZ,
    refund_amount NUMERIC(12,2) NOT NULL DEFAULT 0,
    review_reason TEXT NOT NULL DEFAULT '',
    terms_version TEXT NOT NULL,
    terms_snapshot JSONB NOT NULL,
    result_ack BYTEA,
    terms_accepted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, request_id)
);
CREATE UNIQUE INDEX subscription_payments_provider_idx ON subscription_payments (merchant_id,provider_payment_id) WHERE provider_payment_id IS NOT NULL;
CREATE INDEX subscription_payments_tenant_idx ON subscription_payments (tenant_id,created_at DESC);
CREATE TABLE subscription_payment_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES subscription_payments(id),
    kind TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE subscription_refund_requests (
    id UUID PRIMARY KEY,
    order_id TEXT NOT NULL UNIQUE REFERENCES subscription_payments(id),
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','approved','rejected')),
    resolution TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    resolved_by BIGINT REFERENCES auth_users(id)
);
INSERT INTO schema_migrations(version) VALUES ('020_subscription_payments');
COMMIT;
