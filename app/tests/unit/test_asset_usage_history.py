"""The asset section's utilisation and service-cadence charts read this service.

The charts plot time on the x-axis, so ordering and the month window are part
of the contract, not presentation detail. A reversed series draws the asset's
history backwards, and an unbounded window returns five years of points into a
panel sized for two.
"""
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.asset_usage_history_service import (
    DEFAULT_MONTHS,
    MAX_MONTHS,
    get_asset_usage_history,
)


class FakeQuery:
    """Records the limit asked for and replays rows newest-first, as the real
    query does, so the service's own reversal is what gets tested."""

    def __init__(self, rows, spy):
        self._rows = rows
        self._spy = spy

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def limit(self, n):
        self._spy["limit"] = n
        return FakeQuery(self._rows[:n], self._spy)

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.spy = {}

    def query(self, *a, **k):
        return FakeQuery(self.rows, self.spy)


def reading(day: int, op=10.0, idle=2.0, dist=100.0, dsls=5, down=1.0):
    """One stored reading, newest-first callers build these in reverse."""
    return SimpleNamespace(
        recorded_at=datetime(2026, 1, day, tzinfo=timezone.utc),
        operating_hours_last_30d=Decimal(str(op)),
        idle_hours_last_30d=Decimal(str(idle)),
        distance_last_30d_km=Decimal(str(dist)),
        days_since_last_service=dsls,
        downtime_hours_last_90d=Decimal(str(down)),
    )


def test_points_come_back_oldest_first():
    # The database hands back newest-first; the chart needs the opposite.
    db = FakeSession([reading(3), reading(2), reading(1)])

    points = get_asset_usage_history(db, "asset-1")

    assert [p.period for p in points] == [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]


def test_default_window_is_requested_when_caller_does_not_ask():
    db = FakeSession([reading(1)])

    get_asset_usage_history(db, "asset-1")

    assert db.spy["limit"] == DEFAULT_MONTHS


def test_window_is_capped_so_a_huge_request_cannot_pull_everything():
    db = FakeSession([reading(1)])

    get_asset_usage_history(db, "asset-1", months=10_000)

    assert db.spy["limit"] == MAX_MONTHS


def test_window_of_zero_or_less_still_asks_for_one_month():
    db = FakeSession([reading(1)])

    get_asset_usage_history(db, "asset-1", months=0)

    assert db.spy["limit"] == 1


def test_asset_with_no_readings_returns_empty_not_an_error():
    db = FakeSession([])

    assert get_asset_usage_history(db, "asset-1") == []


def test_stored_decimals_become_rounded_floats():
    db = FakeSession([reading(1, op=Decimal("12.349"), dist=Decimal("100.06"))])

    p = get_asset_usage_history(db, "asset-1")[0]

    assert p.operating_hours == 12.3
    assert p.distance_km == 100.1
    assert isinstance(p.operating_hours, float)


def test_missing_values_stay_none_rather_than_becoming_zero():
    # A month that recorded nothing must not plot as a month of zero work.
    row = reading(1)
    row.operating_hours_last_30d = None
    row.days_since_last_service = None
    row.downtime_hours_last_90d = None
    db = FakeSession([row])

    p = get_asset_usage_history(db, "asset-1")[0]

    assert p.operating_hours is None
    assert p.days_since_last_service is None
    assert p.downtime_hours_90d is None
    assert p.idle_hours == 2.0


def test_unparseable_value_degrades_to_none_instead_of_raising():
    row = reading(1)
    row.idle_hours_last_30d = "not a number"
    db = FakeSession([row])

    assert get_asset_usage_history(db, "asset-1")[0].idle_hours is None


def test_reading_without_a_timestamp_is_dropped():
    # period is the x-axis; a point with no date cannot be placed on it.
    row = reading(1)
    row.recorded_at = None
    db = FakeSession([row, reading(2)])

    points = get_asset_usage_history(db, "asset-1")

    assert len(points) == 1
    assert points[0].period == date(2026, 1, 2)


def test_days_since_last_service_is_an_int_for_the_sawtooth_line():
    db = FakeSession([reading(1, dsls=47)])

    assert get_asset_usage_history(db, "asset-1")[0].days_since_last_service == 47
