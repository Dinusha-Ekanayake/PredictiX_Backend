"""SHA-256 check for pickled model artifacts before they are loaded.

Unpickling runs code stored in the file, so a pickle is loaded only when its
checksum matches the one recorded in app/ai/models/model_checksums.json. After
retraining a model, record the new file with:

    python scripts/update_model_checksums.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parent / "models"
MANIFEST_PATH = MODELS_DIR / "model_checksums.json"

# Pickled artifacts the running API loads. LightGBM boosters are plain text
# and are not listed.
PICKLED_ARTIFACTS = (
    "cost_estimation_model/predictix_breakdown_cost_model_v5.pkl",
    "survival_analysis/survival_bundle.pkl",
)


class ModelIntegrityError(RuntimeError):
    """A model file is missing from the manifest or its contents changed."""


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_key(path: Path) -> str:
    return Path(path).resolve().relative_to(MODELS_DIR).as_posix()


def verify_model_file(path: Path | str) -> None:
    """Raise ModelIntegrityError unless the file matches its recorded checksum."""
    path = Path(path)
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelIntegrityError(f"Model checksum manifest unreadable: {exc}") from exc

    key = _manifest_key(path)
    expected = manifest.get(key)
    if not expected:
        raise ModelIntegrityError(
            f"{key} has no recorded checksum. Run scripts/update_model_checksums.py "
            "after checking the file is the one you trained."
        )
    actual = sha256_of(path)
    if actual != expected:
        raise ModelIntegrityError(
            f"{key} does not match its recorded checksum, refusing to load it."
        )


def write_manifest() -> dict[str, str]:
    """Record the current checksum of every listed artifact."""
    manifest = {rel: sha256_of(MODELS_DIR / rel) for rel in PICKLED_ARTIFACTS}
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
