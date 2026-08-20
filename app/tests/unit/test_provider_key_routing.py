"""Each provider credential belongs to one purpose, and this pins which.

The environment carries two Groq keys and two Brevo keys.
Nothing at runtime fails if a caller reaches for the wrong one: the mail still
sends and the model still answers, just billed to another budget and sent from
another account. These tests are the only thing that notices.

Current routing:
  chatbot / agent LLM        Groq   WH_GROQ_API_KEY, then CHATBOT_GROQ_API_KEY
  warehouse report LLM       Groq   WH_GROQ_API_KEY, model from WH_GROQ_MODEL
  warehouse report mail      Brevo  WH_BREVO_API_KEY
  ticket / FAQ / in-app mail Brevo  BREVO_API_KEY
"""
import inspect
import pathlib
import re

import pytest


def test_groq_keys_are_the_chatbot_keys():
    from app.ai.services import llm_service

    src = inspect.getsource(llm_service._get_api_keys)

    assert "CHATBOT_GROQ_API_KEY" in src
    assert "WH_GROQ_API_KEY" in src
    # A key for a different provider would be accepted and simply fail to
    # authorise, so it must never reach the Groq client.
    assert "OPENROUTER" not in src


def test_warehouse_report_llm_uses_the_warehouse_key():
    """Read as text, not imported: this must hold even when the report module's
    own dependencies are unavailable, which is exactly when it gets edited."""
    repo = pathlib.Path(__file__).resolve().parents[3]
    src = (repo / "app" / "agents" / "report_agents.py").read_text(encoding="utf-8")
    body = src[src.index("def _get_llm("):]
    body = body[: body.index("\ndef ", 1)]

    # Report generation is billed to the warehouse budget, not the chatbot's.
    assert "WH_GROQ_API_KEY" in body
    assert body.index("WH_GROQ_API_KEY") < body.index("CHATBOT_GROQ_API_KEY")
    assert "WH_GROQ_MODEL" in body


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
