"""Chatbot answers grounded in the registered knowledge base.

Flow for a maintenance or standards question:

1. Build the caller's KBScope (role + active warehouse). No scope, no search.
2. Hybrid, scoped search over kb_chunks (app.kb.retrieval.search).
3. Jurisdiction guard: a question about Sri Lankan law is answered from
   Sri Lankan sources only. Without one, the bot says so plainly and may
   offer foreign rules only as labelled reference practice.
4. The model answers from the fenced passages alone (PROMPT_GUARD first),
   cites them as [S07] etc., or replies NOT_FOUND.
5. A "Sources" list with title, section, publisher and jurisdiction is
   appended by code, not by the model, so citations cannot be invented.

Every step is recorded in the AI trace.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from app.ai.agent.guardrails import fence_untrusted
from app.ai.agent.tracing import record
from app.kb.retrieval import KBHit, KBScope, search

log = logging.getLogger("predictix.agent.kb")

NOT_FOUND = "NOT_FOUND"
MAX_PASSAGES = 4
#: Per-source cap before back-filling, so one document cannot take every slot.
MAX_PER_SOURCE = 2
#: Passages scoring this far below the best one are not used or cited.
SCORE_MARGIN = 0.12

_LOCAL_LAW = re.compile(
    r"\b(sri\s*lanka\w*|lankan|local\s+(law|rule|regulation)s?|legal(ly)?|law|act|ordinance|gazette|"
    r"revenue\s+licen[cs]e|emission\s+test|fitness\s+certificate|motor\s+traffic|dmt|statutory|compulsory|mandatory)\b",
    re.IGNORECASE,
)
_JURISDICTION_NAME = {"US": "United States", "UK": "United Kingdom", "LK": "Sri Lanka", "INT": "international"}


def asks_about_local_law(question: str) -> bool:
    """True when the question is about legal requirements (and so needs a Sri Lankan source)."""
    return bool(_LOCAL_LAW.search(question))


def _not_covered(local_law: bool) -> dict:
    if local_law:
        text = (
            "⚖️ I don't have an official Sri Lankan source on that requirement, so I can't tell you what the law "
            "requires. Please check with the Department of Motor Traffic or the Department of Labour, or ask your "
            "warehouse administrator."
        )
    else:
        text = (
            "📚 I couldn't find that in the maintenance knowledge base. Your warehouse administrator or the "
            "vehicle maker's service manual is the best next step."
        )
    return {"answer": text, "action_buttons": []}


def _passage_label(hit: KBHit) -> str:
    return f"[{hit.source_id}] {hit.title}" + (f" - {hit.section}" if hit.section else "")


def sources_footer(hits: list[KBHit]) -> str:
    lines, seen = [], set()
    for h in hits:
        key = (h.source_id, h.section)
        if key in seen:
            continue
        seen.add(key)
        where = _JURISDICTION_NAME.get(h.jurisdiction, h.jurisdiction)
        lines.append(f"• [{h.source_id}] {h.title}" + (f", {h.section}" if h.section else "")
                     + f" ({h.publisher}, {where})")
    return "\n\n📎 *Sources:*\n" + "\n".join(lines)


def _select(hits: list[KBHit]) -> list[KBHit]:
    """The passages the model answers from: relevant, in rank order, and varied.

    At most MAX_PER_SOURCE passages per source on the first pass, so one long
    document split into many similar chunks cannot fill every slot and push
    out a different source that answers the question. Remaining slots are then
    back-filled in rank order, so a question only one source covers still gets
    MAX_PASSAGES passages.
    """
    if not hits:
        return []
    best = max(h.cosine for h in hits)
    relevant = [h for h in hits if h.cosine >= best - SCORE_MARGIN]

    chosen: list[KBHit] = []
    per_source: dict[str, int] = {}
    for h in relevant:
        if len(chosen) == MAX_PASSAGES:
            break
        if per_source.get(h.source_id, 0) < MAX_PER_SOURCE:
            chosen.append(h)
            per_source[h.source_id] = per_source.get(h.source_id, 0) + 1
    for h in relevant:
        if len(chosen) == MAX_PASSAGES:
            break
        if h not in chosen:
            chosen.append(h)
    rank = {id(h): i for i, h in enumerate(relevant)}
    return sorted(chosen, key=lambda h: rank[id(h)])


def answer_from_kb(question: str, user: Any, warehouse_id: Optional[str], db) -> Optional[dict]:
    """A cited answer, a 'not covered' answer, or None when nothing relevant was found."""
    from app.ai.agent.guardrails import guarded_call_groq as call_groq
    from app.chatbot.knowledge_service import embed_text

    scope = KBScope.for_viewer(user, warehouse_id)
    if scope is None:
        record("retrieval", corpus="kb_chunks", method="none", query=question, reason="no scope for caller")
        return None

    local_law = asks_about_local_law(question)
    hits = _select(search(db, question, embed_text(question), scope, top_k=8))
    local = [h for h in hits if h.jurisdiction == "LK"]
    record(
        "retrieval", corpus="kb_chunks", method="hybrid", query=question,
        scope={"role": scope.role, "warehouse_id": scope.warehouse_id, "network_view": scope.network_view},
        local_law_question=local_law,
        hits=[{"id": h.chunk_id, "source": h.source_id, "citation": h.citation(),
               "jurisdiction": h.jurisdiction, "score": round(h.cosine, 4)} for h in hits],
    )
    if not hits:
        return _not_covered(local_law) if local_law else None
    if local_law and not local:
        # Never let a foreign rule stand in for Sri Lankan law.
        record("guard", rule="jurisdiction", outcome="no Sri Lankan source; refused to state the law")
        return _not_covered(True)

    used = local if local_law else hits
    context = fence_untrusted(
        "kb_passages",
        "\n\n".join(
            f"{_passage_label(h)} ({h.publisher}, {_JURISDICTION_NAME.get(h.jurisdiction, h.jurisdiction)})\n"
            f"Applies: {h.applicability}\n{h.content}"
            for h in used
        ),
        limit=9000,
    )
    system = (
        "You are PredictiX Assistant for a vehicle fleet with road vehicles and forklifts across several "
        "Sri Lankan warehouses. Answer the question using ONLY the passages provided. "
        "Cite each fact with its source id in square brackets, e.g. [S07]. "
        "Follow each passage's 'Applies' note: a United States or United Kingdom rule is reference practice, "
        "never Sri Lankan law, and must be described that way. "
        "Prefer the vehicle maker's instructions when the passages say so. "
        f"If the passages do not answer the question, reply with exactly {NOT_FOUND}. "
        "Be concise and practical: short steps or bullet points. Do not mention 'passages' or 'context'."
    )
    try:
        reply, fallback = call_groq(
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": f"Question: {question}\n\n{context}"}],
            max_tokens=500, temperature=0.1,
        )
    except Exception as exc:
        log.error("Knowledge answer synthesis failed: %s", exc)
        top = used[0]
        return {
            "answer": f"📘 **{_passage_label(top)}**\n\n{top.content}{sources_footer([top])}",
            "action_buttons": [],
        }

    text_out = str(reply or "").strip()
    if not text_out or NOT_FOUND in text_out:
        return _not_covered(local_law)
    cited = {m for m in re.findall(r"\[([SDW][\w-]*)\]", text_out)}
    shown = [h for h in used if h.source_id in cited]
    if not shown:
        # An answer that cites none of the passages was not built from them.
        record("guard", rule="uncited_answer", outcome="treated as not covered")
        return _not_covered(local_law)
    return {"answer": (fallback or "") + text_out + sources_footer(shown), "action_buttons": []}
