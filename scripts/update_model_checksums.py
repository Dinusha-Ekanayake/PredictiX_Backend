"""Record the SHA-256 of each pickled model the API loads.

Run after retraining a model and checking the new file is the intended one:

    python scripts/update_model_checksums.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.model_integrity import MANIFEST_PATH, write_manifest  # noqa: E402


def main() -> None:
    for rel, digest in write_manifest().items():
        print(f"{digest}  {rel}")
    print(f"Wrote {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
