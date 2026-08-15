-- 010_align_health_status_with_canonical_bands.sql
--
-- pdm_batch_predictions.health_status carried its own band scale
-- (>=85 "Healthy" / >=70 Good / >=50 Moderate / >=30 Poor / else Critical),
-- written by _compute_health_score in batch_prediction_service.py. Every other
-- consumer of health bands -- the admin dashboard, report agents, the KB
-- annotator, and the assets.health_band column -- uses app/services/health_bands.py
-- (>=60 excellent / >=50 good / >=38 moderate / >=25 poor / else critical),
-- which is also exactly the asset_health_band Postgres enum.
--
-- The two disagreed for 602 of 850 assets. health_status is not rendered in the
-- web UI, but it IS exposed to the LLM agent (app/ai/agent/tools.py), so the
-- chatbot described an asset as "Poor" while the dashboard showed it as
-- moderate. The old top band was also unreachable: it required a score >= 85
-- and the highest score the fleet produces is 79.0.
--
-- batch_prediction_service.py now calls health_bands.band_for(), so new rows are
-- correct by construction. This migration brings existing rows in line.
--
-- Safe to re-run: the WHERE clause makes it a no-op once applied.
-- Reversible: health_status is fully derivable from health_score.

BEGIN;

UPDATE pdm_batch_predictions
SET health_status = CASE
        WHEN health_score >= 60.0 THEN 'excellent'
        WHEN health_score >= 50.0 THEN 'good'
        WHEN health_score >= 38.0 THEN 'moderate'
        WHEN health_score >= 25.0 THEN 'poor'
        ELSE 'critical'
    END
WHERE status = 'ok'
  AND health_score IS NOT NULL
  AND health_status IS DISTINCT FROM CASE
        WHEN health_score >= 60.0 THEN 'excellent'
        WHEN health_score >= 50.0 THEN 'good'
        WHEN health_score >= 38.0 THEN 'moderate'
        WHEN health_score >= 25.0 THEN 'poor'
        ELSE 'critical'
    END;

COMMIT;

-- Verification (expect 0 rows):
--   SELECT COUNT(*) FROM pdm_batch_predictions p
--   JOIN assets a ON a.id = p.asset_id
--   WHERE p.status = 'ok' AND p.health_score IS NOT NULL
--     AND p.health_status IS DISTINCT FROM a.health_band::text;
