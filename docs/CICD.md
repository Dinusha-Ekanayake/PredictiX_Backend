# CI/CD

Two repositories, two pipelines.

| repo | CI | Deploy |
| --- | --- | --- |
| `PredictiX_Backend` | `.github/workflows/ci.yml` | `.github/workflows/deploy.yml` to EC2 |
| `PredictiX-Frontend` | `.github/workflows/ci.yml` | Vercel (already connected) |

## Why the backend deploy workflow exists

The EC2 instance runs a nightly batch that writes predictions into the
production database. When the instance drifts behind `main`, that batch keeps
running with old code and overwrites corrected data. This has already happened:
a run wrote health bands on a superseded scale and produced cost intervals that
excluded their own estimate, hours after both were fixed in `main`.

Deploying automatically on every green build on `main` is what stops that.

## Flow

```
feature branch ──PR──> dev ──PR──> main
      │                 │            │
      └── CI            └── CI       ├── CI
                                     └── CI green ──> deploy to EC2
                                                        └── health check
                                                             └── rollback on failure
```

Deployment is triggered by CI *completing successfully*, not by the push. A red
build cannot reach production.

## Backend CI jobs

| job | needs a database | runs on |
| --- | --- | --- |
| `static-checks` | no | every PR and push |
| `unit-tests` | no | every PR and push |
| `integration-tests` | yes | non-fork PRs and pushes |
| `functional-tests` | yes | non-fork PRs and pushes |
| `ci-passed` | no | aggregates the above |

`functional-tests` runs the module-by-module test plan: one case per row of the
report's tables in §7.3, keyed by the same ids (AU-01, PM-05, and so on). It
prints the ID / case / expected / status table, writes the markdown version to
the job summary, and uploads `functional_results.json` as an artifact.

Run it locally with:

```bash
python scripts/run_functional_tests.py             # every module
python scripts/run_functional_tests.py --module PM # one module
python scripts/run_functional_tests.py --detail    # with failure reasons
python scripts/run_functional_tests.py --md        # markdown for the report
```

Three outcomes are possible and they are not interchangeable. `PASS` means the
expectation held against the live system. `FAIL` means it did not, and is
reported as a defect rather than smoothed over. `FRONTEND` means the behaviour
has no server-side surface to assert, so the backend suite does not judge it and
the frontend suite covers it instead — AU-08, NS-07 and NS-08 are the three.

A case is never marked `PASS` because it was awkward to test.

### Cases that depend on an external model

Three external dependencies decide whether a case can be judged at all, and the
suite refuses to guess when one is missing.

| dependency | cases | absent → |
| --- | --- | --- |
| `GROQ_API_KEY` | CB-01 to CB-07, CB-09 to CB-11, RG-02, RG-07 | skipped |
| Hugging Face inference | AS-09, TK-05 | skipped |
| neither | everything else | runs |

Both guards exist for the same reason. Without a Groq key the agent still
answers, from its non-LLM fallback path. Without Hugging Face the summary
services still return text, from a deterministic template. A test that only
checks "something came back" passes in both cases and reports a working model
that was never called. Skipping says so plainly.

`app/main.py` defaults `HF_HUB_OFFLINE` to `1`, and `.env` additionally sets
`DISABLE_HF_MODELS` and `TRANSFORMERS_OFFLINE`, so **local runs skip AS-09 and
TK-05 by default**. The CI job forces all three off so the summary Spaces are
genuinely exercised there — AS-09 was written to detect those Spaces being
unreachable, and skipping it in CI would defeat the point.

### Telling a model summary from a template

`AssetSummaryResponse` now carries `source`, either `"model"` or `"template"`.
It previously stamped `model_version: "1.0"` on both, so a caller could not tell
whether a model wrote the sentence or the fallback did. AS-09 asserts
`source == "model"`; without that field the case could only check that a
non-empty string came back, which the template always satisfies.

`static-checks` compiles every module, fails if `.env` or any `.pem`/`.key` is
tracked by git, and fails on credential-shaped literals in source. Placeholders
such as `gsk_xxxxxxxx` in help text are ignored so the check stays trustworthy.

Integration tests skip themselves when `DATABASE_URL` is absent, so a fork PR
reports skipped rather than failing for a reason the contributor cannot fix.

Set `ci-passed` as the required status check in branch protection. It is one
check that covers all the others, so adding a job later needs no protection
rule change.

## Deployment behaviour

The deploy job records the current commit before touching anything, then
fetches, hard-resets to the target branch, installs into the same virtualenv
systemd runs from, and byte-compiles before restarting. After the restart it
polls `http://127.0.0.1:8000/` up to six times.

If the service does not come back healthy it resets to the previous commit,
reinstalls, restarts, and fails the run. Rolling back matters here specifically
because of the nightly batch: leaving broken code installed would corrupt data
overnight rather than merely serving errors.

A second step then checks the public URL, which proves nginx is routing to the
restarted process and not just that the process is alive locally.

## Required GitHub configuration

### Backend repository

Settings → Secrets and variables → Actions.

**Secrets — deployment**

| name | value |
| --- | --- |
| `EC2_HOST` | instance public DNS or IP |
| `EC2_USER` | `ubuntu` |
| `EC2_SSH_KEY` | full contents of the `.pem` private key |
| `EC2_APP_DIR` | `/home/ubuntu/PredictiX_Backend` |
| `EC2_SERVICE_NAME` | `predictix` |
| `EC2_PORT` | optional, defaults to 22 |

**Secrets — integration tests**

`DATABASE_URL`, `JWT_SECRET`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`,
`GROQ_API_KEY`, `HF_TOKEN`, `HF_AI_SPACE_URL`.

**Variables**

| name | value |
| --- | --- |
| `BACKEND_PUBLIC_URL` | public base URL, used for the post-deploy check |

**Environments**

Create `ci` and `production`. Put the deployment secrets in `production` and
add yourself as a required reviewer if you want deploys to pause for approval.

### Frontend repository

**Variables:** `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SUPABASE_URL`
**Secrets:** `NEXT_PUBLIC_SUPABASE_ANON_KEY`

These are read at build time, so a missing one fails CI rather than producing a
blank page on a preview deployment.

## Database connection mode

`DATABASE_URL` must point at Supabase's **transaction-mode** pooler, port
**6543**, everywhere the application runs: locally, on EC2, and in the
`DATABASE_URL` secret used by CI.

Session mode (5432) holds one server connection per client for the entire
session and this tier caps that at 15 clients across every process touching the
database. A dev server, the deployed instance and a CI run together exceed it,
and every request then fails with:

```
FATAL: (EMAXCONNSESSION) max clients reached in session mode
```

Transaction mode returns the connection to the pooler after each transaction,
so the client cap stops being the binding constraint. Verified at 20 concurrent
queries, well past the old ceiling.

The trade is roughly 200 ms per warm request, and a one-off multi-second
handshake on each pool slot rather than on each request. `DB_POOL_SIZE` and
`DB_MAX_OVERFLOW` override the per-process ceiling if a deployment owns the
tier outright.

## EC2 prerequisites

The deploy user must restart the service without a password prompt:

```bash
echo "ubuntu ALL=(ALL) NOPASSWD: /bin/systemctl restart predictix, /bin/systemctl status predictix" \
  | sudo tee /etc/sudoers.d/predictix-deploy
sudo chmod 440 /etc/sudoers.d/predictix-deploy
```

The checkout must be able to fetch without an interactive prompt (a deploy key
or a credential helper), and `git reset --hard` must be safe to run, so no
uncommitted local edits should live on the instance.

## Running the same checks locally

```bash
# backend
python scripts/run_tests.py                 # unit, router and integration
python scripts/run_tests.py --unit          # what a fork PR runs
python scripts/run_functional_tests.py      # the §7.3 test plan
python -m compileall -q app scripts -x "(Seq2Seq|__pycache__)"

# frontend
npm test
npx tsc --noEmit
npm run build
```

## What the functional suite writes to the database

Cases that need a row create one, assert against it, and delete it in a
`finally` block. Everything created carries the `ZZFUNCTEST` prefix in its code
or email, so anything left behind by an interrupted run is identifiable and
cannot be mistaken for fleet data:

```sql
SELECT asset_code FROM assets   WHERE asset_code LIKE 'ZZFUNCTEST%';
SELECT email      FROM profiles WHERE email      LIKE 'zzfunctest%';
```

Creating a user also creates a Supabase auth user; `DELETE /users/{id}` removes
both, which is why the cleanup goes through the API rather than the database.

## Known gaps

`npm run lint` is blocking, and the project sits at zero eslint errors, so any
new error is a regression from the change under review. 77 unused-variable
warnings remain and do not fail the build.

`npm audit` is reported but non-blocking, because a transitive advisory with no
available fix should not stop a bugfix from shipping.

There is no staging environment. `dev` is tested but never deployed, so `main`
is the first place code runs against production infrastructure.
