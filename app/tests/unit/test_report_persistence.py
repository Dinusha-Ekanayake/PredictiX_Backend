"""Generated asset reports are recorded in the reports table.

The row used to be inserted through Supabase REST, but the reports table
grants nothing to the REST roles, so every insert was rejected and the error
swallowed: no asset report was ever recorded. It is now written through the
API's own SQLAlchemy session.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

import app.services.report_service as report_service
from app.models import Report

ASSET_ID, WAREHOUSE_ID, USER_ID = uuid4(), str(uuid4()), uuid4()


class FakeSession:
    def __init__(self, fail: bool = False):
        self.added, self.commits, self.rollbacks, self.fail = [], 0, 0, fail

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        if self.fail:
            raise RuntimeError("permission denied for table reports")
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _service(monkeypatch, tmp_path, db):
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    svc = report_service.ReportService.__new__(report_service.ReportService)
    svc.db = db
    svc.context_builder = SimpleNamespace(build_context=lambda asset_id: {
        "warehouse_id": WAREHOUSE_ID, "asset": {"asset_name": "Forklift 7"}, "metrics": {},
    })
    svc.ai_insight = SimpleNamespace(generate_insights=lambda ctx: {"executive_summary": "ok"})
    svc.pdf_render = SimpleNamespace(generate_pdf=lambda ctx, insights, report_id: str(pdf))
    monkeypatch.setattr(report_service.supabase_storage, "upload_file",
                        lambda **kw: "https://storage.example/reports/r.pdf")
    return svc


def test_the_report_row_is_committed_through_the_session(monkeypatch, tmp_path):
    db = FakeSession()
    url, _ = _service(monkeypatch, tmp_path, db).generate_asset_report(ASSET_ID, user_id=USER_ID)

    assert url.endswith("r.pdf") and db.commits == 1
    (row,) = db.added
    assert isinstance(row, Report)
    assert row.report_type == "asset_report" and row.status == "generated"
    # reports_target_check: an asset report carries both its asset and warehouse.
    assert row.asset_id == ASSET_ID and row.warehouse_id == UUID(WAREHOUSE_ID)
    assert row.generated_by == USER_ID and row.file_path == url


def test_a_failed_insert_is_rolled_back_logged_and_the_pdf_still_returned(monkeypatch, tmp_path, caplog):
    db = FakeSession(fail=True)
    with caplog.at_level(logging.ERROR, logger=report_service.log.name):
        url, _ = _service(monkeypatch, tmp_path, db).generate_asset_report(ASSET_ID, user_id=USER_ID)

    assert url.endswith("r.pdf") and db.rollbacks == 1
    assert any("was not recorded" in r.message and r.levelno == logging.ERROR for r in caplog.records)
