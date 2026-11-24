"""Scoped hybrid retrieval over the registered knowledge base (kb_chunks).

Every search needs a KBScope built from the caller. The scope is applied
inside the SQL, before ranking, so a passage the caller may not see is never
fetched, scored or traced:

    status     only sources marked active in the registry
    audience   only sources whose audience includes the caller's role
    warehouse  network-wide sources, plus sources scoped to the caller's
               active warehouse (a super admin's network view sees all);
               a passage tagged with one warehouse (derived operational
               data) is shown only to that warehouse

Ranking is hybrid. Two candidate lists are drawn, one by vector similarity
(meaning) and one by Postgres full-text search (exact terms such as
"1910.178" or "wear metal"), and merged with reciprocal rank fusion (RRF):
score = sum over lists of 1 / (60 + rank). A passage must also clear a
cosine-similarity floor, so a lone keyword match on an unrelated passage is
not returned.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.chatbot.knowledge_service import embedding_literal

#: Roles that may read the registered knowledge base, matching profiles.role.
KNOWN_ROLES = ("user", "admin", "super_admin")

RRF_K = 60
CANDIDATE_POOL = 40
#: Minimum cosine similarity for a passage found by vector search.
MIN_SEMANTIC = 0.30
#: Lower floor for a passage that also matched the query's exact terms.
MIN_WITH_KEYWORDS = 0.20


@dataclass(frozen=True)
class KBScope:
    """Who is asking and for which warehouse. Build it with `for_viewer`."""

    role: str
    warehouse_id: Optional[str]
    network_view: bool = False

    @classmethod
    def for_viewer(cls, viewer: Any, warehouse_id: Optional[str]) -> Optional["KBScope"]:
        """Scope for a signed-in profile, or None (no access) for anything else.

        `warehouse_id` is the caller's active warehouse as the API already
        resolved it. A super admin without one has the network view; anyone
        else without one sees network-wide sources only.
        """
        role = str(getattr(viewer, "role", "") or "").lower()
        if role not in KNOWN_ROLES:
            return None
        wh = str(warehouse_id) if warehouse_id else None
        return cls(role=role, warehouse_id=wh, network_view=(role == "super_admin" and wh is None))


@dataclass(frozen=True)
class KBHit:
    chunk_id: str
    source_id: str
    title: str
    section: Optional[str]
    page_start: Optional[int]
    page_end: Optional[int]
    content: str
    url: str
    publisher: str
    jurisdiction: str
    doc_type: str
    applicability: str
    licence: str
    cosine: float
    rrf: float
    matched_keywords: bool

    def citation(self) -> str:
        """Short citation for prompts and answers, e.g. 'S07, § 1910.178(g) ..., p. 3'."""
        parts = [self.source_id]
        if self.section:
            parts.append(self.section)
        if self.page_start:
            pages = f"p. {self.page_start}" if self.page_start == self.page_end or not self.page_end \
                else f"pp. {self.page_start}-{self.page_end}"
            parts.append(pages)
        return ", ".join(parts)


# A passage about one warehouse (derived operational data) is visible only to
# that warehouse and to a super admin's network view.
_PASSAGE_SCOPE = (
    "(c.warehouse_id IS NULL OR CAST(:network_view AS boolean) "
    "OR c.warehouse_id = CAST(:warehouse_id AS uuid))"
)

_SEARCH = text("""
WITH allowed AS (
    SELECT id FROM kb_sources
    WHERE status = 'active'
      AND CAST(:role AS text) = ANY (audience)
      AND (scope = 'network'
           OR CAST(:network_view AS boolean)
           OR CAST(:warehouse_id AS uuid) = ANY (warehouse_ids))
),
vec AS (
    SELECT id, row_number() OVER (ORDER BY dist) AS rnk
    FROM (
        SELECT c.id, c.embedding <=> CAST(:vector AS vector) AS dist
        FROM kb_chunks c
        WHERE c.source_id IN (SELECT id FROM allowed) AND {passage_scope}
        ORDER BY c.embedding <=> CAST(:vector AS vector)
        LIMIT :pool
    ) nearest
),
kw AS (
    SELECT id, row_number() OVER (ORDER BY rank DESC) AS rnk
    FROM (
        -- Any of the question's terms may match (OR); ts_rank_cd then ranks
        -- passages that contain more of them, closer together, higher. An
        -- AND query would almost never match a natural-language question.
        SELECT c.id, ts_rank_cd(c.content_tsv, q) AS rank
        FROM kb_chunks c,
             to_tsquery('english', replace(plainto_tsquery('english', :query)::text, ' & ', ' | ')) q
        WHERE c.content_tsv @@ q AND c.source_id IN (SELECT id FROM allowed) AND {passage_scope}
        ORDER BY rank DESC
        LIMIT :pool
    ) matched
)
SELECT c.id AS chunk_id, c.source_id, s.title, c.section, c.page_start, c.page_end, c.content,
       s.url, s.publisher, s.jurisdiction, s.doc_type, s.applicability, s.licence,
       1 - (c.embedding <=> CAST(:vector AS vector)) AS cosine,
       COALESCE(1.0 / (:rrf_k + vec.rnk), 0) + COALESCE(1.0 / (:rrf_k + kw.rnk), 0) AS rrf,
       kw.id IS NOT NULL AS matched_keywords
FROM kb_chunks c
JOIN kb_sources s ON s.id = c.source_id
LEFT JOIN vec ON vec.id = c.id
LEFT JOIN kw ON kw.id = c.id
WHERE vec.id IS NOT NULL OR kw.id IS NOT NULL
ORDER BY rrf DESC
LIMIT :pool
""".replace("{passage_scope}", _PASSAGE_SCOPE))


def scope_params(scope: KBScope) -> dict[str, Any]:
    return {"role": scope.role, "network_view": scope.network_view, "warehouse_id": scope.warehouse_id}


def search(
    db: Session,
    query: str,
    query_vector: list[float],
    scope: Optional[KBScope],
    *,
    top_k: int = 6,
) -> list[KBHit]:
    """Top passages the caller may see, best first. No scope means no results."""
    if scope is None or not query.strip():
        return []
    # pgvector 0.8: keep scanning the HNSW graph until enough rows pass the
    # source filter, instead of returning fewer than asked for.
    db.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
    db.execute(text("SET LOCAL hnsw.ef_search = 100"))
    rows = db.execute(_SEARCH, {
        **scope_params(scope), "vector": embedding_literal(query_vector), "query": query[:500],
        "pool": CANDIDATE_POOL, "rrf_k": RRF_K,
    }).mappings().all()
    hits = [KBHit(**{**dict(r), "cosine": float(r["cosine"]), "rrf": float(r["rrf"])}) for r in rows]
    kept = [h for h in hits if h.cosine >= (MIN_WITH_KEYWORDS if h.matched_keywords else MIN_SEMANTIC)]
    return kept[:top_k]
