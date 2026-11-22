"""Print a retrieval report for chatbot help search on the golden dataset.

Read-only. Uses app/tests/data/rag_golden.json, the same data the pytest gate
in app/tests/eval/test_rag_retrieval_eval.py checks, and reports hit@1 and
hit@3 per split plus the off-topic rejection rate. Run it after changing the
embedding model, the threshold, or the FAQs and articles:

    python scripts/eval_rag.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.chatbot.knowledge_service import search_help  # noqa: E402

DATA = json.loads((ROOT / "app" / "tests" / "data" / "rag_golden.json").read_text(encoding="utf-8"))


def _matches(hit: dict, expected: list[str]) -> bool:
    title = str(hit.get("title", "")).lower()
    return any(e.lower() in title for e in expected)


def main() -> int:
    totals: dict[str, list[int]] = {}
    for item in DATA["answerable"]:
        hits = search_help(item["q"], 3)
        ok1 = bool(hits) and _matches(hits[0], item["expected"])
        ok3 = any(_matches(h, item["expected"]) for h in hits)
        split = totals.setdefault(item["split"], [0, 0, 0])
        split[0] += ok1
        split[1] += ok3
        split[2] += 1
        shown = f"{hits[0]['source']}:{hits[0]['title'][:38]} ({hits[0]['similarity']:.2f})" if hits else "nothing"
        print(f"{'OK ' if ok1 else ('~3 ' if ok3 else 'MISS')} [{item['split']:7}] {item['q'][:50]:50} -> {shown}")

    rejected = 0
    for question in DATA["off_topic"]:
        hits = search_help(question, 3)
        rejected += not hits
        shown = f"{hits[0]['title'][:38]} ({hits[0]['similarity']:.2f})" if hits else "nothing (correct)"
        print(f"{'OK ' if not hits else 'LEAK'} [offtopic] {question[:50]:50} -> {shown}")

    print()
    for name, (h1, h3, n) in totals.items():
        print(f"{name:8} hit@1 {h1}/{n} ({h1 / n:.0%})   hit@3 {h3}/{n} ({h3 / n:.0%})")
    print(f"off-topic rejected {rejected}/{len(DATA['off_topic'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
