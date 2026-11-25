"""A ticket summary is clean and shorter than the description it summarises."""
from __future__ import annotations

import pytest

import app.ai.services.ticket_summary_service as ts

LONG_DESC = ("The forklift FL-07 at the Colombo warehouse makes a grinding noise when lifting loads above one "
             "tonne. The hydraulic fluid level looked normal yesterday, but the mast hesitates halfway up and the "
             "operator reported a burning smell after twenty minutes of use.")
INPUT = ts.build_ticket_summary_input(
    title="Forklift mast hesitates", description=LONG_DESC, asset_code="FL-07", asset_name="Forklift",
    category="Mechanical", priority="high",
) if "asset_code" in ts.build_ticket_summary_input.__code__.co_varnames else (
    f"Title: Forklift mast hesitates | Description: {LONG_DESC} | Asset: FL-07 | Category: Mechanical | Priority: high")


def test_change_markers_are_stripped():
    assert ts._postprocess("Grinding noise above one tonne (Δ+1). Mast hesitates (Δ -2).") == \
        "Grinding noise above one tonne. Mast hesitates."


def test_a_model_summary_as_long_as_the_source_is_rejected(monkeypatch):
    echoed = LONG_DESC + " It needs attention."
    monkeypatch.setattr(ts, "_summarize_via_space", lambda space, text: echoed)
    out = ts.generate_ticket_summary(INPUT)
    assert out != echoed and len(out) < len(LONG_DESC)


def test_a_short_clean_model_summary_is_used(monkeypatch):
    good = "Forklift FL-07 mast hesitates under load with a burning smell; inspect the hydraulics."
    monkeypatch.setattr(ts, "_summarize_via_space", lambda space, text: good)
    assert ts.generate_ticket_summary(INPUT) == good


def test_the_fallback_is_shorter_than_a_long_description(monkeypatch):
    monkeypatch.setattr(ts, "_summarize_via_space", lambda space, text: None)
    out = ts.generate_ticket_summary(INPUT)
    assert out and len(out) < len(LONG_DESC)


@pytest.mark.parametrize("desc", ["Brake light out.", "Tyre flat on the left rear wheel"])
def test_short_descriptions_are_not_forced_shorter(monkeypatch, desc):
    monkeypatch.setattr(ts, "_summarize_via_space", lambda space, text: None)
    out = ts.generate_ticket_summary(f"Title: Fault | Description: {desc} | Priority: low")
    assert out  # a summary of a one-line description may be as long as it


def test_garbled_output_still_falls_back(monkeypatch):
    monkeypatch.setattr(ts, "_summarize_via_space", lambda space, text: "FPS FPS 1 2 3 4 5 6 7 8")
    assert "FPS" not in ts.generate_ticket_summary(INPUT)
