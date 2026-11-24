# PredictiX knowledge base

The knowledge the AI reports and the chatbot are grounded in: where it comes
from, how it is loaded, and who may see it.

- `sources.yaml`: the registry. The only list of what may be loaded.
- `REFERENCES.md`, `references.bib`: generated reference list. Do not edit.
- `LEGACY_AUDIT.md`: decisions on the pre-registry corpus (`kb_documents`).
- `.cache/`, `reports/`: local download cache and run reports (not in git).
- Code: `app/kb/pipeline/` (loading) and `app/kb/retrieval.py` (searching).
- Decision record: `docs/adr/0006-knowledge-base-sources.md`.

## The flow

```
 kb/sources.yaml (reviewed in git)
        |
        v
 1 VALIDATE   schema, licence evidence, audience, warehouse codes
        |
        v
 2 FETCH      https download -> status, size and file-signature checks
        |      -> SHA-256 checksum -> local cache
        v
 3 EXTRACT    PDF pages or eCFR XML -> text blocks with section + page
        |      (running headers, footers and print stamps removed)
        v
 4 CHUNK      sentences packed into passages <= 240 model tokens,
        |      one section per passage, short sentence overlap,
        |      "<source> - <section>" heading prepended for embedding
        v
 5 QUALITY    enough text? not a scanned PDF? no over-long passages?
   GATES      not mostly duplicates?   (fail = source skipped, nothing written)
        |
        v
 6 EMBED      all-MiniLM-L6-v2, normalised 384-dim vectors, validated
        |
        v
 7 ARCHIVE    raw original  -> kb-sources/raw/<id>/<sha256>.<ext>   (write-once)
        |      processed     -> kb-sources/processed/<id>/<fingerprint>.json
        v
 8 STORE      one transaction per source: upsert kb_sources row,
               replace its kb_chunks (batched insert), commit
```

Then, at question time:

```
 caller (role + active warehouse)  ->  KBScope   (no scope = no results)
 question -> embedding ----------------------+
 question -> full-text query ----------------+--> SQL: only active sources,
                                             |    caller's role in audience,
                                             |    network or caller's warehouse
                                             v
                         vector top 40  +  keyword top 40
                                 \           /
                         reciprocal rank fusion + similarity floor
                                       |
                    passages with citation [S07, § 1910.178(g) ..., p. n]
                    and applicability note -> report prompt -> AI trace
```

## The three kinds of source

| Id | Kind | Example | Scope |
|---|---|---|---|
| `S01`... | Published, openly licensed documents | 49 CFR 396, HSE L117, NIST handbook | Network-wide |
| `D01`... | Derived from PredictiX data, rebuilt nightly | D01 ticket issue patterns per warehouse | Each passage tagged with its warehouse |
| `W-GLE-01`... | Internal documents for one warehouse | Galle route profile, local SOPs | That warehouse |

D01 aggregates the tickets table (how often an issue occurs at a warehouse,
usual category and priority, median time to resolve, affected vehicles).
Personal data is removed before embedding (`app/kb/pipeline/privacy.py`) and
no single ticket is stored. Individual records stay with the chatbot's SQL
agent, which answers them exactly. The scheduler refreshes D01 nightly
(`KB_REFRESH_HOUR`, default 02:30 Colombo time); an unchanged snapshot is
skipped by its fingerprint.

## How the chatbot uses it

```
 question (KNOWLEDGE intent)
     |
     +-- strong app-FAQ match and not a legal question?  -> help answer (FAQs)
     |
     +-- otherwise: scoped hybrid search over kb_chunks
           |
           +-- legal question and no Sri Lankan (LK) source? -> "no official Sri Lankan
           |                                                    source" (guard, traced)
           +-- passages -> fenced, PROMPT_GUARD first -> model answers from them,
                           cites [S07]; Sources list added by code
           +-- nothing relevant -> help path's "not covered" reply
```

Run `python -m app.kb.pipeline gaps --days 30` to list questions the knowledge
base could not answer well (from the AI traces); that list decides what to add next.

## Why each step exists

| Step | Industry practice it follows | What goes wrong without it |
|---|---|---|
| Registry in git | Data catalogue, change control by review | Unknown documents with unknown licences end up in answers |
| Licence evidence | Licence compliance | Republishing material you may not reuse |
| Signature check | Input validation | An HTML "too many requests" page gets embedded as a manual |
| Checksums | Data integrity, provenance | No way to prove which version an answer came from |
| Raw / processed / serving layers | Medallion architecture (bronze, silver, gold) | Cannot rebuild or audit after a bug; originals lost if a site changes |
| Token-aware chunking | Respecting model limits | The model silently drops text past 256 tokens; that text can never be found |
| Section-bounded passages | Precise citations | Citations point at the wrong heading |
| Quality gates | Fail fast before side effects | A scanned PDF loads as empty or garbage |
| Fingerprint | Idempotent pipelines | Re-runs duplicate data or waste time re-embedding |
| One transaction per source | Atomicity | Readers see a half-loaded source |
| Batched inserts | Bulk loading | One network round trip per row; slow and fragile |
| Scope in SQL | Least privilege, defence in depth | A role or warehouse sees content it should not |
| Hybrid search | Standard RAG retrieval | Pure vectors miss exact terms ("1910.178"); pure keywords miss meaning |
| Golden-set evaluation | Measured quality, regression gate | Changes silently make retrieval worse |

## Commands

Run from the backend root with the virtual environment active:

```bash
python -m app.kb.pipeline validate              # check sources.yaml
python -m app.kb.pipeline ingest --dry-run      # fetch, extract, chunk, check; write nothing
python -m app.kb.pipeline ingest                # load every new or changed source
python -m app.kb.pipeline ingest --only S07     # one source
python -m app.kb.pipeline ingest --force        # reload even if unchanged
python -m app.kb.pipeline sync                  # apply withdrawals from sources.yaml
python -m app.kb.pipeline references            # rebuild REFERENCES.md and references.bib
python -m app.kb.pipeline status                # what is loaded
python -m app.kb.pipeline gaps --days 30        # coverage gaps from real questions

pytest app/tests/unit/test_kb_pipeline.py app/tests/unit/test_kb_retrieval_scope.py
pytest -m eval app/tests/eval/test_kb_registry_eval.py -s   # quality + scoping on the live data
```

Needs `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` and the
cached `all-MiniLM-L6-v2` model.

## Adding a source

1. Confirm it is relevant (a feature and a user group it serves), authoritative
   and licensed for reuse, with the licence stated in the document.
2. Add an entry to `sources.yaml`: next free id, full citation, `licence_evidence`
   quoting where the licence is stated, `applicability`, `scope`, `audience`.
   Use `pages`, `headings` and `include_sections` to load only the relevant part.
3. `validate`, then `ingest --dry-run --only <id>`; read the report and a few
   passages (section labels are what citations show).
4. Add one or two golden questions to `app/tests/data/kb_golden.json`.
5. Open a pull request. After merge: `ingest --only <id>`, run the eval,
   then `references`.

To withdraw a source, set `status: withdrawn`, then run `sync` and `references`.
Its record stays for audit; its passages stop being served at once.

## Warehouse-specific documents

Internal documents for one warehouse (route profiles, local SOPs, known
failure patterns) use ids like `W-GLE-01`, `scope: warehouse`,
`warehouses: [LL-GLE]` and `doc_type: internal_sop`. Retrieval already shows
such sources only to callers working in that warehouse (and to a super
admin's network view); the eval suite proves it with a temporary source.

To load one: upload the file (PDF or Markdown) to the private `kb-sources`
bucket under `incoming/<warehouse>/`, then register it with
`fetch: [{storage_path: incoming/galle/route-profile.md, format: markdown}]`.
Only `W-` sources may load uploads, and they must be warehouse-scoped; the
file is checked, checksummed and archived like any other original.
