\set ON_ERROR_STOP on

BEGIN;

CREATE TABLE supply_photos (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  branch_id TEXT NOT NULL,
  created_by BIGINT NOT NULL,
  register_id BIGINT NOT NULL,
  file_name TEXT NOT NULL CHECK (length(file_name) BETWEEN 1 AND 255),
  content_type TEXT NOT NULL CHECK (content_type IN ('image/jpeg', 'image/png', 'image/webp')),
  content BYTEA NOT NULL CHECK (octet_length(content) BETWEEN 1 AND 12582912),
  sha256 TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP + INTERVAL '24 hours',
  recognition_result JSONB,
  recognition_attempts INTEGER NOT NULL DEFAULT 0 CHECK (recognition_attempts >= 0),
  recognition_attempted_at TIMESTAMPTZ,
  recognition_error TEXT,
  recognition_error_status INTEGER,
  UNIQUE (tenant_id, id)
);

CREATE INDEX supply_photos_pending_idx ON supply_photos (expires_at);
CREATE INDEX supply_photos_actor_idx ON supply_photos (tenant_id, created_by, created_at DESC);

CREATE TABLE supply_photo_documents (
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  photo_id TEXT NOT NULL,
  document_index INTEGER NOT NULL CHECK (document_index BETWEEN 0 AND 19),
  supply_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (photo_id, document_index),
  UNIQUE (tenant_id, supply_id),
  FOREIGN KEY (tenant_id, photo_id) REFERENCES supply_photos(tenant_id, id) ON DELETE CASCADE
);

INSERT INTO schema_migrations(version) VALUES ('016_supply_photos');
COMMIT;
