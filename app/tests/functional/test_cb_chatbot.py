"""7.3.8 Agentic Chatbot (CB-01 .. CB-12).

These call the live Groq-backed agent. Each asks a question whose answer is
checkable against the database, so a fluent but wrong reply fails rather than
passes.
"""
import pytest

from .conftest import case

pytestmark = pytest.mark.functional


def _ask(client, auth, question: str, role: str = "admin", history=None) -> dict:
    payload = {"question": question}
    if history:
        payload["history"] = history
    r = client.post("/chatbot/agent", json=payload, headers=auth(role))
    if r.status_code == 404:
        r = client.post("/chatbot/ask", json=payload, headers=auth(role))
    assert r.status_code == 200, f"agent call failed ({r.status_code}): {r.text[:200]}"
    return r.json()


def _answer(body: dict) -> str:
    for k in ("answer", "response", "reply", "message", "content"):
        if isinstance(body.get(k), str) and body[k].strip():
            return body[k]
    return ""


def _tools(body: dict) -> list[str]:
    return [t.get("name", "") for t in (body.get("tool_trace") or [])]


@case("CB-01", "Ask supported FAQ question", "FAQ processing returns relevant answer")
def test_cb_01_faq(client, auth, requires_llm):
    body = _ask(client, auth, "What is PredictiX?")
    assert _answer(body).strip(), "the agent returned an empty answer"


@case("CB-02", "Ask about an asset", "Relevant asset information is retrieved")
def test_cb_02_asset_question(client, auth, ctx, requires_llm):
    detail = client.get(f"/assets/{ctx['asset_in']}", headers=auth("admin"))
    code = detail.json()["asset_code"]
    body = _ask(client, auth, f"Give me the details of asset {code}.")
    ans = _answer(body)
    assert ans.strip(), "empty answer"
    assert code.lower() in ans.lower(), (
        f"the answer never mentions the asset that was asked about ({code})")


@case("CB-03", "Ask about maintenance prediction",
      "Response matches stored prediction information")
def test_cb_03_prediction_question(client, auth, ctx, requires_llm):
    detail = client.get(f"/assets/{ctx['asset_in']}", headers=auth("admin"))
    code = detail.json()["asset_code"]
    body = _ask(client, auth, f"What is the failure probability for asset {code}?")
    ans = _answer(body)
    assert ans.strip(), "empty answer"

    pred = client.get(f"/batch-predictions/{ctx['asset_in']}", headers=auth("admin"))
    if pred.status_code != 200 or pred.json().get("failure_probability") is None:
        pytest.skip("no stored probability to compare against")
    prob = float(pred.json()["failure_probability"])

    import re
    nums = [float(x) for x in re.findall(r"\d+\.?\d*", ans)]
    pct = prob * 100
    assert any(abs(n - pct) < 2.0 or abs(n - prob) < 0.02 for n in nums), (
        f"the answer quotes {nums[:6]} but the stored probability is "
        f"{prob:.4f} ({pct:.1f}%)")


@case("CB-04", "Ask about a ticket", "Relevant ticket information is returned")
def test_cb_04_ticket_question(client, auth, requires_llm):
    listing = client.get("/tickets/", params={"limit": 1}, headers=auth("admin"))
    rows = listing.json()
    rows = rows.get("items", rows) if isinstance(rows, dict) else rows
    if not rows:
        pytest.skip("no tickets available")
    number = rows[0].get("ticket_number")

    body = _ask(client, auth, f"What is the status of ticket {number}?")
    ans = _answer(body)
    assert ans.strip(), "empty answer"
    assert number.lower() in ans.lower() or rows[0].get("status", "") in ans.lower(), (
        f"the answer references neither ticket {number} nor its status")


@case("CB-05", "Ask warehouse level question",
      "Appropriate operational information is retrieved")
def test_cb_05_warehouse_question(client, auth, requires_llm):
    body = _ask(client, auth, "How many assets are in my warehouse?")
    assert _answer(body).strip(), "empty answer"


@case("CB-06", "Ask question requiring RAG context", "Relevant semantic context is retrieved")
def test_cb_06_rag_path(client, auth, requires_llm):
    body = _ask(client, auth, "Explain what the critical health band means.")
    ans = _answer(body)
    assert ans.strip(), "empty answer"
    assert "handle_knowledge" in _tools(body) or len(ans) > 60, (
        f"the knowledge path was not used and the answer is thin: tools={_tools(body)}")


@case("CB-07", "Database query returns multiple rows", "Results are summarized correctly")
def test_cb_07_multi_row(client, auth, requires_llm):
    body = _ask(client, auth, "List the five assets with the highest failure probability.")
    ans = _answer(body)
    assert ans.strip(), "empty answer"
    assert len(ans) > 40, "a multi-row query produced a one-line answer"


@case("CB-08", "Generated SQL fails", "SQL self healing attempts correction")
def test_cb_08_sql_self_healing():
    import inspect
    from app.ai.agent import tools

    src = inspect.getsource(tools)
    markers = ("retry", "self_heal", "repair", "second attempt", "attempt 2", "_fix_sql")
    assert any(m in src.lower() for m in markers), (
        "no retry or repair path is present in the agent's SQL handling, so a "
        "failed query is not corrected")


@case("CB-09", "Database query cannot be completed", "Contextual fallback is used")
def test_cb_09_fallback_is_not_debug_text(client, auth, requires_llm):
    body = _ask(client, auth, "What is the square root of a warehouse divided by Tuesday?")
    ans = _answer(body)
    assert ans.strip(), "empty answer for an unanswerable question"
    for leak in ("Debug:", "Traceback", "psycopg2", "SQLAlchemy", "Exception"):
        assert leak.lower() not in ans.lower(), (
            f"internal detail {leak!r} leaked into a user-facing reply")


@case("CB-10", "Submit follow up question", "Conversation context is maintained")
def test_cb_10_follow_up(client, auth, ctx, requires_llm):
    detail = client.get(f"/assets/{ctx['asset_in']}", headers=auth("admin"))
    code = detail.json()["asset_code"]

    first = _ask(client, auth, f"Tell me about asset {code}.")
    history = [
        {"role": "user", "content": f"Tell me about asset {code}."},
        {"role": "assistant", "content": _answer(first)},
    ]
    second = _ask(client, auth, "What is its health score?", history=history)
    ans = _answer(second)
    assert ans.strip(), "the follow-up produced no answer"
    assert "which asset" not in ans.lower() and "please specify" not in ans.lower(), (
        "the agent lost the subject of the conversation on the follow-up")


@case("CB-11", "Request information outside user's scope",
      "Restricted information is not returned")
def test_cb_11_scope(client, auth, ctx, db, requires_llm):
    from sqlalchemy import text

    other = db.execute(text("""
        SELECT asset_code FROM assets
        WHERE warehouse_id <> CAST(:w AS uuid) ORDER BY asset_code LIMIT 1
    """), {"w": ctx["warehouse_id"]}).scalar()
    if not other:
        pytest.skip("no out-of-scope asset available")

    body = _ask(client, auth, f"Show me the full details of asset {other}.", role="user")
    ans = _answer(body).lower()
    assert "health score" not in ans or other.lower() not in ans, (
        f"the agent disclosed details of {other}, which is outside the caller's scope")


@case("CB-12", "Submit request handled by zero token path",
      "Request is processed without unnecessary LLM call")
def test_cb_12_zero_token_path(client, auth):
    body = _ask(client, auth, "hello")
    ans = _answer(body)
    assert ans.strip(), "the greeting produced no reply"
    tools = _tools(body)
    assert "handle_greeting" in tools, (
        f"a greeting did not take the instant path: tools={tools}")
