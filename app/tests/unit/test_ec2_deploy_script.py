"""scripts/deploy/ec2_deploy.sh: idempotent deploys and automatic rollback.

Each test builds a real git origin and a clone standing in for the EC2 app
directory. Only the parts that would touch the host are stubbed: systemctl,
journalctl, sudo, curl (the health endpoint) and the virtualenv's python for
pip/playwright. The health stub reports the models as not loaded whenever the
checked-out tree contains a file named UNHEALTHY, so a "bad release" is just a
commit that adds that file.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "deploy" / "ec2_deploy.sh"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None or shutil.which("git") is None,
    reason="runs the deploy script under bash with POSIX tools (Linux CI)",
)

GOOD_ENV = "DATABASE_URL=postgresql://x\nJWT_SECRET=s\nSUPABASE_URL=https://x\nSUPABASE_KEY=k\n"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _write_exe(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture()
def host(tmp_path: Path):
    """An origin repo with one healthy commit on main, and a deployed clone."""
    origin, app, stubs = tmp_path / "origin", tmp_path / "app", tmp_path / "bin"
    origin.mkdir()
    stubs.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    _git(origin, "config", "user.email", "ci@example.invalid")
    _git(origin, "config", "user.name", "ci")
    (origin / "app").mkdir()
    (origin / "app" / "__init__.py").write_text("", encoding="utf-8")
    (origin / "requirements-prod.txt").write_text("# none\n", encoding="utf-8")
    _git(origin, "add", ".")
    _git(origin, "commit", "-q", "-m", "release 1")

    subprocess.run(["git", "clone", "-q", str(origin), str(app)], check=True)
    (app / ".env").write_text(GOOD_ENV, encoding="utf-8")
    (app / "venv" / "bin").mkdir(parents=True)

    log = tmp_path / "calls.log"
    # venv python: pip and playwright do nothing; everything else is real Python.
    _write_exe(app / "venv" / "bin" / "python", f"""
if [[ "$1" == "-m" && ( "$2" == "pip" || "$2" == "playwright" ) ]]; then echo "$2 $*" >> "{log}"; exit 0; fi
exec "{sys.executable}" "$@"
""")
    _write_exe(stubs / "sudo", 'exec "$@"\n')
    _write_exe(stubs / "systemctl", f'echo "systemctl $*" >> "{log}"\n')
    _write_exe(stubs / "journalctl", "exit 0\n")
    _write_exe(stubs / "curl", f"""
if [[ -e "{app}/UNHEALTHY" ]]; then echo '{{"models_loaded": false}}'; else echo '{{"models_loaded": true}}'; fi
""")

    def run(*args: str, **env: str) -> subprocess.CompletedProcess:
        full_env = {
            **os.environ, "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}",
            "MIN_FREE_MB": "0", "HEALTH_ATTEMPTS": "2", "HEALTH_INTERVAL": "0", **env,
        }
        return subprocess.run(["bash", str(SCRIPT), str(app), "predictix", *args],
                              capture_output=True, text=True, env=full_env)

    def commit(message: str, *, unhealthy: bool = False) -> str:
        marker = origin / "UNHEALTHY"
        if unhealthy:
            marker.write_text("", encoding="utf-8")
        elif marker.exists():
            marker.unlink()
        (origin / "app" / "version.py").write_text(f"V = {message!r}\n", encoding="utf-8")
        _git(origin, "add", "-A")
        _git(origin, "commit", "-q", "-m", message)
        return _git(origin, "rev-parse", "HEAD")

    def restarts() -> int:
        return log.read_text(encoding="utf-8").count("systemctl restart") if log.exists() else 0

    return {"app": app, "run": run, "commit": commit, "restarts": restarts,
            "head": lambda: _git(app, "rev-parse", "HEAD")}


def test_a_healthy_release_is_installed_at_the_exact_commit(host):
    target = host["commit"]("release 2")
    newer = host["commit"]("release 3, not yet tested")
    result = host["run"]("main", target)
    assert result.returncode == 0, result.stderr
    assert host["head"]() == target != newer
    assert host["restarts"]() == 1


def test_redeploying_the_running_healthy_commit_changes_nothing(host):
    target = host["commit"]("release 2")
    assert host["run"]("main", target).returncode == 0
    again = host["run"]("main", target)
    assert again.returncode == 0 and "nothing to do" in again.stdout
    assert host["restarts"]() == 1


def test_an_unhealthy_release_is_rolled_back(host):
    good = host["head"]()
    bad = host["commit"]("release 2 breaks model loading", unhealthy=True)
    result = host["run"]("main", bad)
    assert result.returncode == 1
    assert "rolling back" in result.stderr
    assert host["head"]() == good
    assert host["restarts"]() == 2  # the bad release, then the rollback


def test_nothing_changes_when_a_required_setting_is_missing(host):
    before = host["head"]()
    target = host["commit"]("release 2")
    (host["app"] / ".env").write_text("DATABASE_URL=x\nSUPABASE_URL=x\nSUPABASE_KEY=x\n", encoding="utf-8")
    result = host["run"]("main", target)
    assert result.returncode == 1 and "JWT_SECRET is missing" in result.stderr
    assert host["head"]() == before and host["restarts"]() == 0


@pytest.mark.parametrize("branch,commit", [("main;rm -rf /", ""), ("main", "$(id)")])
def test_unsafe_branch_or_commit_values_are_refused(host, branch, commit):
    result = host["run"](branch, commit)
    assert result.returncode == 1 and "refusing unsafe" in result.stderr
    assert host["restarts"]() == 0


def test_a_commit_that_is_not_on_the_branch_is_refused(host):
    before = host["head"]()
    origin = host["app"].parent / "origin"
    _git(origin, "checkout", "-q", "-b", "experiment")
    stray = host["commit"]("unreviewed work")
    _git(origin, "checkout", "-q", "main")
    _git(host["app"], "fetch", "-q", "origin", "experiment")
    result = host["run"]("main", stray)
    assert result.returncode == 1 and "is not on origin/main" in result.stderr
    assert host["head"]() == before and host["restarts"]() == 0
