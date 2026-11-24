"""Check that this Python environment can run the PredictiX API.

    python scripts/deploy/check_runtime.py            # CI (no database, no .env)
    venv/bin/python scripts/deploy/check_runtime.py   # on the EC2 instance

Starts the application in-process with no database and no network calls, and
fails unless:
  * the app imports and its startup completes,
  * the PdM classifier/regressor and the breakdown-cost model are loaded,
  * the survival bundle passes its checksum and unpickles,
  * no torch / local-model package is installed when --server is given (the
    EC2 instance cannot hold them).

Exit code 0 means the environment is fit to serve; anything else is printed.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEAVY_PACKAGES = ("torch", "sentence_transformers", "transformers")


def _isolate_from_real_services() -> None:
    """No database, no Supabase, no Hugging Face, no scheduler, no .env file."""
    for name in ("DATABASE_URL", "DATABASE_PASSWORD", "SUPABASE_URL", "SUPABASE_KEY",
                 "SUPABASE_SERVICE_ROLE_KEY"):
        os.environ.pop(name, None)
    os.environ.update(JWT_SECRET=os.getenv("JWT_SECRET") or "runtime-check-only",
                      SCHEDULER_ENABLED="false", DISABLE_HF_MODELS="true")
    import dotenv

    dotenv.load_dotenv = lambda *args, **kwargs: False  # keep the operator's .env out of it


def check(server: bool) -> list[str]:
    problems: list[str] = []
    if server:
        heavy = [name for name in HEAVY_PACKAGES if importlib.util.find_spec(name)]
        if heavy:
            problems.append(f"server install must not include {', '.join(heavy)}")

    _isolate_from_real_services()
    sys.path.insert(0, str(ROOT))
    from fastapi.testclient import TestClient

    import app.main as main
    from app.ai.services.survival_service import _load_bundle

    with TestClient(main.app) as client:
        health = client.get("/").json()
    if health.get("models_loaded") is not True:
        problems.append("PdM classifier/regressor did not load")
    if health.get("cost_model_loaded") is not True:
        problems.append("breakdown cost model did not load")
    try:
        _load_bundle()
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        problems.append(f"survival bundle did not load: {exc}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server", action="store_true",
                        help="also require a server-only install (no torch or local models)")
    problems = check(parser.parse_args().server)
    print(f"Python {sys.version.split()[0]}")
    for problem in problems:
        print(f"FAIL  {problem}")
    if not problems:
        print("OK    the API starts and every shipped model loads")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
