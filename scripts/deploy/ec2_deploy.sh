#!/usr/bin/env bash
# Deploy one commit of PredictiX_Backend on the EC2 host, with automatic rollback.
#
#   scripts/deploy/ec2_deploy.sh <app_dir> <service> <branch> [commit]
#
# The deploy workflow (.github/workflows/deploy.yml) runs this over SSH, using
# the copy of this file from the commit being deployed. It can also be run by
# hand on the instance with the same arguments.
#
# What it guarantees:
#   * Idempotent: deploying the commit that is already running and healthy
#     changes nothing.
#   * Exact: the commit CI tested is the commit installed, not whatever the
#     branch points at by the time the job runs.
#   * Safe: if the new code does not come up healthy (process answering AND
#     the prediction models loaded), the previous commit is reinstalled and
#     restarted, and the script exits non-zero. This host runs the nightly
#     prediction batch, so leaving broken code in place would write bad data.
#
# Environment overrides (all optional):
#   REQUIREMENTS     requirements file to install (default requirements-prod.txt)
#   HEALTH_URL       local health endpoint (default http://127.0.0.1:8000/)
#   MIN_FREE_MB      free disk space required before installing (default 1500)
#   HEALTH_ATTEMPTS  health checks before giving up (default 12)
#   HEALTH_INTERVAL  seconds between health checks (default 5)
#   FORCE=1          reinstall and restart even if the commit is already live
#   SKIP_ENV_CHECK=1 do not check .env for the required settings
set -Eeuo pipefail

APP_DIR="${1:?usage: ec2_deploy.sh <app_dir> <service> <branch> [commit]}"
SERVICE="${2:?service name is required}"
BRANCH="${3:?branch is required}"
COMMIT="${4:-}"

REQUIREMENTS="${REQUIREMENTS:-requirements-prod.txt}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/}"
MIN_FREE_MB="${MIN_FREE_MB:-1500}"
HEALTH_ATTEMPTS="${HEALTH_ATTEMPTS:-12}"
HEALTH_INTERVAL="${HEALTH_INTERVAL:-5}"
REQUIRED_SETTINGS=(DATABASE_URL JWT_SECRET SUPABASE_URL SUPABASE_KEY)

log()  { printf '[deploy] %s\n' "$*"; }
fail() { printf '::error::%s\n' "$*" >&2; exit 1; }

# ── Preconditions: checked before anything on the host changes ───────────────
[[ "$BRANCH" =~ ^[A-Za-z0-9._/-]+$ ]] || fail "refusing unsafe branch name: $BRANCH"
[[ -z "$COMMIT" || "$COMMIT" =~ ^[0-9a-f]{7,40}$ ]] || fail "refusing unsafe commit: $COMMIT"

cd "$APP_DIR" || fail "app directory not found: $APP_DIR"
PY="$APP_DIR/venv/bin/python"
[[ -x "$PY" ]] || fail "virtualenv missing: create it with 'python3 -m venv venv' (docs/EC2_Deployment.md)"

if [[ "${SKIP_ENV_CHECK:-0}" != "1" ]]; then
  [[ -f .env ]] || fail ".env not found in $APP_DIR; systemd reads settings from it"
  for name in "${REQUIRED_SETTINGS[@]}"; do
    grep -Eq "^${name}=.+" .env || fail "$name is missing from .env; the API cannot start without it"
  done
fi

free_mb="$(df --output=avail -m "$APP_DIR" | tail -1 | tr -d ' ')"
(( free_mb >= MIN_FREE_MB )) || fail "only ${free_mb} MB free on disk, need ${MIN_FREE_MB} MB to install safely"

# ── Helpers ──────────────────────────────────────────────────────────────────
healthy() {
  # Up AND the prediction models loaded. A process that starts without its
  # models answers requests but every prediction fails, so it is not healthy.
  local body
  body="$(curl -fsS --max-time 10 "$HEALTH_URL" 2>/dev/null)" || return 1
  printf '%s' "$body" | "$PY" -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("models_loaded") is True else 1)'
}

wait_healthy() {
  local attempt
  for attempt in $(seq 1 "$HEALTH_ATTEMPTS"); do
    if healthy; then
      log "health check passed (attempt $attempt)"
      return 0
    fi
    sleep "$HEALTH_INTERVAL"
  done
  return 1
}

# Every step ends in `|| return 1`: bash ignores `set -e` inside a function
# that is called as an `if` condition, which is how this one is called.
install_commit() {
  local sha="$1"
  log "checking out $sha"
  # -f discards local edits to tracked files and -B moves the branch, so a
  # half-finished earlier deploy can never block this one.
  git checkout -q -f -B "$BRANCH" "$sha" || return 1

  if [[ -f "$REQUIREMENTS" ]]; then
    log "installing $REQUIREMENTS"
    # --prefer-binary avoids compiling from source, which a 1 GB instance
    # cannot do reliably. pip leaves already-satisfied pins alone, so this is
    # quick when nothing changed.
    "$PY" -m pip install --disable-pip-version-check --quiet --prefer-binary -r "$REQUIREMENTS" || return 1
  else
    # Only commits older than requirements-prod.txt; the installed packages
    # from the newer commit are kept.
    log "warning: $REQUIREMENTS not in $sha; keeping the installed packages"
  fi

  # Fail on a syntax error before touching the running service.
  "$PY" -m compileall -q app || return 1

  # Query embedding model for the knowledge base (ONNX, no torch). A no-op
  # once cached; not fatal, but without it knowledge answers fall back to
  # the help articles.
  HF_HUB_OFFLINE=0 "$PY" -m app.chatbot.onnx_embedder >/dev/null 2>&1     || log "warning: could not fetch the ONNX embedding model; knowledge-base answers are degraded"

  # Browser for the PDF export. A no-op when already installed; not fatal,
  # because without it the frontend falls back to the print dialog.
  if "$PY" -c 'import playwright' 2>/dev/null; then
    "$PY" -m playwright install chromium >/dev/null 2>&1 \
      || log "warning: could not install Chromium; /reports/render-pdf will answer 503"
  fi
}

restart() {
  log "restarting $SERVICE"
  sudo systemctl restart "$SERVICE"
}

# ── Deploy ───────────────────────────────────────────────────────────────────
PREVIOUS_SHA="$(git rev-parse HEAD)"
git fetch --quiet --prune origin "$BRANCH"
TARGET_SHA="$(git rev-parse --verify "${COMMIT:-origin/$BRANCH}^{commit}")" \
  || fail "commit ${COMMIT:-origin/$BRANCH} not found after fetching $BRANCH"

# The commit must belong to the branch being deployed.
git merge-base --is-ancestor "$TARGET_SHA" "origin/$BRANCH" \
  || fail "$TARGET_SHA is not on origin/$BRANCH"

log "running:   $PREVIOUS_SHA"
log "deploying: $TARGET_SHA ($BRANCH)"

if [[ "$TARGET_SHA" == "$PREVIOUS_SHA" && "${FORCE:-0}" != "1" ]] && healthy; then
  log "already running $TARGET_SHA and healthy; nothing to do"
  exit 0
fi

if install_commit "$TARGET_SHA" && restart && wait_healthy; then
  log "deployed $TARGET_SHA"
  exit 0
fi

printf '::error::%s\n' "$TARGET_SHA did not come up healthy; rolling back to $PREVIOUS_SHA" >&2
sudo journalctl -u "$SERVICE" -n 60 --no-pager || true

if [[ "$TARGET_SHA" != "$PREVIOUS_SHA" ]]; then
  install_commit "$PREVIOUS_SHA" && restart && wait_healthy \
    && log "rollback complete; $PREVIOUS_SHA is serving" \
    || printf '::error::%s\n' "rollback to $PREVIOUS_SHA is not healthy either; the service needs attention" >&2
fi
exit 1
