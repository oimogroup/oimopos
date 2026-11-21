BEGIN;
CREATE INDEX operational_catalog_save_lookup ON operational_events
  (tenant_id, actor_user_id, ((payload->'_catalogSave'->>'requestId')))
  WHERE payload ? '_catalogSave';
INSERT INTO schema_migrations(version) VALUES ('025_catalog_save_operations');
COMMIT;
