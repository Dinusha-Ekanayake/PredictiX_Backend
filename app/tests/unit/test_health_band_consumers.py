"""Every screen that reports health must use the shared band definition.

Regression for the "critical" count disagreeing across screens for the same
warehouse: admin dashboard 127 (shared bands, < 25), warehouse page 366
(hard-coded < 60), AI report < 30, KB benchmark text "< 50% health".
"""
from app.services.health_bands import CRITICAL_THRESHOLD, HEALTH_BAND_NAMES, band_bounds

GOOD_FROM = band_bounds("good")[0]
MODERATE_FROM = band_bounds("moderate")[0]


def test_warehouse_dashboard_uses_shared_cutoffs():
    from app.routers import warehouse_dashboard as wd

    assert wd.HEALTHY_FROM == GOOD_FROM
    assert wd.AT_RISK_BELOW == MODERATE_FROM


def test_warehouse_band_labels_cover_every_band():
    from app.routers.warehouse_dashboard import _band_range_label

    labels = {band: _band_range_label(band) for band in HEALTH_BAND_NAMES}
    assert labels["critical"] == f"< {CRITICAL_THRESHOLD:g}%"
    assert labels["excellent"].startswith("≥ ")
    assert len(set(labels.values())) == len(HEALTH_BAND_NAMES)


def test_report_agent_bands_are_the_shared_bands():
    from app.agents import report_agents as ra

    assert ra._BAND_EXCELLENT == band_bounds("excellent")[0]
    assert ra._BAND_GOOD == GOOD_FROM
    assert ra._BAND_MODERATE == MODERATE_FROM
    assert ra._BAND_CRITICAL == CRITICAL_THRESHOLD


def test_kb_benchmark_states_the_real_critical_cutoff():
    from app.kb.kb_annotator import compute_benchmark_alerts

    ctx = {"total_assets": 100, "critical_count": 30, "at_risk_count": 45}
    message = " ".join(a["message"] for a in compute_benchmark_alerts(ctx))
    assert f"<{CRITICAL_THRESHOLD:g}% health" in message
    assert f"<{MODERATE_FROM:g}% health" in message
    assert "<50% health" not in message and "<60% health" not in message
