"""Each provider credential belongs to one purpose, and this pins which.

The environment carries two Groq keys, an OpenRouter key and two Brevo keys.
Nothing at runtime fails if a caller reaches for the wrong one: the mail still
sends and the model still answers, just billed to another budget and sent from
another account. These tests are the only thing that notices.

Current routing:
  chatbot / agent LLM        Groq          CHATBOT_GROQ_API_KEY, WH_GROQ_API_KEY
  warehouse report LLM       OpenRouter    OPENROUTER_API_KEY
  warehouse report mail      Brevo         WH_BREVO_API_KEY
  ticket / FAQ / in-app mail Brevo         BREVO_API_KEY
"""
import importlib
import inspect
import pathlib
import re

import pytest


def test_groq_keys_are_the_chatbot_keys():
    from app.ai.services import llm_service

    src = inspect.getsource(llm_service._get_api_keys)

    assert "CHATBOT_GROQ_API_KEY" in src
    assert "WH_GROQ_API_KEY" in src
    # OpenRouter is a different provider and must never be handed to Groq.
    assert "OPENROUTER" not in src


def test_warehouse_report_llm_stays_on_openrouter():
    """Read as text, not imported: this must hold even when the report module's
    own dependencies are unavailable, which is exactly when it gets edited."""
    repo = pathlib.Path(__file__).resolve().parents[3]
    src = (repo / "app" / "agents" / "report_agents.py").read_text(encoding="utf-8")
    body = src[src.index("def _get_llm("):]
    body = body[: body.index("\ndef ", 1)]

    assert "OPENROUTER_API_KEY" in body
    assert "openrouter.ai" in body
    # A Groq key here would be accepted and simply fail to authorise.
    assert "GROQ_API_KEY" not in body


@pytest.mark.parametrize(
    "env, expected",
    [
        ({"CHATBOT_GROQ_MODEL": "model-a", "WH_GROQ_MODEL": "model-b"}, "model-a"),
        ({"WH_GROQ_MODEL": "model-b"}, "model-b"),
        ({}, "llama-3.3-70b-versatile"),
    ],
)
def test_chatbot_model_prefers_its_own_name_then_falls_back(monkeypatch, env, expected):
    """An existing deployment naming the model WH_GROQ_MODEL keeps working."""
    monkeypatch.delenv("CHATBOT_GROQ_MODEL", raising=False)
    monkeypatch.delenv("WH_GROQ_MODEL", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    from app.ai.services import llm_service

    reloaded = importlib.reload(llm_service)
    try:
        assert reloaded.CHATBOT_MODEL == expected
        # The chosen model heads the cascade the chatbot actually walks.
        assert reloaded.MODEL_CASCADE[0] == expected
        assert reloaded.FAST_MODELS[0] == expected
    finally:
        importlib.reload(llm_service)


def test_only_warehouse_report_mail_uses_the_warehouse_brevo_account():
    """Any other caller passing use_wh_key=True is sending from the wrong account."""
    import app.services.notification_service as notif
    import app.services.report_notification_service as report_notif

    callers = [
        rel
        for mod, rel in ((notif, "notification_service"),
                         (report_notif, "report_notification_service"))
        if "use_wh_key=True" in inspect.getsource(mod)
    ]

    assert callers == ["report_notification_service"]


def test_warehouse_mail_reads_the_warehouse_key_first():
    import app.services.notification_service as notif

    src = inspect.getsource(notif.NotificationService.send_email)
    branch = src[src.index("if use_wh_key:"):]
    # The warehouse names must both be consulted before the general key.
    wh = min(branch.index("WH_BREVO_API_KEY"), branch.index("WHBREVO"))
    assert wh < branch.index("BREVO_API_KEY\"")


def test_falling_back_to_the_general_account_is_announced():
    """Sending warehouse mail from the general account must not be silent."""
    import app.services.notification_service as notif

    src = inspect.getsource(notif.NotificationService.send_email)
    branch = src[src.index("if use_wh_key:"):]

    assert re.search(r"print\(.*WARNING", branch, re.S)
