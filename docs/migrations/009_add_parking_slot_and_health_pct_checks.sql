-- Migration: assets.parking_slot + sensor_readings health-percentage CHECK constraints
-- Run this in Supabase SQL editor or via psql.
--
-- Part 1 — assets.parking_slot
--   Warehouse parking bay for each vehicle, formatted "<zone letter>-<bay>" e.g.
--   'A-012', 'C-047'. Zone letter identifies the warehouse block/yard; bay is a
--   3-digit slot number within that zone. A bay holds one vehicle at a time, so
--   it is unique per warehouse (partial index — NULL means "no assigned bay").
--
-- Part 2 — health-percentage CHECK constraints
--   sensor_readings had NO check constraints of any kind, which is why out-of-range
--   component health values (including negatives) were writable and reached the
--   models. app.ai.services.survival_service._clamp_health_pct and
--   app.ai.services.batch_prediction_service._clamp_health_pct already defend the
--   read path; these constraints close the write path so the invalid data can
--   never be stored in the first place. NULL stays allowed — "not measured" is a
--   real state and is distinct from "measured out of range".
--
--   Run this while the affected tables are empty (i.e. as part of the fleet
--   rebuild, after the wipe and before the load) so validation is instant. If
--   applying against a populated table, repair out-of-range rows first:
--       SELECT count(*) FROM sensor_readings
--        WHERE oil_life_pct       NOT BETWEEN 0 AND 100
--           OR brake_health_pct   NOT BETWEEN 0 AND 100
--           OR tire_health_pct    NOT BETWEEN 0 AND 100
--           OR battery_health_pct NOT BETWEEN 0 AND 100
--           OR hydraulic_health_pct NOT BETWEEN 0 AND 100;

BEGIN;

-- ── Part 1: parking slot ──────────────────────────────────────────────────────
ALTER TABLE assets
    ADD COLUMN IF NOT EXISTS parking_slot TEXT;

COMMENT ON COLUMN assets.parking_slot IS
    'Warehouse parking bay, "<zone>-<bay>" e.g. A-012. Unique per warehouse; NULL = unassigned.';

CREATE UNIQUE INDEX IF NOT EXISTS uq_assets_warehouse_parking_slot
    ON assets (warehouse_id, parking_slot)
    WHERE parking_slot IS NOT NULL;

-- ── Part 2: health-percentage range constraints ───────────────────────────────
ALTER TABLE sensor_readings
    DROP CONSTRAINT IF EXISTS ck_sensor_readings_oil_life_pct,
    DROP CONSTRAINT IF EXISTS ck_sensor_readings_brake_health_pct,
    DROP CONSTRAINT IF EXISTS ck_sensor_readings_tire_health_pct,
    DROP CONSTRAINT IF EXISTS ck_sensor_readings_battery_health_pct,
    DROP CONSTRAINT IF EXISTS ck_sensor_readings_hydraulic_health_pct;

ALTER TABLE sensor_readings
    ADD CONSTRAINT ck_sensor_readings_oil_life_pct
        CHECK (oil_life_pct IS NULL OR (oil_life_pct >= 0 AND oil_life_pct <= 100)),
    ADD CONSTRAINT ck_sensor_readings_brake_health_pct
        CHECK (brake_health_pct IS NULL OR (brake_health_pct >= 0 AND brake_health_pct <= 100)),
    ADD CONSTRAINT ck_sensor_readings_tire_health_pct
        CHECK (tire_health_pct IS NULL OR (tire_health_pct >= 0 AND tire_health_pct <= 100)),
    ADD CONSTRAINT ck_sensor_readings_battery_health_pct
        CHECK (battery_health_pct IS NULL OR (battery_health_pct >= 0 AND battery_health_pct <= 100)),
    ADD CONSTRAINT ck_sensor_readings_hydraulic_health_pct
        CHECK (hydraulic_health_pct IS NULL OR (hydraulic_health_pct >= 0 AND hydraulic_health_pct <= 100));

COMMIT;
