-- Mazzin schema. Money is always integer cents. Never FLOAT.
-- Apply with: mysql -h <host> -u <user> -p <db> < schema.sql

CREATE TABLE events (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  funnel VARCHAR(32) NOT NULL,
  session_id CHAR(36) NOT NULL,        -- client-generated UUID
  event VARCHAR(32) NOT NULL,          -- funnel_start, swipe_1..N, result_view, paywall_view, pay_tap, purchase
  step TINYINT NULL,                   -- swipe number if applicable
  subid VARCHAR(128) NULL,
  utm_source VARCHAR(64) NULL, utm_campaign VARCHAR(128) NULL,
  utm_content VARCHAR(128) NULL, utm_term VARCHAR(128) NULL,
  extra JSON NULL,
  INDEX idx_funnel_event (funnel, event, created_at),
  INDEX idx_session (session_id)
);

CREATE TABLE purchases (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  funnel VARCHAR(32) NOT NULL,
  session_id CHAR(36) NOT NULL,
  stripe_event_id VARCHAR(255) NULL,
  payment_intent VARCHAR(255) NULL,
  checkout_session VARCHAR(255) NULL,
  amount_cents INT NOT NULL,
  currency CHAR(3) NOT NULL,
  email VARCHAR(255) NULL,
  country CHAR(2) NULL,
  result_style VARCHAR(64) NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'pending',
  UNIQUE KEY uq_stripe_event (stripe_event_id),
  UNIQUE KEY uq_payment_intent (payment_intent),
  INDEX idx_session (session_id)
);

CREATE TABLE reports (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  purchase_id BIGINT NOT NULL,
  content JSON NOT NULL,
  FOREIGN KEY (purchase_id) REFERENCES purchases(id)
);
