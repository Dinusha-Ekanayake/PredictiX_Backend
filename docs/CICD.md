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
| `unit-tests` (61 tests) | no | every PR and push |
| `integration-tests` (30 tests) | yes | non-fork PRs and pushes |
| `ci-passed` | no | aggregates the above |

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
python scripts/run_tests.py            # everything
python scripts/run_tests.py --unit     # what a fork PR runs
python -m compileall -q app scripts -x "(Seq2Seq|__pycache__)"

# frontend
npm test
npx tsc --noEmit
npm run build
```

## Known gaps

`npm run lint` is blocking, and the project sits at zero eslint errors, so any
new error is a regression from the change under review. 77 unused-variable
warnings remain and do not fail the build.

`npm audit` is reported but non-blocking, because a transitive advisory with no
available fix should not stop a bugfix from shipping.

There is no staging environment. `dev` is tested but never deployed, so `main`
is the first place code runs against production infrastructure.
