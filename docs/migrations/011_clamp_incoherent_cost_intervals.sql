-- 011_clamp_incoherent_cost_intervals.sql
--
-- The cost point estimate and its 80% interval come from different models:
-- CatBoost for the value, two LightGBM quantile models for the bounds. Nothing
-- in training forces them to agree, so a row can end up with a lower bound
-- above the estimate, or an upper bound below it. An "80% interval" that
-- excludes its own estimate is not a range anyone can act on.
--
-- breakdown_cost_model.py now widens the interval to contain the point at
-- prediction time. This applies the same rule to rows already stored.
--
-- The estimate itself is never moved: only the bounds widen, so the number the
-- model produced is preserved exactly.
--
-- Safe to re-run: the WHERE clause makes it a no-op once applied.

BEGIN;

UPDATE pdm_batch_predictions
SET min_cost_lkr = LEAST(min_cost_lkr, estimated_cost_lkr),
    max_cost_lkr = GREATEST(max_cost_lkr, estimated_cost_lkr)
WHERE estimated_cost_lkr IS NOT NULL
  AND min_cost_lkr IS NOT NULL
  AND max_cost_lkr IS NOT NULL
  AND NOT (min_cost_lkr <= estimated_cost_lkr AND estimated_cost_lkr <= max_cost_lkr);

COMMIT;

-- Verification (expect 0):
--   SELECT COUNT(*) FROM pdm_batch_predictions
--   WHERE estimated_cost_lkr IS NOT NULL
--     AND NOT (min_cost_lkr <= estimated_cost_lkr
--              AND estimated_cost_lkr <= max_cost_lkr);
