"""Measure chatbot help retrieval (FAQs + knowledge base) on a fixed question set.

Read-only. Reports hit@1 and hit@3 for questions with a known answer, and the
rejection rate for questions the help content should not answer. Run after
changing the embedding model, the threshold or the articles:

    python scripts/eval_rag.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.chatbot.knowledge_service import search_help  # noqa: E402

# Paraphrased on purpose: the wording differs from the stored question or title,
# so a hit needs meaning, not shared keywords.
ANSWERABLE = [
    ("I can't remember my password, what now?", ["forgot my password", "reset my password"]),
    ("Where do I change the password I log in with?", ["change my password", "reset my password"]),
    ("How do I sign out of PredictiX?", ["log out"]),
    ("How can I raise a new maintenance request?", ["open a ticket"]),
    ("Where can I see the tickets I submitted?", ["view my tickets"]),
    ("What do the different ticket priority levels mean?", ["ticket priorities", "Ticket Priority Thresholds"]),
    ("What states can a ticket be in?", ["ticket statuses"]),
    ("How does the system predict that a vehicle will break down?", ["failure prediction work", "failure probability"]),
    ("What does the failure probability number mean?", ["failure probability score"]),
    ("What counts as a critical alert?", ["critical alerts"]),
    ("How do I find a particular vehicle?", ["search for an asset", "view assets"]),
    ("How do I update my phone number or details?", ["update my profile"]),
    ("How can I upload a new profile photo?", ["Change Profile Picture"]),
    ("How do I talk to the support team?", ["contact support", "access help"]),
    ("Is my information kept safe?", ["data secure"]),
    ("What is this application for?", ["what is predictix"]),
    ("How often should a Toyota forklift get serviced?", ["Toyota Forklift"]),
    ("What does ISO 55000 say about fleet risk?", ["ISO 55000"]),
    ("Why do brakes matter so much for safety?", ["Brake Health"]),
    ("How do engine hours affect failure risk?", ["Engine Hours"]),
]

UNANSWERABLE = [
    "What is the capital of France?",
    "Give me a chocolate cake recipe",
    "Who won the football world cup?",
    "Write me a poem about the sea",
    "What is the price of bitcoin today?",
    "Translate hello into Japanese",
]


def _matches(hit: dict, expected: list[str]) -> bool:
    title = str(hit.get("title", "")).lower()
    return any(e.lower() in title for e in expected)


def main() -> int:
    top1 = top3 = 0
    for question, expected in ANSWERABLE:
        hits = search_help(question, 3)
        first = hits[0] if hits else None
        ok1 = bool(first) and _matches(first, expected)
        ok3 = any(_matches(h, expected) for h in hits)
        top1 += ok1
        top3 += ok3
        shown = f"{first['source']}:{first['title'][:38]} ({first['similarity']:.2f})" if first else "nothing"
        print(f"{'OK ' if ok1 else ('~3 ' if ok3 else 'MISS')} {question[:52]:52} -> {shown}")

    rejected = 0
    for question in UNANSWERABLE:
        hits = search_help(question, 3)
        rejected += not hits
        shown = f"{hits[0]['title'][:38]} ({hits[0]['similarity']:.2f})" if hits else "nothing (correct)"
        print(f"{'OK ' if not hits else 'LEAK'} {question[:52]:52} -> {shown}")

    n = len(ANSWERABLE)
    print(f"\nhit@1 {top1}/{n} ({top1 / n:.0%})   hit@3 {top3}/{n} ({top3 / n:.0%})   "
          f"off-topic rejected {rejected}/{len(UNANSWERABLE)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
