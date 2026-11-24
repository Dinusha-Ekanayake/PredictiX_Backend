"""Check that this Python environment can run the PredictiX API.

    python scripts/deploy/check_runtime.py            # CI (no database, no .env)
    venv/bin/python scripts/deploy/check_runtime.py   # on the EC2 instance

Starts the application in-process with no database, and fails unless the
checks below pass. The only network access fetches the embedding model when
it is not cached yet.
  * the app imports and its startup completes,
  * the PdM classifier/regressor and the breakdown-cost model are loaded,
  * the survival bundle passes its checksum and unpickles,
  * chatbot queries can be embedded locally (sentence-transformers or ONNX),
    so the knowledge base answers without the hosted endpoint,
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


def _fetch_onnx_model() -> None:
    """Populate the model cache first: huggingface_hub reads HF_HUB_OFFLINE
    when it is imported, and the app defaults it to offline."""
    os.environ["HF_HUB_OFFLINE"] = "0"
    sys.path.insert(0, str(ROOT))
    from app.chatbot import onnx_embedder

    onnx_embedder.fetch_model_files()


def check(server: bool) -> list[str]:
    problems: list[str] = []
    if server:
        heavy = [name for name in HEAVY_PACKAGES if importlib.util.find_spec(name)]
        if heavy:
            problems.append(f"server install must not include {', '.join(heavy)}")
    try:
        _fetch_onnx_model()
    except Exception as exc:  # noqa: BLE001 - reported below as a failed embedding
        problems.append(f"ONNX embedding model could not be fetched: {exc}")

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

    import app.chatbot.knowledge_service as knowledge

    knowledge._embed_hosted = _hosted_not_allowed  # must work locally
    try:
        vector = knowledge.embed_text("forklift brake inspection interval")
        if len(vector) != knowledge.EMBEDDING_DIM:
            problems.append(f"query embedding has {len(vector)} dimensions")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"chatbot queries cannot be embedded locally: {exc}")
    return problems


def _hosted_not_allowed(value: str) -> list[float]:
    raise RuntimeError("fell through to the hosted endpoint")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server", action="store_true",
                        help="also require a server-only install (no torch or local models)")
    problems = check(parser.parse_args().server)
    print(f"Python {sys.version.split()[0]}")
    for problem in problems:
        print(f"FAIL  {problem}")
    if not problems:
        print("OK    the API starts, every shipped model loads and queries embed locally")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
