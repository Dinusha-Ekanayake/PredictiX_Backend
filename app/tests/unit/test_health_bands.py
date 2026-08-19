"""Health bands are the one definition every screen bands a score with.

Thresholds kept in more than one place put the same asset in different bands
depending on the screen. These tests pin the shared definition and the two
places that derive from it.
"""
import pytest

from app.services.health_bands import (
    CRITICAL_BAND,
    HEALTH_BAND_NAMES,
    HEALTH_BAND_THRESHOLDS,
    band_bounds,
    band_case_sql,
    band_for,
)

# The Postgres asset_health_band enum, best to worst.
DB_ENUM = ("excellent", "good", "moderate", "poor", "critical")

# Highest health_score the fleet actually produces. Any band cut-off above
# this can never match, which is how "healthy" became unreachable before.
OBSERVED_MAX_SCORE = 79.0


def test_band_names_match_the_database_enum():
    assert HEALTH_BAND_NAMES == DB_ENUM


@pytest.mark.parametrize(
    "score, expected",
    [
        (100, "excellent"),
        (79, "excellent"),
        (60, "excellent"),   # inclusive lower bound
        (59.99, "good"),
        (50, "good"),
        (49.99, "moderate"),
        (38, "moderate"),
        (37.99, "poor"),
        (25, "poor"),
        (24.99, "critical"),
        (0, "critical"),
    ],
)
def test_band_for_boundaries(score, expected):
    assert band_for(score) == expected


@pytest.mark.parametrize("bad", [None, float("nan")])
def test_band_for_returns_none_when_unscorable(bad):
    """No prediction is not the same as a bad prediction."""
    assert band_for(bad) is None


def test_every_band_is_reachable_below_the_observed_ceiling():
    reachable = {band_for(s) for s in range(0, int(OBSERVED_MAX_SCORE) + 1)}
    assert reachable == set(DB_ENUM), f"unreachable bands: {set(DB_ENUM) - reachable}"


def test_thresholds_are_strictly_descending():
    lowers = [lower for _, lower in HEALTH_BAND_THRESHOLDS]
    assert lowers == sorted(lowers, reverse=True)
    assert all(0 <= v <= 100 for v in lowers)


def test_bands_partition_the_range_without_gaps():
    """Each band's lower bound is the next band's upper bound."""
    for i, name in enumerate(HEALTH_BAND_NAMES[:-1]):
        lower, _ = band_bounds(name)
        next_lower, next_upper = band_bounds(HEALTH_BAND_NAMES[i + 1])
        assert next_upper == lower


def test_band_case_sql_agrees_with_band_for():
    """The set-based SQL and the Python path must classify identically."""
    sql = band_case_sql("health_score")
    for name, lower in HEALTH_BAND_THRESHOLDS:
        assert f"WHEN health_score >= {lower} THEN '{name}'" in sql
    assert f"ELSE '{CRITICAL_BAND}'" in sql
