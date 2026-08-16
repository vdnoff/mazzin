-- 002 — a purchase that came from a PaymentIntent rather than a Checkout
-- Session. Apply by hand: mysql -h <host> -u <user> -p <db> < this file
--
-- READ THIS FIRST. On a database built from schema.sql this migration does
-- NOTHING, and that is the expected outcome rather than a mistake. Every
-- condition it wants is already true:
--
--   * `checkout_session` has been VARCHAR(255) NULL since the table was
--     first defined, so a purchase can already exist without one.
--   * `uq_payment_intent` has been a UNIQUE KEY since the same commit, so
--     payments are already deduped by payment intent.
--   * `uq_stripe_event` is untouched here and stays as it is.
--
-- It exists anyway because "the schema already allows it" is a claim worth
-- being able to check rather than remember, and because a database restored
-- from an older dump might not match. Running it prints one row per check
-- saying what it found and what it did.
--
-- Every statement is guarded against information_schema and prepared only if
-- it is needed, so this is safe to run twice, or ten times.

-- --- 1. checkout_session must be nullable ---------------------------------
-- A PaymentIntent purchase has no checkout session at all. MySQL has no
-- `MODIFY ... IF`, so the column definition is read first and the ALTER is
-- built only when it would change something — an unconditional MODIFY would
-- rewrite the table on every run for no reason.
SET @nullable := (
  SELECT IS_NULLABLE FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'purchases'
    AND COLUMN_NAME = 'checkout_session'
);

SET @sql := IF(@nullable = 'NO',
  'ALTER TABLE purchases MODIFY checkout_session VARCHAR(255) NULL',
  'DO 0');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SELECT 'checkout_session nullable' AS check_name,
       IFNULL(@nullable, 'COLUMN MISSING') AS was,
       IF(@nullable = 'NO', 'altered to NULL', 'already nullable — no change')
         AS action;

-- --- 2. payment_intent must be UNIQUE -------------------------------------
-- This is what makes one payment yield one purchase row when the same payment
-- arrives as both a checkout.session.completed and a payment_intent.succeeded:
-- the second INSERT raises IntegrityError and the webhook answers 200
-- duplicate. Without it, both would be recorded.
--
-- Counted as a unique index on exactly this one column: a composite index that
-- happens to start with payment_intent would not give the guarantee.
SET @uniq := (
  SELECT COUNT(*) FROM information_schema.STATISTICS s
  WHERE s.TABLE_SCHEMA = DATABASE()
    AND s.TABLE_NAME = 'purchases'
    AND s.COLUMN_NAME = 'payment_intent'
    AND s.NON_UNIQUE = 0
    AND (SELECT COUNT(*) FROM information_schema.STATISTICS t
         WHERE t.TABLE_SCHEMA = s.TABLE_SCHEMA
           AND t.TABLE_NAME = s.TABLE_NAME
           AND t.INDEX_NAME = s.INDEX_NAME) = 1
);

SET @sql := IF(@uniq = 0,
  'ALTER TABLE purchases ADD UNIQUE KEY uq_payment_intent (payment_intent)',
  'DO 0');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SELECT 'payment_intent unique' AS check_name,
       IF(@uniq = 0, 'absent', 'present') AS was,
       IF(@uniq = 0, 'unique key added', 'already unique — no change') AS action;

-- --- 3. the existing UNIQUE on stripe_event_id is kept ---------------------
-- Nothing above touches it. Reported so a run of this file says so out loud
-- rather than leaving it to be assumed.
SELECT 'stripe_event_id unique' AS check_name,
       IF(COUNT(*) > 0, 'present', 'ABSENT — investigate') AS was,
       'untouched by this migration' AS action
  FROM information_schema.STATISTICS
 WHERE TABLE_SCHEMA = DATABASE()
   AND TABLE_NAME = 'purchases'
   AND COLUMN_NAME = 'stripe_event_id'
   AND NON_UNIQUE = 0;
