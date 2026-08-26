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

-- 2026-08-14 — visualizer
-- One row per purchase that has uploaded a photo. It is the state machine the
-- status endpoint reads and, more importantly, the thing that stops a buyer
-- being given more image generations than they paid for: `generations` is
-- incremented under a conditional UPDATE, so two taps arriving together can
-- only ever claim one slot between them.
--
-- `generations` counts credits actually spent — an attempt that never got an
-- image back gives its credit back, because nothing was billed for it.
-- `attempts` only ever rises, and is the ceiling that stops a purchase whose
-- generation fails every time from retrying without end.
--
-- The images themselves are files, not columns: they are megabytes each, they
-- are read by a route that streams them, and a mysqldump of this table should
-- stay small enough to be a backup rather than an archive.
CREATE TABLE visualizations (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  purchase_id BIGINT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
              ON UPDATE CURRENT_TIMESTAMP,
  status VARCHAR(16) NOT NULL DEFAULT 'uploaded',
  generations TINYINT NOT NULL DEFAULT 0,
  attempts TINYINT NOT NULL DEFAULT 0,
  result_n TINYINT NULL,
  started_at DATETIME NULL,
  error VARCHAR(32) NULL,
  UNIQUE KEY uq_visualization_purchase (purchase_id),
  FOREIGN KEY (purchase_id) REFERENCES purchases(id)
);

-- 2026-08-26 — Meta match enrichment
-- What the browser knew at the moment it asked for a checkout session, held
-- until the webhook can use it. The server-side Purchase event fires from
-- Stripe's request, not the buyer's, so by then the buyer's IP and
-- User-Agent are gone — and those are two of the identifiers Meta matches a
-- conversion on. Captured at /api/checkout, read once, then swept.
--
-- Deliberately NOT Stripe metadata, which is where the click ids ride. Stripe
-- documents metadata as the wrong place for personal data, and an IP address
-- is personal data; metadata is also permanent, dashboard-visible and
-- exportable, where this table has a retention window and a sweeper.
--
-- Deliberately NOT the events table either. tracking.py stores two enum words
-- about the device and says, in as many words, that the raw User-Agent and
-- the IP are stored nowhere. That rule is about the analytics history, which
-- is kept forever and read by people; this row exists for minutes, is read
-- once by a machine, and is deleted. Keeping it in its own table rather than
-- widening `events` is what keeps that rule true.
--
-- Keyed on the session id because that is what already travels to the webhook
-- in Stripe metadata. One row per session; a second checkout attempt from the
-- same session overwrites it, which is what you want — the latest attempt is
-- the one that paid.
--
-- Sweep with scripts/cleanup_context.py (cron, daily). Nothing here is worth
-- keeping past the webhook it was captured for.
CREATE TABLE checkout_context (
  session_id CHAR(36) NOT NULL PRIMARY KEY,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  client_ip VARCHAR(45) NULL,
  client_ua VARCHAR(400) NULL,
  INDEX idx_context_created (created_at)
);
