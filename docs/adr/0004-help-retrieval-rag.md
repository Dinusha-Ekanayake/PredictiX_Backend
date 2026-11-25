# ADR-0004: Help retrieval (RAG) design

- Status: Accepted
- Date: 2026-11-23

## Context

The FAQ Synthesizer answers "how do I" questions from the FAQ table and the
`knowledge_base` articles. Before this change the hosted Hugging Face
embedding endpoint returned HTTP 402, so retrieval silently failed; inactive
articles could be returned; and FAQs and articles were searched separately
with no shared relevance bar.

## Decision

- **Embeddings**: `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions),
  loaded locally. The hosted endpoint is a second option and TF-IDF is the
  last fallback, so help still works without network access.
- **One ranked list**: `search_help` (`app/chatbot/knowledge_service.py`)
  merges FAQs and active articles. FAQs are embedded twice (full text, and a
  short "question; tags" form) and score as the better of the two.
- **Relevance bar**: cosine similarity at least `0.30` (semantic) or
  `0.10` (lexical fallback). Below the bar the bot says the topic is not
  covered instead of guessing.
- **Query cleaning**: the product name is stripped for ranking
  (`_ranking_query`) because it appears in nearly every document, unless that
  would leave only filler words.
- **Grounded answers**: only hits within `0.12` of the best score are sent to
  the model, inside `<help_content>` fences, after the `PROMPT_GUARD` system
  message. The model must answer from them or reply `NOT_FOUND`. Answers list
  their sources. If the model is down, the top item is returned verbatim.

## Evaluation

`scripts/eval_rag.py` and `app/tests/eval/test_rag_retrieval_eval.py` run the
golden set in `app/tests/data/rag_golden.json`:

| Split | Result |
|-------|--------|
| Tuning (20) | 20/20 hit@1 |
| Held-out (23) | 22/23 hit@1, 23/23 hit@3 |
| Off-topic (10) | 10/10 correctly refused |

Thresholds were tuned on the tuning split only; the held-out split checks
they generalise.

## Consequences

- New FAQ or article content should come with a golden question so
  regressions show up in the eval.
- Changing the model or thresholds requires re-running the eval and updating
  the table above.
