"""The single definition of an asset's health band.

Why this exists
---------------
The same fleet was being reported two different ways on two screens. The admin
dashboard banded ``pdm_batch_predictions.health_score`` at 90/75/60/40 and
reported 161 critical assets for Colombo; the assets list read
``assets.health_band`` and reported 13. Both screens called the result
"critical", so the numbers looked simply wrong.

Two separate problems caused that:

1. **The dashboard thresholds were never calibrated.** ``health_score`` is
   ``_compute_health_score`` in the batch service, the mean of five component
   health percentages *minus* a penalty for failure probability and urgency. It
   is therefore systematically lower than raw component health. Observed across
   the fleet: min 0.0, p25 35.0, median 42.6, p75 50.9, max **79.0**. Against a
   90-point "Excellent" cut-off, *no asset can ever be Excellent*, "Good"
   captured one asset in four hundred, and 91% of a normally-worn fleet
   rendered as Poor or Critical. An alert that fires on nine assets in ten is
   not an alert.

2. **``assets.health_band`` had no owner.** Nothing in the backend wrote it, it was set once at seed time and read forever after, so it could only drift.
   ``batch_prediction_service`` now maintains it from the same score through
   :func:`band_for`, which is what makes the two screens agree by construction
   rather than by coincidence.

Calibration
-----------
Thresholds are set against the actual ``health_score`` distribution so each
band means something and every band is reachable:

    excellent  >= 60     ~8.5%
    good       >= 50     ~18.5%
    moderate   >= 38     ~38.6%
    poor       >= 25     ~24.9%
    critical   <  25     ~9.5%

Cross-checked against the model's own decision layer
(``pdm_decision_service.build_decision``), which independently puts ~30% of the
fleet at ``urgent``, consistent with the ~35% landing in poor/critical here,
and with the 29% positive rate the v7 classifier was trained on.

These bands describe *relative fleet condition*, not an absolute engineering
grade. They are a triage aid for sorting and filtering; the authoritative
per-asset call is the PdM tier, and component-level risk comes from the
survival models.
"""

from __future__ import annotations

#: Ordered best -> worst. Each entry is (band name, inclusive lower bound).
#: Anything below the last bound falls into :data:`CRITICAL_BAND`.
HEALTH_BAND_THRESHOLDS: tuple[tuple[str, float], ...] = (
    ("excellent", 60.0),
    ("good", 50.0),
    ("moderate", 38.0),
    ("poor", 25.0),
)

CRITICAL_BAND = "critical"

#: Every band, best -> worst. Matches the ``asset_health_band`` enum.
HEALTH_BAND_NAMES: tuple[str, ...] = tuple(
    name for name, _ in HEALTH_BAND_THRESHOLDS
) + (CRITICAL_BAND,)

#: The band the "Critical Alerts" KPI counts, so the headline number and the
#: Critical slice of the distribution chart can never diverge again.
CRITICAL_THRESHOLD: float = HEALTH_BAND_THRESHOLDS[-1][1]


def band_for(score: float | int | None) -> str | None:
    """Band a health score. ``None`` in, ``None`` out, an asset with no
    completed prediction has no band, which is distinct from a bad one."""
    if score is None:
        return None
    try:
        value = float(score)
    except (TypeError, ValueError):
        return None
    if value != value:  # NaN
        return None
    for name, lower in HEALTH_BAND_THRESHOLDS:
        if value >= lower:
            return name
    return CRITICAL_BAND


def band_bounds(band: str) -> tuple[float | None, float | None]:
    """``(lower_inclusive, upper_exclusive)`` for a band, for building SQL."""
    names = list(HEALTH_BAND_NAMES)
    if band not in names:
        raise ValueError(f"unknown health band: {band!r}")
    idx = names.index(band)
    lower = None if band == CRITICAL_BAND else HEALTH_BAND_THRESHOLDS[idx][1]
    upper = HEALTH_BAND_THRESHOLDS[idx - 1][1] if idx > 0 else None
    return lower, upper


def band_case_sql(column: str = "health_score") -> str:
    """A SQL ``CASE`` mapping ``column`` to a band name.

    Built from the same thresholds as :func:`band_for` so a set-based UPDATE
    and the Python path can never disagree.
    """
    whens = "\n                ".join(
        f"WHEN {column} >= {lower} THEN '{name}'"
        for name, lower in HEALTH_BAND_THRESHOLDS
    )
    return f"CASE\n                {whens}\n                ELSE '{CRITICAL_BAND}'\n            END"


def band_count_sql(column: str = "health_score") -> str:
    """``COUNT(*) FILTER (...)`` fragments, one per band, best -> worst.

    Generated from the thresholds above rather than written out, so the chart
    bands and :func:`band_for` cannot drift apart.
    """
    parts: list[str] = []
    for band in HEALTH_BAND_NAMES:
        lower, upper = band_bounds(band)
        conds = []
        if lower is not None:
            conds.append(f"{column} >= {lower}")
        if upper is not None:
            conds.append(f"{column} < {upper}")
        where = " AND ".join(conds) if conds else "TRUE"
        parts.append(f"COUNT(*) FILTER (WHERE {where}) AS h_{band}")
    return ",\n            ".join(parts)
