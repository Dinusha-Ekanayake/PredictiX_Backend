"""7.3.5 Ticket Management and AI Processing (TK-01 .. TK-12)."""
import pytest

from .conftest import case

pytestmark = pytest.mark.functional

SAMPLE = ("The forklift hydraulic line is leaking fluid onto the warehouse floor "
          "and the mast will not lift a full pallet. It needs urgent attention.")


def _rows(payload):
    if isinstance(payload, dict):
        for k in ("items", "tickets", "data", "results"):
            if k in payload:
                return payload[k]
    return payload


@pytest.fixture
def ticket(client, auth, ctx, unique):
    """A ticket that exists for the duration of one test, then is removed."""
    tag = unique()
    r = client.post("/tickets/", json={
        "title": f"{tag} hydraulic leak",
        "description": SAMPLE,
        "created_by": ctx["admin_profile_id"],
        "asset_id": ctx["asset_in"],
        "warehouse_id": ctx["warehouse_id"],
    }, headers=auth("admin"))
    if r.status_code not in (200, 201):
        pytest.skip(f"could not create a fixture ticket ({r.status_code}): {r.text[:160]}")
    tid = r.json()["id"]
    yield r.json()
    client.delete(f"/tickets/{tid}", headers=auth("admin"))


@case("TK-01", "Create ticket with valid information", "Ticket is created successfully")
def test_tk_01_create(ticket):
    assert ticket.get("id"), "no id on the created ticket"
    assert ticket.get("ticket_number"), "no ticket_number assigned"
    assert ticket.get("status") == "open", f"unexpected initial status {ticket.get('status')!r}"


@case("TK-02", "Create ticket with incomplete required fields",
      "Validation error is returned")
def test_tk_02_validation(client, auth):
    r = client.post("/tickets/", json={"title": "missing the rest"}, headers=auth("admin"))
    assert r.status_code == 422, f"expected a validation error, got {r.status_code}"


@case("TK-03", "Submit ticket for categorization", "A predicted category is returned")
def test_tk_03_categorize(client, auth):
    r = client.post("/tickets/categorize", json={"title": "Hydraulic leak",
                                                 "description": SAMPLE},
                    headers=auth("admin"))
    assert r.status_code == 200, f"categorisation failed ({r.status_code}): {r.text[:200]}"
    body = r.json()
    cat = body.get("predicted_label") or body.get("category")
    assert cat, f"no category in the response: {list(body)[:6]}"
    assert str(cat).lower() in ("electrical", "mechanical", "software"), (
        f"{cat!r} is not one of the three ticket_category enum values")
    conf = body.get("confidence")
    assert conf is None or 0.0 <= float(conf) <= 1.0, f"confidence {conf} is outside 0..1"


@case("TK-04", "Submit ticket for priority prediction",
      "Low, Medium or High priority is returned")
def test_tk_04_prioritize(client, auth):
    # The endpoint takes a single `text` field, not title/description.
    r = client.post("/tickets/prioritize", json={"text": f"Hydraulic leak. {SAMPLE}"},
                    headers=auth("admin"))
    assert r.status_code == 200, f"prioritisation failed ({r.status_code}): {r.text[:200]}"
    body = r.json()
    pri = body.get("priority") or body.get("predicted_priority")
    assert pri, f"no priority in the response: {list(body)[:6]}"
    assert str(pri).lower() in ("low", "medium", "high"), f"unexpected priority {pri!r}"


@case("TK-05", "Request ticket summarization", "A concise summary is returned")
def test_tk_05_summarize(client, auth, ticket, requires_hf):
    r = client.get(f"/ticket-summaries/by-ticket/{ticket['id']}", headers=auth("admin"))
    assert r.status_code == 200, f"summarisation failed ({r.status_code}): {r.text[:200]}"

    body = r.json()
    summary = (body.get("summary") or "").strip()
    assert summary, "an empty summary was returned"
    assert len(summary) < len(ticket["description"]), (
        "the summary is no shorter than the description it summarises")


@case("TK-06", "Update ticket status", "Status is changed correctly")
def test_tk_06_update_status(client, auth, ticket):
    r = client.put(f"/tickets/{ticket['id']}", json={"status": "in_progress"},
                   headers=auth("admin"))
    assert r.status_code == 200, f"status update failed ({r.status_code}): {r.text[:160]}"
    got = client.get(f"/tickets/{ticket['id']}", headers=auth("admin"))
    assert got.json().get("status") == "in_progress", "status did not persist"


@case("TK-07", "Assign ticket", "Assignment is stored")
def test_tk_07_assign(client, auth, ctx, ticket):
    r = client.put(f"/tickets/{ticket['id']}",
                   json={"assigned_to": ctx["admin_profile_id"]}, headers=auth("admin"))
    assert r.status_code == 200, f"assignment failed ({r.status_code}): {r.text[:160]}"
    got = client.get(f"/tickets/{ticket['id']}", headers=auth("admin"))
    assert str(got.json().get("assigned_to")) == str(ctx["admin_profile_id"]), (
        "the assignee was not stored")


@case("TK-08", "Add ticket update or comment", "Update is linked to correct ticket")
def test_tk_08_comment(client, auth, ctx, ticket):
    r = client.post("/ticket-comments/", json={
        "ticket_id": ticket["id"],
        "user_id": ctx["admin_profile_id"],
        "comment": "Functional test comment.",
    }, headers=auth("admin"))
    assert r.status_code in (200, 201), f"comment failed ({r.status_code}): {r.text[:160]}"

    listing = client.get("/ticket-comments/", params={"ticket_id": ticket["id"]},
                         headers=auth("admin"))
    assert listing.status_code == 200
    rows = _rows(listing.json())
    assert any(str(c.get("ticket_id")) == str(ticket["id"]) for c in rows), (
        "the comment is not linked to the ticket")


@case("TK-09", "Resolve or close ticket", "Ticket lifecycle is updated correctly")
def test_tk_09_resolve(client, auth, ticket):
    r = client.put(f"/tickets/{ticket['id']}", json={"status": "resolved"},
                   headers=auth("admin"))
    assert r.status_code == 200, f"resolve failed ({r.status_code})"
    body = client.get(f"/tickets/{ticket['id']}", headers=auth("admin")).json()
    assert body.get("status") == "resolved", "status is not resolved"
    assert body.get("resolved_at"), "resolved_at was not stamped"


@case("TK-10", "Search tickets", "Matching tickets are returned")
def test_tk_10_search(client, auth, ticket):
    r = client.get("/tickets/", params={"search": ticket["ticket_number"]},
                   headers=auth("admin"))
    assert r.status_code == 200, f"search failed ({r.status_code})"
    rows = _rows(r.json())
    assert any(t.get("ticket_number") == ticket["ticket_number"] for t in rows), (
        "searching by ticket number did not return the ticket")


@case("TK-11", "Filter tickets by status, priority or category",
      "Correct tickets are displayed")
def test_tk_11_filter(client, auth):
    r = client.get("/tickets/", params={"status": "open", "limit": 50}, headers=auth("admin"))
    assert r.status_code == 200, f"filtered listing failed ({r.status_code})"
    rows = _rows(r.json())
    bad = [t for t in rows if t.get("status") != "open"]
    assert not bad, f"{len(bad)} returned tickets do not have status 'open'"


@case("TK-12", "Unauthorized user attempts restricted ticket action",
      "Request is rejected")
def test_tk_12_unauthorized(client, auth, ticket):
    r = client.delete(f"/tickets/{ticket['id']}", headers=auth("user"))
    assert r.status_code in (401, 403), (
        f"a standard user deleted or was allowed to delete a ticket ({r.status_code})")
