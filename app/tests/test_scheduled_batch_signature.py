"""Regression test: app.main's call into run_batch_for_all_assets must
always match the real function signature.

Guards against the bug found in the asset-domain audit (2026-08): main.py
called run_batch_for_all_assets(..., cost_bundle=breakdown_cost_bundle)
after the parameter had been renamed to breakdown_cost_bundle, so the
scheduled batch job's daily prediction refresh silently failed on every
run — a bare `except Exception: log.exception(...)` swallowed the
TypeError, so pdm_batch_predictions only ever got refreshed via manual
admin-triggered runs.

This inspects the real function signature via ast/inspect directly (no DB
connection or loaded ML models needed), so it fails fast if this class of
kwarg-name drift ever recurs.
"""
import ast
import inspect
from pathlib import Path

from app.ai.services.batch_prediction_service import run_batch_for_all_assets

_MAIN_PY = Path(__file__).resolve().parents[1] / "main.py"


def _kwargs_passed_to_run_batch_for_all_assets() -> set[str]:
    """Statically extract the keyword-argument names app/main.py's
    _run_scheduled_batch passes to run_batch_for_all_assets, by parsing the
    call — avoids importing app.main (which has heavyweight startup-time
    side effects: model loading, scheduler setup) just to introspect one
    call site."""
    tree = ast.parse(_MAIN_PY.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "run_batch_for_all_assets"
        ):
            return {kw.arg for kw in node.keywords if kw.arg is not None}
    raise AssertionError(
        "Could not find a run_batch_for_all_assets(...) call in app/main.py "
        "— did _run_scheduled_batch get renamed or moved?"
    )


def test_scheduled_batch_call_matches_run_batch_for_all_assets_signature():
    real_params = set(inspect.signature(run_batch_for_all_assets).parameters)
    passed_kwargs = _kwargs_passed_to_run_batch_for_all_assets()

    unknown = passed_kwargs - real_params
    assert not unknown, (
        f"app/main.py passes keyword argument(s) {sorted(unknown)} to "
        f"run_batch_for_all_assets(), but they don't exist on the real "
        f"function signature ({sorted(real_params)}). This is the exact bug "
        f"class that silently broke the scheduled PDM batch job "
        f"(cost_bundle vs breakdown_cost_bundle) — the scheduler's own "
        f"exception handler swallows this as a bare TypeError with no "
        f"visible failure, so it must be caught here instead."
    )


if __name__ == "__main__":
    test_scheduled_batch_call_matches_run_batch_for_all_assets_signature()
    print("OK: app/main.py's call into run_batch_for_all_assets matches its real signature.")
