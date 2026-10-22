\set ON_ERROR_STOP on

CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

SELECT NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '003_catalog_and_technical_cards') AS run_003 \gset
\if :run_003
  \ir 003_catalog_and_technical_cards.sql
\endif

SELECT NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '004_operational_workspace') AS run_004 \gset
\if :run_004
  \ir 004_operational_workspace.sql
\endif

SELECT NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '005_saas_multitenancy') AS run_005 \gset
\if :run_005
  \ir 005_saas_multitenancy.sql
\endif

SELECT NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '006_employees_and_roles') AS run_006 \gset
\if :run_006
  \ir 006_employees_and_roles.sql
\endif

SELECT NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '007_pos_cashier_pin') AS run_007 \gset
\if :run_007
  \ir 007_pos_cashier_pin.sql
\endif

SELECT NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '008_pos_registers') AS run_008 \gset
\if :run_008
  \ir 008_pos_registers.sql
\endif

SELECT NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '009_poster_onboarding') AS run_009 \gset
\if :run_009
  \ir 009_poster_onboarding.sql
\endif

SELECT NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '010_poster_access_model') AS run_010 \gset
\if :run_010
  \ir 010_poster_access_model.sql
\endif

SELECT NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '011_employee_permissions') AS run_011 \gset
\if :run_011
  \ir 011_employee_permissions.sql
\endif

SELECT NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '012_employee_pin_reveal') AS run_012 \gset
\if :run_012
  \ir 012_employee_pin_reveal.sql
\endif

SELECT NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '013_service_plans') AS run_013 \gset
\if :run_013
  \ir 013_service_plans.sql
\endif

SELECT NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '014_employee_soft_delete') AS run_014 \gset
\if :run_014
  \ir 014_employee_soft_delete.sql
\endif

SELECT NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '015_deleted_employee_login_reuse') AS run_015 \gset
\if :run_015
  \ir 015_deleted_employee_login_reuse.sql
\endif

SELECT NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '016_supply_photos') AS run_016 \gset
\if :run_016
  \ir 016_supply_photos.sql
\endif

SELECT NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '017_connection_requests') AS run_017 \gset
\if :run_017
  \ir 017_connection_requests.sql
\endif

SELECT NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '018_trial_registration') AS run_018 \gset
\if :run_018
  \ir 018_trial_registration.sql
\endif

SELECT NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '019_email_outbox') AS run_019 \gset
\if :run_019
  \ir 019_email_outbox.sql
\endif

SELECT NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '020_subscription_payments') AS run_020 \gset
\if :run_020
  \ir 020_subscription_payments.sql
\endif

SELECT NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '021_annual_subscriptions') AS run_021 \gset
\if :run_021
  \ir 021_annual_subscriptions.sql
\endif
