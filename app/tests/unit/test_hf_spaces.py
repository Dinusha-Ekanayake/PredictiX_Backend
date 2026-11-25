"""Waking the Hugging Face Spaces: hosts, readiness, waiting and the keep-alive job."""
from __future__ import annotations

import pytest
import requests

from app.ai.services import hf_spaces
from app.ai.services.hf_spaces import Space, space_host


@pytest.mark.parametrize("value,expected", [
    ("SharadaAbeywickrama/Ticket_summery_generation", "https://sharadaabeywickrama-ticket-summery-generation.hf.space"),
    ("Org.Name/my.space_v2", "https://org-name-my-space-v2.hf.space"),
    ("https://x-y.hf.space/", "https://x-y.hf.space"),
    ("  owner/name  ", "https://owner-name.hf.space"),
])
def test_space_host(value, expected):
    assert space_host(value) == expected


@pytest.mark.parametrize("bad", ["", "no-slash", "/name", "owner/"])
def test_space_host_rejects_non_spaces(bad):
    with pytest.raises(ValueError):
        space_host(bad)


def test_only_configured_spaces_are_used(monkeypatch):
    monkeypatch.setenv("HF_AI_SPACE_URL", "https://a.hf.space")
    monkeypatch.setenv("TICKET_SUMMARY_SPACE", "o/ticket")
    monkeypatch.delenv("ASSET_SUMMARY_SPACE", raising=False)
    assert [s.setting for s in hf_spaces.configured_spaces()] == ["HF_AI_SPACE_URL", "TICKET_SUMMARY_SPACE"]


class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


class FakeSession:
    """Answers each GET with the next scripted response."""

    def __init__(self, script):
        self.script, self.calls = list(script), []

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers))
        nxt = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


SPACE = Space("TICKET_SUMMARY_SPACE", "https://o-ticket.hf.space")


@pytest.mark.parametrize("response,ready", [
    (FakeResponse(200, {"version": "4"}), True),
    (FakeResponse(200, None), False),          # the "starting" placeholder page, not the app
    (FakeResponse(503, None), False),
    (requests.Timeout(), False),
], ids=["app-config", "html-placeholder", "sleeping-503", "timeout"])
def test_is_ready(response, ready):
    assert hf_spaces.is_ready(SPACE, FakeSession([response]))[0] is ready


def test_the_token_is_sent_to_private_spaces(monkeypatch):
    monkeypatch.setenv("HF_TOKEN_space", "hf_secret")
    session = FakeSession([FakeResponse(200, {})])
    hf_spaces.is_ready(SPACE, session)
    url, headers = session.calls[0]
    assert url == "https://o-ticket.hf.space/config" and headers == {"Authorization": "Bearer hf_secret"}


def test_wake_polls_until_the_space_is_ready():
    now = [0.0]
    session = FakeSession([FakeResponse(503, None), FakeResponse(200, None), FakeResponse(200, {"ok": 1})])
    result = hf_spaces.wake(SPACE, wait_s=600, session=session,
                            sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])
    assert result.ready and len(session.calls) == 3
    assert result.seconds == 2 * hf_spaces.POLL_INTERVAL_S


def test_wake_gives_up_after_the_wait():
    now = [0.0]
    result = hf_spaces.wake(SPACE, wait_s=60, session=FakeSession([FakeResponse(503, None)]),
                            sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])
    assert not result.ready and result.detail == "HTTP 503" and result.seconds >= 60


def test_the_keep_alive_job_never_raises(monkeypatch):
    def boom(**kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(hf_spaces, "wake_all", boom)
    hf_spaces.keep_warm_job()


def test_the_cli_fails_when_a_space_does_not_start(monkeypatch, capsys):
    monkeypatch.setattr(hf_spaces, "configured_spaces", lambda: [SPACE])
    monkeypatch.setattr(hf_spaces, "wake_all", lambda wait_s: [hf_spaces.WakeResult(SPACE, False, 600.0, "HTTP 503")])
    assert hf_spaces.main(["--wait", "1"]) == 1
    assert "FAILED" in capsys.readouterr().out


@pytest.mark.parametrize("value,expected", [(None, 6.0), ("12", 12.0), ("0", 0.0), ("-3", 0.0), ("soon", 6.0)])
def test_keepalive_interval(monkeypatch, value, expected):
    import app.main as main

    if value is None:
        monkeypatch.delenv("HF_SPACE_KEEPALIVE_HOURS", raising=False)
    else:
        monkeypatch.setenv("HF_SPACE_KEEPALIVE_HOURS", value)
    assert main.hf_keepalive_hours() == expected
