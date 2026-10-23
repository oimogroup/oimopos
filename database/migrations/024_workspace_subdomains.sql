BEGIN;

ALTER TABLE tenants ADD COLUMN workspace_subdomain TEXT;

DO $$
DECLARE
  tenant RECORD;
  base TEXT;
  candidate TEXT;
  suffix INTEGER;
  tail TEXT;
BEGIN
  FOR tenant IN SELECT id, name FROM tenants ORDER BY created_at, id LOOP
    base := lower(tenant.name);
    base := replace(base, 'ё', 'yo');
    base := replace(base, 'ж', 'zh');
    base := replace(base, 'х', 'kh');
    base := replace(base, 'ц', 'ts');
    base := replace(base, 'ч', 'ch');
    base := replace(base, 'ш', 'sh');
    base := replace(base, 'щ', 'shch');
    base := replace(base, 'ю', 'yu');
    base := replace(base, 'я', 'ya');
    base := replace(base, 'ъ', '');
    base := replace(base, 'ь', '');
    base := translate(base,
      'абвгдезийклмнопрстуфыэ',
      'abvgdeziyklmnoprstufye');
    base := regexp_replace(base, '[^a-z0-9]+', '-', 'g');
    base := trim(both '-' from left(base, 48));
    IF length(base) < 3 OR base IN ('www','api','admin','login','account','billing','pos','static','assets','platform','support','mail','help','docs','status','cdn') THEN
      base := 'oimo-' || substring(md5(tenant.id) from 1 for 8);
    END IF;
    candidate := base;
    suffix := 2;
    WHILE EXISTS (SELECT 1 FROM tenants WHERE workspace_subdomain = candidate) LOOP
      tail := '-' || suffix::TEXT;
      candidate := left(base, 48 - length(tail)) || tail;
      suffix := suffix + 1;
    END LOOP;
    UPDATE tenants SET workspace_subdomain = candidate WHERE id = tenant.id;
  END LOOP;
END $$;

ALTER TABLE tenants ALTER COLUMN workspace_subdomain SET NOT NULL;
ALTER TABLE tenants ADD CONSTRAINT tenants_workspace_subdomain_format
  CHECK (workspace_subdomain ~ '^[a-z0-9]+(-[a-z0-9]+)*$' AND length(workspace_subdomain) BETWEEN 3 AND 48);
CREATE UNIQUE INDEX tenants_workspace_subdomain_uq ON tenants (lower(workspace_subdomain));

INSERT INTO schema_migrations(version) VALUES ('024_workspace_subdomains');
COMMIT;
