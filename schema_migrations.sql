-- Incremental schema changes, applied by hand on the server.
-- schema.sql stays as the from-scratch definition; this file is the history
-- of everything applied on top of it. Append, never rewrite.
--
-- Apply with: mysql -h <host> -u <user> -p <db> < schema_migrations.sql

-- 2026-08-09 — Phase 1b
-- /api/report looks a purchase up by its Stripe checkout session id on every
-- poll; without this the lookup is a full table scan.
ALTER TABLE purchases ADD INDEX idx_checkout_session (checkout_session);
