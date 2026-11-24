"""Generated asset reports are recorded in the reports table.

The table's reports_target_check constraint requires an asset_report row to
carry both asset_id and warehouse_id. Without warehouse_id every insert was
rejected and the error swallowed, so no asset report was ever recorded.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from uuid import uuid4

import pytest

import app.services.report_service as report_service

ASSET_ID, WAREHOUSE_ID, USER_ID = uuid4(), str(uuid4()), uuid4()


class _Table:
    def __init__(self, inserted, fail):
        self.inserted, self.fail = inserted, fail

    def insert(self, row):
        if self.fail:
            raise RuntimeError("new row violates check constraint")
        self.inserted.append(row)
        return SimpleNamespace(execute=lambda: None)


@pytest.fixture()
def service(monkeypatch, tmp_path):
    inserted: list[dict] = []
    state = {"fail": False}
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    svc = report_service.ReportService.__new__(report_service.ReportService)
    svc.supabase = SimpleNamespace(table=lambda name: _Table(inserted, state["fail"]))
    svc.context_builder = SimpleNamespace(build_context=lambda asset_id: {
        "warehouse_id": WAREHOUSE_ID, "asset": {"asset_name": "Forklift 7"}, "metrics": {},
    })
    svc.ai_insight = SimpleNamespace(generate_insights=lambda ctx: {"executive_summary": "ok"})
    svc.pdf_render = SimpleNamespace(generate_pdf=lambda ctx, insights, report_id: str(pdf))
    monkeypatch.setattr(report_service.supabase_storage, "upload_file",
                        lambda **kw: "https://storage.example/reports/r.pdf")
    return svc, inserted, state


def test_the_row_satisfies_the_target_check(service):
    svc, inserted, _ = service
    url, _ = svc.generate_asset_report(ASSET_ID, user_id=USER_ID)
    assert url.endswith("r.pdf")
    (row,) = inserted
    assert row["report_type"] == "asset_report"
    assert row["asset_id"] == str(ASSET_ID) and row["warehouse_id"] == WAREHOUSE_ID
    assert row["status"] == "generated" and row["generated_by"] == str(USER_ID)


def test_a_rejected_row_is_logged_as_an_error_but_the_pdf_is_still_returned(service, caplog):
    svc, _, state = service
    state["fail"] = True
    with caplog.at_level(logging.ERROR, logger=report_service.log.name):
        url, _ = svc.generate_asset_report(ASSET_ID, user_id=USER_ID)
    assert url.endswith("r.pdf")
    assert any("was not recorded" in r.message and r.levelno == logging.ERROR for r in caplog.records)
