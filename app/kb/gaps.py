"""Coverage-gap report: knowledge-base searches that found nothing useful.

Reads the retrieval steps recorded in ai_traces and lists questions whose
best passage scored below WEAK_SCORE (or that found none), most frequent
first. The output stays local (kb/reports, not in git) because it contains
the text users typed.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

WEAK_SCORE = 0.45

_STEPS = text("""
    SELECT t.created_at, t.channel, step
    FROM ai_traces t, jsonb_array_elements(t.steps) step
    WHERE t.created_at >= now() - make_interval(days => :days)
      AND step->>'kind' = 'retrieval'
      AND step->>'corpus' LIKE 'kb_chunks%'
""")


def _best_score(step: dict) -> float:
    scores = [h.get("score") for h in step.get("hits") or [] if isinstance(h.get("score"), (int, float))]
    return max(scores) if scores else 0.0


def gap_report(db: Session, days: int = 30) -> str:
    rows = db.execute(_STEPS, {"days": days}).all()
    gaps: dict[str, list[float]] = defaultdict(list)
    channels: Counter = Counter()
    local_law = 0
    for _, channel, step in rows:
        best = _best_score(step)
        if best < WEAK_SCORE:
            question = " ".join(str(step.get("query") or "").split())[:200]
            gaps[question.lower()].append(best)
            channels[channel] += 1
            local_law += bool(step.get("local_law_question"))

    lines = [
        f"# Knowledge-base coverage gaps (last {days} days)",
        "",
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}. "
        f"{len(rows)} knowledge-base searches; {sum(len(v) for v in gaps.values())} found no passage "
        f"scoring {WEAK_SCORE} or more. {local_law} of those asked about legal requirements.",
        "",
        "| Times asked | Best score | Question |",
        "|---|---|---|",
    ]
    for question, scores in sorted(gaps.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        lines.append(f"| {len(scores)} | {max(scores):.2f} | {question.replace('|', '/')} |")
    lines += ["", "Use this list to choose sources to add (see kb/README.md, 'Adding a source')."]
    return "\n".join(lines) + "\n"
