BEGIN;

-- Deleted employees retain their identity and original login for audit history.
-- Only accounts that can be restored must continue reserving their login.
DROP INDEX auth_users_login_uq;
CREATE UNIQUE INDEX auth_users_login_uq ON auth_users (lower(login))
  WHERE deleted_at IS NULL;

INSERT INTO schema_migrations(version) VALUES ('015_deleted_employee_login_reuse');
COMMIT;
