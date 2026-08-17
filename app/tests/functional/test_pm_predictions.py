"""7.3.4 Predictive Maintenance, Cost and Explainability (PM-01 .. PM-11)."""
import pytest

from app.services.health_bands import band_for
from .conftest import case

pytestmark = pytest.mark.functional


@pytest.fixture
def prediction(client, auth, ctx):
    """The current stored prediction for the shared test asset.

    Function scoped because `auth` is: a module-scoped fixture cannot depend
    on a function-scoped one, and pytest reports that as a setup error on
    every test that asks for it.
    """
    r = client.get(f"/batch-predictions/{ctx['asset_in']}", headers=auth("admin"))
    if r.status_code != 200:
        pytest.skip(f"no stored prediction for the test asset ({r.status_code})")
    return r.json()


@case("PM-01", "Retrieve current asset prediction", "Current prediction record is returned")
def test_pm_01_current_prediction(client, auth, ctx):
    r = client.get(f"/batch-predictions/{ctx['asset_in']}", headers=auth("admin"))
    assert r.status_code == 200, f"prediction unavailable ({r.status_code})"
    body = r.json()
    assert str(body.get("asset_id")) == ctx["asset_in"], "returned another asset's prediction"
    assert body.get("predicted_at"), "no predicted_at timestamp"


@case("PM-02", "View maintenance probability",
      "Probability and maintenance status are displayed")
def test_pm_02_probability(prediction):
    p = prediction.get("failure_probability")
    assert p is not None, "no failure_probability on the stored prediction"
    assert 0.0 <= float(p) <= 1.0, f"probability {p} is outside 0..1"
    assert prediction.get("maintenance_required") is not None, "no maintenance_required flag"


@case("PM-03", "View maintenance timing", "Predicted days until maintenance are displayed")
def test_pm_03_days_until(prediction):
    d = prediction.get("predicted_days_until_maintenance")
    assert d is not None, "no predicted_days_until_maintenance"
    assert int(d) >= 0, f"negative days until maintenance ({d})"


@case("PM-04", "View predicted maintenance date",
      "Date is displayed according to decision logic")
def test_pm_04_predicted_date(prediction):
    assert prediction.get("predicted_maintenance_date"), "no predicted_maintenance_date"


@case("PM-05", "View asset health information", "Health score and health band are displayed")
def test_pm_05_health(prediction):
    score = prediction.get("health_score")
    assert score is not None, "no health_score"
    assert 0 <= float(score) <= 100, f"health score {score} is outside 0..100"

    status = prediction.get("health_status")
    assert status, "no health_status"
    expected = band_for(float(score))
    assert status == expected, (
        f"health_status is {status!r} but a score of {score} bands as "
        f"{expected!r} under the canonical definition")


@case("PM-06", "Request maintenance cost estimate", "Point estimate is returned")
def test_pm_06_cost_estimate(client, auth, ctx):
    r = client.get(f"/predictions/cost/{ctx['asset_in']}", headers=auth("admin"))
    assert r.status_code == 200, f"cost endpoint failed ({r.status_code}): {r.text[:200]}"
    body = r.json()
    est = body.get("estimated_cost_lkr", body.get("predicted_cost_lkr"))
    assert est is not None, "no cost point estimate returned"
    assert float(est) > 0, f"non-positive cost estimate ({est})"


@case("PM-07", "View cost interval", "Lower and upper estimates are displayed")
def test_pm_07_cost_interval(prediction):
    lo = prediction.get("min_cost_lkr")
    hi = prediction.get("max_cost_lkr")
    est = prediction.get("estimated_cost_lkr")
    if lo is None and hi is None:
        pytest.skip("this asset has no stored cost interval")
    assert lo is not None and hi is not None, "only one side of the interval is present"
    assert float(lo) <= float(hi), f"inverted interval: {lo} > {hi}"
    if est is not None:
        assert float(lo) <= float(est) <= float(hi), (
            f"the interval [{lo}, {hi}] excludes its own estimate {est}")


@case("PM-08", "View SHAP explanation", "Important contributing factors are shown")
def test_pm_08_shap(prediction):
    factors = prediction.get("top_explanations") or prediction.get("contributing_factors")
    assert factors, "no explanation payload on the prediction"
    assert isinstance(factors, list) and factors, "explanations are empty"
    first = factors[0]
    assert isinstance(first, dict), f"unexpected explanation shape: {type(first).__name__}"
    assert any(k in first for k in ("feature", "name", "factor")), (
        f"explanation entries name no feature: {list(first)[:5]}")


@case("PM-09", "View prediction confidence information",
      "Available confidence information is shown")
def test_pm_09_confidence(prediction):
    # Confidence is expressed as the tier plus the agreement flag from the
    # decision layer, not as a single scalar.
    assert prediction.get("tier"), "no decision tier on the prediction"
    assert prediction.get("tier") in ("urgent", "watch", "healthy", "conflict"), (
        f"unknown tier {prediction.get('tier')!r}")
    assert prediction.get("agreement") is not None, "no agreement flag"


@case("PM-10", "View component analysis",
      "Supported Weibull based component results are returned")
def test_pm_10_component_survival(client, auth, ctx):
    r = client.get(f"/survival/{ctx['asset_in']}", headers=auth("admin"))
    assert r.status_code == 200, f"survival endpoint failed ({r.status_code}): {r.text[:200]}"
    body = r.json()
    comps = body.get("components", body)
    assert comps, "no component results returned"
    names = {c.get("component") for c in comps} if isinstance(comps, list) else set(comps)
    for expected in ("brake", "tire", "battery", "oil", "hydraulic"):
        assert expected in names, f"component {expected} missing from the response"


@case("PM-11", "Prediction data is unavailable",
      "Missing value is handled without fabricated output")
def test_pm_11_no_fabricated_values(db):
    from sqlalchemy import text

    # A failed prediction must store a null probability, never a placeholder.
    bad = db.execute(text("""
        SELECT count(*) FROM pdm_batch_predictions
        WHERE status <> 'ok' AND failure_probability IS NOT NULL
    """)).scalar()
    assert bad == 0, (
        f"{bad} failed predictions carry a probability value instead of null")

    # And an ok row must not be silently empty.
    hollow = db.execute(text("""
        SELECT count(*) FROM pdm_batch_predictions
        WHERE status = 'ok' AND failure_probability IS NULL
    """)).scalar()
    assert hollow == 0, (
        f"{hollow} predictions are marked ok but carry no probability")
