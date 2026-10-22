BEGIN;

ALTER TABLE auth_users ADD COLUMN email TEXT;

-- Existing email logins keep their address, verification and recovery links.
UPDATE auth_users SET email = lower(login)
WHERE staff_role <> 'pos_terminal' AND login ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$';

-- Do not assign a shared legacy contact address to an arbitrary owner.
WITH candidates AS (
  SELECT u.id, lower(trim(t.contact_email)) AS address,
         count(*) OVER (PARTITION BY lower(trim(t.contact_email))) AS owners
  FROM auth_users u JOIN tenants t ON t.id = u.tenant_id
  WHERE u.role = 'owner' AND u.email IS NULL AND u.deleted_at IS NULL
    AND trim(t.contact_email) ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'
)
UPDATE auth_users u SET email = c.address
FROM candidates c WHERE u.id = c.id AND c.owners = 1
  AND NOT EXISTS (SELECT 1 FROM auth_users other WHERE lower(other.email) = c.address AND other.deleted_at IS NULL);

UPDATE auth_users SET email_verified_at = NULL WHERE email IS DISTINCT FROM lower(login);

CREATE UNIQUE INDEX auth_users_email_uq ON auth_users (lower(email))
  WHERE email IS NOT NULL AND deleted_at IS NULL;
DROP INDEX auth_users_login_uq;
-- Terminal and employee credentials retain their existing namespace. Owners
-- may share an alias; their account identity is the unique email address.
CREATE UNIQUE INDEX auth_users_login_uq ON auth_users (lower(login))
  WHERE role <> 'owner' AND deleted_at IS NULL;
CREATE INDEX auth_users_owner_login_idx ON auth_users (lower(login)) WHERE role = 'owner' AND deleted_at IS NULL;

CREATE FUNCTION sync_auth_user_email() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.staff_role = 'pos_terminal' THEN
    NEW.email := NULL;
  ELSIF NEW.role <> 'owner' OR NEW.email IS NULL THEN
    NEW.email := CASE WHEN NEW.login ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$' THEN lower(NEW.login) ELSE NULL END;
  ELSE
    NEW.email := lower(trim(NEW.email));
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER auth_user_email_identity BEFORE INSERT OR UPDATE OF login, email, role, staff_role ON auth_users
  FOR EACH ROW EXECUTE FUNCTION sync_auth_user_email();

INSERT INTO schema_migrations(version) VALUES ('023_account_email_identity');
COMMIT;
