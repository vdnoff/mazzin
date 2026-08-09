-- Incremental schema changes, applied by hand on the server.
-- schema.sql stays as the from-scratch definition; this file is the history
-- of everything applied on top of it. Append, never rewrite.
--
-- Apply with: mysql -h <host> -u <user> -p <db> < schema_migrations.sql

-- 2026-08-09 — Phase 1b
-- /api/report looks a purchase up by its Stripe checkout session id on every
-- poll; without this the lookup is a full table scan.
ALTER TABLE purchases ADD INDEX idx_checkout_session (checkout_session);

-- 2026-08-09 — Phase 2c.5
-- Per-style report sections that are the same for every buyer of a style, so
-- they are generated once and read from here on every later purchase. The
-- unique key is what makes the write idempotent under concurrent first
-- purchases of the same style.
CREATE TABLE style_sections (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  funnel VARCHAR(32) NOT NULL,
  style_id VARCHAR(64) NOT NULL,
  section_id VARCHAR(32) NOT NULL,
  content JSON NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_style_section (funnel, style_id, section_id)
);
