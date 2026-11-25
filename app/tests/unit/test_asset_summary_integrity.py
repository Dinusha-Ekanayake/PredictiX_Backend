"""An asset summary never states what the asset's data does not."""
from __future__ import annotations

import pytest

import app.ai.services.asset_summary_service as svc

INPUT = ("Asset: Komatsu FD30 130 | Type: vehicle | Vehicle type: Forklift_3.0T | Year: 2021 | "
         "Fuel: LPG | Status: active | Health: Critical | Health score: 31.5 | "
         "Criticality score: 74.05 | Maintenance priority: high | Service due in: 12 days | Risk: high")
CALM_INPUT = INPUT.replace("Health: Critical", "Health: Excellent").replace(
    "Maintenance priority: high", "Maintenance priority: low").replace("Risk: high", "Risk: low")


@pytest.mark.parametrize("text,expected_prefix", [
    ("Forklift_3.0T 130 is critical. Current criticality score: 74.05 (out of a possible 74).",
     "figures not in the asset data: 74"),                                  # invented bound (seen in prod)
    ("Komatsu FD30 130 requires diesel fuel and attention within 12 days.", "hallucinated content"),
    ("Komatsu FD30 130 Cargo: pallets. Service due in 12 days.", "hallucinated content"),
    ("Komatsu FD30 130 requires no maintenance this period. Priority is high.", "says no maintenance is needed"),
    ("Too short.", "too short"),
], ids=["invented-figure", "fuel-hallucination", "cargo-label", "no-maintenance-but-urgent", "too-short"])
def test_unpublishable_answers_are_rejected_with_a_reason(text, expected_prefix):
    assert svc.rejection_reason(text, INPUT).startswith(expected_prefix)


@pytest.mark.parametrize("text", [
    "Komatsu FD30 130 (2021, LPG) is in critical health with a criticality score of 74.05; service is due in 12 days.",
    "Komatsu FD30 130 health score is 31.5. Maintenance priority: high.",   # a restated label is style, not fabrication
    "Komatsu FD30 130 has health 31.5.",                                     # number ending a sentence is still 31.5
], ids=["grounded", "restated-label", "trailing-period"])
def test_grounded_answers_are_published(text):
    assert svc.rejection_reason(text, INPUT) is None


def test_no_maintenance_is_fine_for_an_asset_in_good_shape():
    assert svc.rejection_reason("Komatsu FD30 130 requires no maintenance this period, due in 12 days.", CALM_INPUT) is None


def test_summarize_reports_why_the_template_was_used(monkeypatch):
    monkeypatch.setattr(svc, "_summarize_via_space", lambda space, text: None)
    out = svc.summarize_asset(INPUT)
    assert (out.source, out.fallback_reason) == ("template", "unavailable")

    monkeypatch.setattr(svc, "_summarize_via_space", lambda space, text: "Score 74.05 of a possible 74 for Komatsu FD30 130.")
    out = svc.summarize_asset(INPUT)
    assert out.source == "template" and out.fallback_reason.startswith("rejected: figures not in the asset data")

    good = "Komatsu FD30 130 is in critical health; service is due in 12 days."
    monkeypatch.setattr(svc, "_summarize_via_space", lambda space, text: good)
    out = svc.summarize_asset(INPUT)
    assert (out.summary, out.source, out.fallback_reason) == (good, "model", None)


def test_the_template_itself_is_grounded(monkeypatch):
    monkeypatch.setattr(svc, "_summarize_via_space", lambda space, text: None)
    out = svc.summarize_asset(INPUT)
    assert svc._numbers_in(out.summary) <= svc._numbers_in(INPUT)
