# Testing the PredictiX API

The suite is layered so each kind of test runs only where its dependencies
exist. Markers in `pytest.ini` select the layers.

| Layer | Where | Marker | Needs | What it proves |
|---|---|---|---|---|
| Unit | `app/tests/unit`, `app/tests/qa_automated` | (none) | nothing | Logic in isolation: auth helpers, permission rules, SQL validator, guardrails, RAG ranking with fake vectors, tracing, health bands, decision layer |
| Red-team | `app/tests/unit/test_adversarial_suite.py` + `app/tests/data/adversarial.json` | (none) | nothing | Every known SQL-sandbox bypass, data-fence breakout and unsafe link is refused; realistic queries are still accepted |
| Integration | `app/tests/integration` | `integration` | `DATABASE_URL`, `JWT_SECRET` | Against the real database: the authorization matrix, the SQL sandbox, the chatbot agent graph with a scripted model, and audit traces |
| RAG evaluation | `app/tests/eval/test_rag_retrieval_eval.py` + `app/tests/data/rag_golden.json` | `eval` | database + embedding model | Retrieval quality gates on a golden set |
| Live LLM evaluation | `app/tests/eval/test_llm_answers.py` | `llm` | a valid Groq key, `RUN_LLM_TESTS=1` | Answers are grounded and cited; hard negatives get "not covered" |
| Functional test plan | `app/tests/functional` | `functional` | live API, seeded demo accounts, `TEST_*_PASSWORD` | One case per requirement in the test plan |

## Running

```bash
pip install -r requirements.txt -r requirements-dev.txt

python scripts/run_tests.py --unit                 # unit + router, no database
pytest app/tests/integration -m integration         # needs DATABASE_URL + JWT_SECRET
HF_HUB_OFFLINE=0 pytest app/tests/eval -m "eval and not llm" -s   # RAG gates, prints a report
RUN_LLM_TESTS=1 pytest app/tests/eval -m llm -s     # live model, spends quota
python scripts/run_functional_tests.py             # test plan as a pass/fail table
pytest --cov --cov-report=term                      # coverage of shipped code (.coveragerc)
python scripts/eval_rag.py                          # quick retrieval report without pytest
```

## How the integration tests stay safe on a shared database

- Tokens are minted for real profiles with the API's own signing key, so no
  passwords are needed and nothing logs in.
- Requests are reads, or ones the API must refuse before writing (the
  assertion is that refusal).
- The chatbot SQL sandbox runs inside transactions that are always rolled
  back.
- The one suite that writes (audit traces) deletes its own rows.

## Chatbot and RAG testing approach

- **Agent graph.** `test_chatbot_pipeline.py` runs the real router, handlers,
  retrieval, SQL sandbox, self-healer, record widget and response compiler
  with a scripted model, so every path in the architecture diagram is
  exercised deterministically. Each scripted call asserts that the shared
  security rules were sent first.
- **Retrieval quality.** `rag_golden.json` holds questions with known answers,
  split into `tuning` (used to choose the threshold) and `heldout` (written
  afterwards, never tuned on), plus `off_topic` questions that must retrieve
  nothing and `hard_negative` questions that mention PredictiX subjects the help
  content does not answer. Gates: hit@1 and hit@3 per split, off-topic
  rejection. The gates sit a little below measured scores so corpus noise does
  not fail the build but a real regression does.
- **Answer quality.** With a live model, held-out questions must produce
  answers that cite the expected source, and hard negatives must be reported
  as not covered.
- **Adversarial.** Payloads live in `adversarial.json`, so a new bypass found in
  review becomes a permanent regression test by adding one line.

## Adding tests

- A bug fix gets a test that fails without the fix.
- A new endpoint gets rows in `test_authorization_matrix.py` for each role and
  for own and other warehouse.
- A change to retrieval, the threshold, FAQs or articles: run
  `scripts/eval_rag.py` and the `eval` gate; add new question types to
  `rag_golden.json` under `heldout`.
- A new SQL or prompt bypass: add it to `adversarial.json`.
