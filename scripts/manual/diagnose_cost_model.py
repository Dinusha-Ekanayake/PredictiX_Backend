"""
Run this ON THE SERVER, from your backend project root, using the exact same
Python interpreter/virtualenv the deployed app uses:

    python3 diagnose_cost_model.py

It reproduces exactly what main.py's lifespan does when loading the v5
breakdown cost model, but prints the real reason for failure directly to
your terminal instead of it being swallowed by a try/except.
"""
import sys
import traceback
from pathlib import Path

print("=" * 70)
print("PredictiX v5 Cost Model — Diagnostic")
print("=" * 70)

print(f"\nPython: {sys.version}")
print(f"Running from: {Path.cwd()}")

# ── Step 1: is catboost importable? ──────────────────────────────────────────
print("\n[1] Checking catboost...")
try:
    import catboost
    print(f"    OK — catboost version {catboost.__version__}")
except Exception as e:
    print(f"    FAILED — {type(e).__name__}: {e}")
    print("    FIX: pip install catboost  (then restart the app)")

# ── Step 2: does the .pkl file actually exist where the code expects it? ────
print("\n[2] Checking for the model file...")
try:
    expected = (
        Path(__file__).resolve().parent
        / "app" / "ai" / "models" / "cost_estimation_model"
        / "predictix_breakdown_cost_model_v5.pkl"
    )
    print(f"    Expected path: {expected}")
    if expected.exists():
        size_mb = expected.stat().st_size / (1024 * 1024)
        print(f"    OK — file exists, {size_mb:.1f} MB")
    else:
        print("    FAILED — file does NOT exist at this path.")
        print("    FIX: copy predictix_breakdown_cost_model_v5.pkl to that exact folder.")
        # Show what IS in that folder, if it exists, to help spot typos
        folder = expected.parent
        if folder.exists():
            print(f"    Files currently in {folder}:")
            for f in folder.iterdir():
                print(f"      - {f.name}")
        else:
            print(f"    Folder does not even exist: {folder}")
except Exception as e:
    print(f"    Could not check — {type(e).__name__}: {e}")

# ── Step 3: try the actual load function the app calls ──────────────────────
print("\n[3] Calling load_breakdown_bundle() exactly as main.py does...")
try:
    import sys
    from pathlib import Path

    # Put the repository root on sys.path so `import app` works however this script
    # is invoked. Located by walking up to the directory that contains the app
    # package, rather than by counting parents, so moving this file cannot break it.
    _here = Path(__file__).resolve()
    _root = next(p for p in _here.parents if (p / "app" / "__init__.py").exists())
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    from app.ai.models.cost_estimation_model.breakdown_cost_model import load_breakdown_bundle
    bundle = load_breakdown_bundle()
    print("    SUCCESS")
    print(f"    version:        {bundle.get('version')}")
    print(f"    predictor_name: {bundle.get('predictor_name')}")
    print(f"    test R2:        {bundle.get('test_metrics', {}).get('R2')}")
    print(f"    fleet_mean_lkr: {bundle.get('fleet_mean_lkr')}")
    print("\n    ==> The bundle loads FINE here. If it still 503s in the running")
    print("        app, the app process needs a restart to pick this up, or the")
    print("        app is running from a different environment/directory than")
    print("        this script.")
except Exception:
    print("    FAILED — full traceback below:\n")
    traceback.print_exc()
    print("\n    ==> This traceback is the actual root cause. Paste it back.")

print("\n" + "=" * 70)