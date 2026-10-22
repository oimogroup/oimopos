BEGIN;

ALTER TABLE platform_plans ADD COLUMN annual_price NUMERIC(12,2) CHECK (annual_price >= 0);
UPDATE platform_plans SET monthly_price = CASE code WHEN 'canteen' THEN 3500 WHEN 'restaurant' THEN 4000 END,
  annual_price = CASE code WHEN 'canteen' THEN 42000 WHEN 'restaurant' THEN 48000 END,
  updated_at = CURRENT_TIMESTAMP
WHERE code IN ('canteen', 'restaurant');
ALTER TABLE platform_plans ALTER COLUMN annual_price SET NOT NULL;

-- Existing quotes retain both their original amount and their one-month term.
ALTER TABLE subscription_payments ADD COLUMN period_months SMALLINT NOT NULL DEFAULT 1
  CHECK (period_months IN (1, 12));

INSERT INTO schema_migrations(version) VALUES ('021_annual_subscriptions');
COMMIT;
