BEGIN;

-- Preserve employee identities referenced by sales, shifts and audit history.
ALTER TABLE auth_users ADD COLUMN deleted_at TIMESTAMPTZ;
ALTER TABLE auth_users ADD CONSTRAINT auth_users_deleted_inactive_check
  CHECK (deleted_at IS NULL OR NOT is_active);

INSERT INTO schema_migrations(version) VALUES ('014_employee_soft_delete');
COMMIT;
