"""The nightly knowledge-base refresh only runs where the local model exists."""
from __future__ import annotations

import importlib.util

import pytest

import app.main as main


@pytest.mark.parametrize("flag,expected", [("true", True), ("1", True), ("false", False), ("no", False)])
def test_the_flag_overrides_detection(monkeypatch, flag, expected):
    monkeypatch.setenv("KB_REFRESH_ENABLED", flag)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: pytest.fail("detection must not run"))
    assert main.kb_refresh_enabled() is expected


@pytest.mark.parametrize("installed", [True, False])
def test_auto_follows_whether_sentence_transformers_is_installed(monkeypatch, installed):
    monkeypatch.delenv("KB_REFRESH_ENABLED", raising=False)
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name: object() if installed and name == "sentence_transformers" else None)
    assert main.kb_refresh_enabled() is installed
