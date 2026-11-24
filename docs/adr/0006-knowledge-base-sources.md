# ADR-0006: Knowledge-base source registry and ingestion pipeline

- Status: Accepted
- Date: 2026-11-23

## Context

The report agent grounds warehouse reports in a knowledge base (SRS REQ-40).
The existing corpus (`kb_documents`, 1,317 passages from 10 PDFs) recorded
only file names: no publisher, licence, URL, page or version. Half of it came
from one general environmental-standards booklet, it had no vector index, and
none of it was scoped by warehouse or role. The final report's future work
asks for equipment manuals, maintenance procedures, SOPs and inspection
guidelines in semantic retrieval.

PredictiX serves several vehicle warehouses (Colombo, Galle, Badulla) whose
assets are road vehicles and forklifts, for three roles: users (drivers,
technicians, department staff), warehouse admins and super admins.

## Decision

**Registry as the source of truth.** `kb/sources.yaml` lists every source with
its citation, licence, the evidence of that licence, jurisdiction, an
applicability note, warehouse scope, audience, the features it supports and a
review date. It is validated strictly (`app/kb/pipeline/registry.py`) and
changed only by reviewed pull requests. Rejected candidates stay in the file
with the reason.

**Admission policy.** A source must (1) support a PredictiX feature for a real
user group and cover the fleet, (2) come from a government body, standards
body or peer-reviewed journal, (3) carry a reuse licence stated in the
document itself, and (4) say how a foreign rule applies, so answers never
present it as Sri Lankan law. Sites that refuse automated clients are not
worked around.

**Three data layers.**

| Layer | Content | Where |
|---|---|---|
| Raw | Original file, byte for byte | Private bucket `kb-sources/raw/<id>/<sha256>.<ext>`, write-once |
| Processed | Extracted blocks and passages, with provenance | `kb-sources/processed/<id>/<fingerprint>.json` |
| Serving | Passages, embeddings, full-text vectors | Postgres `kb_sources`, `kb_chunks` (migration 014) |

**Pipeline** (`python -m app.kb.pipeline`): fetch (signature and size checks,
retries, cache) → extract (PDF or eCFR XML, page and section kept, headers and
footers removed) → chunk (model tokenizer, at most 240 of the 256 tokens the
model reads, sentence boundaries, overlap, one section per passage) → quality
gates → embed (all-MiniLM-L6-v2, the query model) → archive → one transaction
per source. A fingerprint of the file, registry entry, pipeline version and
model makes re-runs idempotent.

**Retrieval** (`app/kb/retrieval.py`): hybrid search (HNSW cosine + Postgres
full text, merged by reciprocal rank fusion) with the scope applied in SQL
before ranking: active sources only, the caller's role must be in the
audience, and a warehouse-scoped source is visible only to its warehouses (a
super admin's network view sees all). No scope returns nothing.

**Vector store.** pgvector in the existing Supabase Postgres, with an HNSW
index. At this size (about 1,000 to 10,000 passages) a separate vector
database would add a service, a second copy of the data and cost without a
retrieval gain; it remains an option past millions of vectors.

## Consequences

- Every passage can be traced to a page of an archived original by checksum,
  and the reference list (`kb/REFERENCES.md`, `kb/references.bib`) is
  generated, never hand-edited.
- Adding a source is a reviewed YAML change plus one command; withdrawing one
  is a status change followed by `sync`, which removes it from retrieval
  immediately.
- No openly licensed, authoritative source was found for warehouse-specific
  conditions (coastal corrosion at Galle, long descents at Badulla).
  Warehouse-scoped internal documents (ids `W-<code>-NN`) are the intended
  route, using the same registry and scoping.
- Operational knowledge enters as derived sources (`D01` ticket patterns):
  aggregates only, personal data removed, each passage scoped to its warehouse
  (migration 015 adds `kb_chunks.warehouse_id`), refreshed nightly.
- The chatbot's KNOWLEDGE intent answers from this knowledge base with code-built
  citations. A question about legal requirements is answered only from Sri
  Lankan (`LK`) sources; without one the bot says so, and the guard is traced.
- The legacy `kb_documents` PDFs were audited (`kb/LEGACY_AUDIT.md`) and are no
  longer served (`KB_LEGACY_PDFS_ENABLED` re-enables them); the team's own
  articles in that table remain.
- Coverage is monitored from real questions (`python -m app.kb.pipeline gaps`).
- `app/tests/eval/test_kb_registry_eval.py` gates retrieval quality and
  checks that no source reaches a role or warehouse outside its scope.
