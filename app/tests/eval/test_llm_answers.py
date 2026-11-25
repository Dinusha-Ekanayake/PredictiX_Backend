"""Answer-level evaluation of the help chatbot against the live language model.

Retrieval quality is gated in test_rag_retrieval_eval.py. This checks the
step after it, with the real model:

- groundedness: an answerable question gets an answer that cites the help
  item it was built from;
- refusal: a hard negative (a question that mentions PredictiX subjects the
  help content does not answer) gets "not covered", even though retrieval
  may hand the model related items.

Opt-in, because it spends model quota and depends on a third-party service:

    RUN_LLM_TESTS=1 pytest app/tests/eval/test_llm_answers.py -m llm -s
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from dotenv import load_dotenv

load_dotenv()

pytestmark = [pytest.mark.llm, pytest.mark.eval]

DATA = json.loads((Path(__file__).resolve().parents[1] / "data" / "rag_golden.json").read_text(encoding="utf-8"))
NOT_COVERED = "couldn't find that in the PredictiX help content"
MIN_GROUNDED = 0.85
MIN_REFUSED = 0.80


@pytest.fixture(scope="module")
def ask():
    if os.getenv("RUN_LLM_TESTS") != "1":
        pytest.skip("set RUN_LLM_TESTS=1 to call the live language model")
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL is not set")
    from app.ai.agent.tools import ToolContext, answer_from_help
    from app.ai.services.llm_service import call_groq
    from app.chatbot.knowledge_service import search_help

    try:
        call_groq(messages=[{"role": "user", "content": "Reply with OK."}], max_tokens=5)
    except Exception as exc:
        pytest.skip(f"language model unavailable: {exc}")

    ctx = ToolContext(db=None, user=SimpleNamespace(id="eval", role="user", warehouse_id=None, full_name="Eval User"))

    def _ask(question: str) -> dict:
        hits = search_help(question, 4)
        return {"hits": hits, "answer": answer_from_help(question, ctx, hits)["answer"]}

    return _ask


def test_answers_are_grounded_and_cite_their_source(ask):
    items = [i for i in DATA["answerable"] if i["split"] == "heldout"]
    grounded, report = 0, []
    for item in items:
        out = ask(item["q"])
        ok = NOT_COVERED not in out["answer"] and "Sources:" in out["answer"] and any(
            e.lower() in out["answer"].lower().split("sources:", 1)[-1] for e in item["expected"]
        )
        grounded += ok
        report.append(f"  {'OK  ' if ok else 'FAIL'} {item['q'][:60]}")
    print("\n".join(["\nGrounded answers"] + report))
    rate = grounded / len(items)
    assert rate >= MIN_GROUNDED, f"grounded answers {rate:.0%} < {MIN_GROUNDED:.0%}"


def test_hard_negatives_are_reported_as_not_covered(ask):
    questions = DATA["hard_negative"]
    refused = sum(NOT_COVERED in ask(q)["answer"] for q in questions)
    rate = refused / len(questions)
    assert rate >= MIN_REFUSED, f"hard negatives refused {rate:.0%} < {MIN_REFUSED:.0%}"
