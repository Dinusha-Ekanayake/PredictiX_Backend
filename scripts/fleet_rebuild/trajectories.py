"""Selects, re-dates and regionally conditions real v11 vehicle trajectories.

Why resample instead of synthesise: v11 trajectories are already internally
coherent, odometer rises monotonically, ``days_since_last_service`` accumulates
and resets exactly on service events, component health decays then jumps back
when that component is serviced, and ``lifetime_service_count`` increments in
step. Reproducing all of that from scratch is how synthetic fleets go subtly
wrong. Adopting a real trajectory inherits the coherence for free, and
guarantees every value sits inside the distribution the models were trained on.

Three transformations are applied on the way out:

1. **Re-dating.** v11 vehicles stop at different dates (all start 2020-01-01,
   last snapshots run 2025-07..2025-11). Each trajectory is re-anchored so its
   final snapshot is *today*. Left at their original dates the fleet's newest
   reading is months stale, which understates ``days_since_last_service``.

2. **Seasonal re-draw.** Because the shift differs per vehicle, a reading's
   calendar month moves, which would leave monsoon rainfall landing in the wrong
   month. The three seasonal columns are therefore re-drawn from v11's own
   distribution *conditioned on the new calendar month*, so seasonality is
   correct and the values stay in-distribution.

3. **Regional conditioning.** v11 is Colombo-only. Warehouse identity is not a
   model feature (verified against all 58), so regional character can only be
   expressed through environmental columns that are. Multipliers/offsets from
   ``config.REGIONAL_ADJUST`` are applied and then hard-clipped to v11's own
   observed range for that column, so nothing escapes the trained domain.
"""

from __future__ import annotations

import random
from datetime import date

import pandas as pd

from . import config as C

# Columns whose value is a property of the calendar month rather than of the
# vehicle, so they must follow the *new* date after re-dating.
SEASONAL_COLS = ["ambient_temp_avg_c", "ambient_humidity_avg_pct", "rainfall_mm_30d"]

# Sri Lanka has two monsoons. v11 is Colombo, i.e. Southwest-monsoon phased
# (peak rain May-Sep). Badulla sits in Uva, where the Northeast monsoon
# dominates (peak rain Dec-Feb). Sampling Badulla's seasonal values from the
# month six months opposite approximates that phase inversion. It is an
# approximation, not a meteorological model, but it is much closer to reality
# than giving an upcountry depot Colombo's rainfall calendar.
SEASONAL_PHASE_SHIFT_MONTHS = {"COL": 0, "BDL": 6, "GLE": 0}


def _add_months(anchor: date, months: int) -> date:
    """Shift a date back/forward by whole months, clamping the day-of-month."""
    total = anchor.month - 1 + months
    year = anchor.year + total // 12
    month = total % 12 + 1
    # 28 is safe for every month and keeps monthly spacing uniform.
    day = min(anchor.day, 28)
    return date(year, month, day)


class TrajectorySource:
    """Loads v11 once and hands out re-dated, regionally-conditioned trajectories."""

    def __init__(self, csv_path: str = C.V11_CSV, seed: int = C.RANDOM_SEED) -> None:
        self._df = pd.read_csv(csv_path)
        self._df["snapshot_date"] = pd.to_datetime(self._df["snapshot_date"])
        self._df.sort_values(["vehicle_id", "snapshot_date"], inplace=True)
        self._by_vehicle = {vid: g for vid, g in self._df.groupby("vehicle_id", sort=True)}
        self._rng = random.Random(seed)

        # Hard bounds for clipping, v11's own observed extremes, so a
        # regionally-adjusted value can never leave the trained domain.
        self._bounds = {c: (float(self._df[c].min()), float(self._df[c].max()))
                        for c in C.ENV_COLS}

        # Month-conditional pools for the seasonal re-draw.
        month = self._df["snapshot_date"].dt.month
        self._seasonal_pool = {
            m: {c: sub[c].to_numpy() for c in SEASONAL_COLS}
            for m, sub in self._df.groupby(month)
        }

    # ── selection ─────────────────────────────────────────────────────────────
    def vehicles_by_type(self) -> dict[str, list[str]]:
        """Distinct v11 vehicle ids grouped by vehicle_type, with >= the
        required number of snapshots. Order is deterministic (sorted) so a
        given seed always yields the same fleet."""
        out: dict[str, list[str]] = {}
        for vid, g in self._by_vehicle.items():
            if len(g) < C.SNAPSHOTS_PER_ASSET:
                continue
            out.setdefault(g["vehicle_type"].iloc[0], []).append(vid)
        return out

    def bounds(self) -> dict[str, tuple[float, float]]:
        return dict(self._bounds)

    # ── extraction ────────────────────────────────────────────────────────────
    def take(self, vehicle_id: str, warehouse_short: str, end_date: date) -> pd.DataFrame:
        """Return this vehicle's last N snapshots, re-dated to end on
        ``end_date`` and conditioned for ``warehouse_short``."""
        g = self._by_vehicle[vehicle_id].tail(C.SNAPSHOTS_PER_ASSET).copy()
        g.reset_index(drop=True, inplace=True)
        n = len(g)

        # 1. Re-date: uniform monthly spacing ending exactly on end_date.
        #    Kept as datetime64 (not python `date` objects) so downstream
        #    consumers can use .dt accessors and Timestamp comparisons.
        g["snapshot_date"] = pd.to_datetime([
            end_date if i == n - 1 else _add_months(end_date, -(n - 1 - i))
            for i in range(n)
        ])

        # 2. Seasonal re-draw against the new calendar month.
        phase = SEASONAL_PHASE_SHIFT_MONTHS.get(warehouse_short, 0)
        redrawn = {c: [] for c in SEASONAL_COLS}
        for d in g["snapshot_date"]:
            pool_month = (d.month - 1 + phase) % 12 + 1
            pool = self._seasonal_pool[pool_month]
            idx = self._rng.randrange(len(pool[SEASONAL_COLS[0]]))
            for c in SEASONAL_COLS:
                redrawn[c].append(float(pool[c][idx]))
        for c in SEASONAL_COLS:
            g[c] = redrawn[c]

        # 3. Regional adjustment, then clip into v11's observed range.
        adjust = C.REGIONAL_ADJUST.get(warehouse_short, {})
        for col in C.ENV_COLS:
            lo, hi = self._bounds[col]
            if col in adjust:
                mult, offset = adjust[col]
                g[col] = g[col] * mult + offset
            g[col] = g[col].clip(lower=lo, upper=hi).round(2)

        return g


def derive_manufacture_year(age_years_final: float, end_date: date) -> int:
    """Manufacture year implied by the vehicle's age at its final snapshot.

    Derived rather than carried over from v11: re-dating moves the trajectory
    forward in time, so the original manufacture_year would no longer agree with
    ``vehicle_age_years``. Deriving it keeps age and build year consistent, which
    matters because both are model features.
    """
    end_frac = end_date.year + (end_date.timetuple().tm_yday / 365.25)
    return int(round(end_frac - float(age_years_final)))
