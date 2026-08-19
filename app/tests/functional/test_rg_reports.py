"""7.3.7 Report Generation and RAG (RG-01 .. RG-08)."""
import pytest

from .conftest import case

pytestmark = pytest.mark.functional


@case("RG-01", "Generate asset report", "Report contains the selected asset information")
def test_rg_01_asset_report(client, auth, ctx):
    import io

    from pypdf import PdfReader

    detail = client.get(f"/assets/{ctx['asset_in']}", headers=auth("admin"))
    assert detail.status_code == 200
    code = detail.json()["asset_code"]

    r = client.post(f"/asset-reports/{ctx['asset_in']}", headers=auth("admin"))
    assert r.status_code == 200, f"asset report failed ({r.status_code}): {r.text[:200]}"
    assert r.content[:4] == b"%PDF", (
        f"the endpoint did not return a PDF (starts with {r.content[:16]!r})")

    # The response is a rendered PDF, so the asset has to be read out of the
    # page text rather than the raw bytes.
    pages = PdfReader(io.BytesIO(r.content)).pages
    body = "\n".join(p.extract_text() or "" for p in pages)
    assert body.strip(), "the PDF carries no extractable text"
    assert code in body, (
        f"the report does not mention the requested asset {code}; "
        f"first 200 chars: {body[:200]!r}")


@case("RG-02", "Generate warehouse report", "Report uses the selected warehouse information")
def test_rg_02_warehouse_report_is_scoped(client, auth, ctx, db, requires_llm):
    from sqlalchemy import text

    r = client.get("/warehouse-dashboard/generate-report",
                   params={"warehouse_id": ctx["warehouse_id"]}, headers=auth("admin"))
    assert r.status_code == 200, f"warehouse report failed ({r.status_code}): {r.text[:200]}"
    body = r.json()

    scoped = db.execute(text(
        "SELECT count(*) FROM assets WHERE warehouse_id = CAST(:w AS uuid)"
    ), {"w": ctx["warehouse_id"]}).scalar()
    fleet = db.execute(text("SELECT count(*) FROM assets")).scalar()
    assert scoped != fleet, "cannot distinguish scoped from fleet-wide on this data"

    # Find any asset total the report states and check which population it used.
    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, int) and "asset" in k.lower() and "total" in k.lower():
                    yield k, v
                else:
                    yield from walk(v)
        elif isinstance(node, list):
            for v in node:
                yield from walk(v)

    totals = list(walk(body))
    assert totals, f"the report states no asset total to verify: keys={list(body)[:8]}"
    wrong = [(k, v) for k, v in totals if v == fleet and fleet != scoped]
    assert not wrong, (
        f"the report counts the whole fleet ({fleet}) rather than the selected "
        f"warehouse ({scoped}) in {[k for k, _ in wrong]} — warehouse_id is not "
        "scoping the query")


@case("RG-03", "Retrieve semantic context from pgvector", "Relevant information is returned")
def test_rg_03_pgvector_retrieval():
    from app.chatbot.knowledge_service import search_knowledge

    hits = search_knowledge("What does a critical health band mean for an asset?", 3)
    assert hits, "pgvector search returned nothing"
    assert isinstance(hits, list), f"unexpected return type {type(hits).__name__}"
    first = hits[0]
    assert isinstance(first, dict) and (first.get("content") or first.get("title")), (
        "retrieved rows carry no content")


@case("RG-04", "Generate RAG based report", "Retrieved context is included in generation")
def test_rg_04_report_uses_retrieved_context():
    from app.kb.kb_vector_store import get_kb_store

    store = get_kb_store()
    hits = store.retrieve("preventive maintenance ratio benchmark", top_k=4)
    assert hits, "the report knowledge store retrieved nothing"

    # The report path must use ranked retrieval, not whole-corpus stuffing.
    import inspect
    from app.agents import report_agents

    src = inspect.getsource(report_agents.run_warehouse_agent)
    assert "build_full_kb_context" not in src, (
        "run_warehouse_agent calls build_full_kb_context(), which concatenates "
        "the entire knowledge base into the prompt regardless of the question — "
        "the retrieval ranking is never applied on this path")


@case("RG-05", "Compare report values with database values",
      "Report remains consistent with source data")
def test_rg_05_report_matches_database(client, auth, ctx, db):
    from sqlalchemy import text

    r = client.get("/warehouse-dashboard/summary",
                   params={"warehouse_id": ctx["warehouse_id"]}, headers=auth("admin"))
    assert r.status_code == 200, f"summary failed ({r.status_code})"
    body = r.json()

    actual = db.execute(text(
        "SELECT count(*) FROM assets WHERE warehouse_id = CAST(:w AS uuid)"
    ), {"w": ctx["warehouse_id"]}).scalar()

    stated = None
    for key in ("total_assets", "asset_count", "assets_total", "total"):
        if isinstance(body.get(key), int):
            stated = body[key]
            break
    if stated is None:
        pytest.skip(f"the summary states no asset total: keys={list(body)[:10]}")
    assert stated == actual, (
        f"the summary reports {stated} assets, the database holds {actual}")


@case("RG-06", "Request report for invalid asset", "Controlled error response is returned")
def test_rg_06_invalid_asset(client, auth):
    bogus = "00000000-0000-0000-0000-000000000000"
    r = client.post(f"/asset-reports/{bogus}", headers=auth("admin"))
    assert r.status_code in (400, 404, 422), (
        f"an unknown asset produced {r.status_code} rather than a handled error")
    assert r.status_code != 500, "an unknown asset produced an unhandled server error"


@case("RG-07", "Unauthorized user requests restricted report", "Request is denied")
def test_rg_07_unauthorized(client, auth, ctx, requires_llm):
    r = client.get("/warehouse-dashboard/generate-report",
                   params={"warehouse_id": ctx["warehouse_id"]}, headers=auth("user"))
    assert r.status_code in (401, 403), (
        f"a standard user generated a warehouse report ({r.status_code})")


@case("RG-08", "Store generated report", "Report information is saved correctly")
def test_rg_08_report_is_persisted(client, auth, ctx, db):
    from sqlalchemy import text

    before = db.execute(text("SELECT count(*) FROM reports")).scalar()
    r = client.post(f"/asset-reports/{ctx['asset_in']}", headers=auth("admin"))
    assert r.status_code == 200, f"report generation failed ({r.status_code})"

    db.rollback()
    after = db.execute(text("SELECT count(*) FROM reports")).scalar()
    assert after > before, (
        f"the reports table still holds {after} rows after generating a report — "
        "generated reports are streamed to the caller and never persisted")
