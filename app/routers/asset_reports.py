"""
app/routers/asset_reports.py

Routes:
  POST /asset-reports/{asset_id}  — generate real PDF report
  GET  /asset-reports/dummy/pdf   — dummy PDF for styling test

  + Merged in:
  POST /reports/render-pdf        — HTML → PDF rendering (Playwright)
  CRUD /reports                   — Report management

NOTE: this file now defines TWO router objects — `router` (/asset-reports)
and `reports_router` (/reports). main.py must import and register BOTH:

    from .routers.asset_reports import router as asset_reports_router, reports_router
    ...
    app.include_router(asset_reports_router)
    app.include_router(reports_router)

The standalone app/routers/reports.py file is now redundant (its CRUD routes
are duplicated here) — main.py must NOT also import/register that file's
router, or /reports/* would have two competing route definitions.
"""

from __future__ import annotations

import uuid
import os
import traceback
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.background import BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

# Existing imports (UNCHANGED)
from app.services.report_service import ReportService
from app.services.pdf_render import PDFRenderService
from app.deps import get_db, require_user, require_admin
from app.models import Asset, Profile, Report, Ticket, Warehouse
from app.schemas.report import ReportCreate, ReportUpdate, ReportOut

log = logging.getLogger("predictix.reports")

# ════════════════════════════════════════════════════════════════════
# EXISTING ROUTER (UNCHANGED) → /asset-reports
# ════════════════════════════════════════════════════════════════════
router = APIRouter(
    prefix="/asset-reports",
    tags=["Asset Reports"],
    dependencies=[Depends(require_user)],
)


@router.post("/{asset_id}")
def generate_asset_report_endpoint(
    asset_id: uuid.UUID,
    background_tasks: BackgroundTasks,
):
    service = ReportService()
    try:
        url, pdf_path = service.generate_asset_report(asset_id)
        background_tasks.add_task(os.remove, pdf_path)
        return FileResponse(
            path=pdf_path,
            filename=f"Asset_Report_{asset_id}.pdf",
            media_type="application/pdf",
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to generate report: {str(e)}")


@router.get("/dummy/pdf")
def generate_dummy_pdf(background_tasks: BackgroundTasks):
    try:
        pdf_service = PDFRenderService()
        dummy_context = {
            "generated_date": "June 13, 2026", "report_id": "DUMMY001",
            "asset": {
                "id": "dummy", "asset_code": "SLW0421",
                "asset_name": "Delivery Van - SLW0421", "asset_type": "vehicle",
                "vehicle_type": "Delivery_Van", "make": "Toyota", "model": "HiAce",
                "manufacture_year": "2019", "registration_number": "SLW-0421",
                "vin": "JT2BF22K1W0123456", "status": "active",
                "health_band": "moderate", "criticality_score": "7.8",
                "purchase_date": "2019-06-15", "warranty_expiry_date": "2024-06-15",
                "last_service_date": "2024-01-20", "next_service_date": "2024-04-20",
                "current_mileage": "84320", "vehicle_age_years": "5",
                "payload_capacity_kg": "1500", "vehicle_role": "Last Mile Delivery",
                "lifetime_service_count": "18", "lifetime_breakdown_count": "3",
                "description": "Medium-duty delivery van.",
                "warehouse": "LankaLogix - Colombo", "department": "Operations",
            },
            "maintenance": [], "tickets": [],
            "sensor": {
                "recorded_at": "2024-04-25 08:30", "tire_health_pct": "72",
                "brake_health_pct": "65", "battery_health_pct": "88",
                "oil_life_pct": "45", "hydraulic_health_pct": "91",
                "coolant_temp_max_c": "97", "engine_temp_avg_c": "88",
                "active_fault_code_count": "2", "days_since_last_service": "96",
                "engine_hours_since_last_service": "420",
                "downtime_hours_last_90d": "12", "fuel_level": "63",
                "odometer_km": "84320",
            },
            "metrics": {
                "total_events": 18, "preventive_count": 15, "corrective_count": 3,
                "preventive_ratio": 83.3, "corrective_ratio": 16.7,
                "total_cost": 245800.0, "avg_cost_per_event": 13655.6,
                "total_downtime_hours": 12.5, "total_tickets": 12,
                "open_tickets": 4, "high_priority_tickets": 2, "closed_tickets": 7,
                "health_score": 67.4, "failure_probability": 31.8,
                "risk_level": "High", "days_until_maintenance": 14,
                "predicted_maintenance_date": "2024-05-12",
                "estimated_cost": 42500.0, "min_cost": 28000.0,
                "max_cost": 68000.0, "currency": "LKR", "top_explanations": {},
            },
        }
        dummy_insights = {
            "executive_summary": "Asset shows moderate health at 67.4%.",
            "maintenance_insights": ["Brake health below safe threshold."],
            "recommendations": {"critical": [], "high": [], "medium": []},
            "cost_analysis": {
                "maintenance_cost_mtd": 12500.0, "downtime_cost_mtd": 37500.0,
                "predicted_repair_cost": 42500.0, "predicted_downtime_days": 2.0,
            },
            "future_predictions": {
                "next_failure_probability": 0.318,
                "optimal_maintenance_date": "2024-05-06",
                "suggested_maintenance_type": "preventive",
                "predicted_maintenance_cost_next_6_months": 185000,
                "predicted_performance_in_6_months": "declining",
                "estimated_remaining_life": "8-10 months",
            },
            "operational_efficiency": {
                "optimisation_recommendations": ["Reduce idle time."],
            },
            "conclusion": "Schedule inspection soon.",
        }
        pdf_path = pdf_service.generate_pdf(
            context=dummy_context,
            insights=dummy_insights,
            report_id=uuid.uuid4(),
        )
        background_tasks.add_task(os.remove, pdf_path)
        return FileResponse(
            path=pdf_path,
            filename="dummy_asset_report.pdf",
            media_type="application/pdf",
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════════
# MERGED-IN ROUTER → /reports (CRUD + PDF rendering)
# ════════════════════════════════════════════════════════════════════
reports_router = APIRouter(
    prefix="/reports",
    tags=["Reports"],
    dependencies=[Depends(require_user)],
)

@reports_router.post("/", response_model=ReportOut)
def create_report(payload: ReportCreate, db: Session = Depends(get_db)):
    if payload.asset_id and not db.query(Asset).filter(Asset.id == payload.asset_id).first():
        raise HTTPException(status_code=404, detail="Asset not found")
    if payload.warehouse_id and not db.query(Warehouse).filter(Warehouse.id == payload.warehouse_id).first():
        raise HTTPException(status_code=404, detail="Warehouse not found")
    if payload.ticket_id and not db.query(Ticket).filter(Ticket.id == payload.ticket_id).first():
        raise HTTPException(status_code=404, detail="Ticket not found")
    if payload.generated_by and not db.query(Profile).filter(Profile.id == payload.generated_by).first():
        raise HTTPException(status_code=404, detail="User not found")

    obj = Report(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@reports_router.get("/", response_model=list[ReportOut])
def list_reports(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return db.query(Report).order_by(Report.created_at.desc()).offset(offset).limit(limit).all()


@reports_router.get("/{report_id}", response_model=ReportOut)
def get_report(report_id: str, db: Session = Depends(get_db)):
    obj = db.query(Report).filter(Report.id == report_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Report not found")
    return obj


@reports_router.put("/{report_id}", response_model=ReportOut)
def update_report(report_id: str, payload: ReportUpdate, db: Session = Depends(get_db)):
    obj = db.query(Report).filter(Report.id == report_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Report not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, key, value)

    db.commit()
    db.refresh(obj)
    return obj


@reports_router.delete("/{report_id}", dependencies=[Depends(require_admin)])
def delete_report(report_id: str, db: Session = Depends(get_db)):
    obj = db.query(Report).filter(Report.id == report_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Report not found")

    db.delete(obj)
    db.commit()
    return {"message": "Report deleted"}


# ── PDF rendering — server-side HTML → PDF via headless Chromium ────────────
#
# Why this exists: the frontend used to call window.print() on a hidden
# iframe, which always shows Chrome/Edge's own print header/footer (page
# title, URL, date) — a browser-level feature with no CSS/JS override. The
# only way to guarantee it never appears is to never enter the browser's
# print pipeline at all.
#
# Setup: pip install playwright && playwright install --with-deps chromium

class RenderPdfRequest(BaseModel):
    html: str = Field(..., description="Full HTML document string to render (as produced by assetPdfExport.ts's generateAssetReportHtml()).")
    filename: str = Field(default="report.pdf", description="Suggested download filename.")


# Repeating footer — rendered by Chromium on every physical page. Playwright's
# header/footer templates run in an isolated context with no access to our
# page's own <style>, so all styling here must be inline.
_FOOTER_TEMPLATE = """
<div style="width:100%; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;
            font-size:7.5px; color:#6b7280; display:flex; justify-content:space-between;
            padding:0 13mm; box-sizing:border-box;">
  <span>PredictiX AI Platform &nbsp;&middot;&nbsp; Asset Performance Report &nbsp;&middot;&nbsp; Confidential &nbsp;&middot;&nbsp; &copy; Predictix 2026</span>
  <span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span>
</div>
"""

# Empty header — display_header_footer must be True for the footer template
# to render at all, but we don't want Chromium's default header content
# (title/date/url), so we supply a blank one explicitly.
_HEADER_TEMPLATE = "<span></span>"


@reports_router.post("/render-pdf")
async def render_pdf(payload: RenderPdfRequest) -> Response:
    """Render the given HTML to a PDF and return it as a binary download."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="PDF rendering is not available on this server (playwright not installed).",
        ) from exc

    if not payload.html or len(payload.html) < 50:
        raise HTTPException(status_code=400, detail="html payload is empty or too short")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            try:
                page = await browser.new_page()
                await page.set_content(payload.html, wait_until="networkidle")
                pdf_bytes = await page.pdf(
                    format="A4",
                    print_background=True,
                    display_header_footer=True,
                    header_template=_HEADER_TEMPLATE,
                    footer_template=_FOOTER_TEMPLATE,
                    margin={"top": "10mm", "bottom": "18mm", "left": "13mm", "right": "13mm"},
                )
            finally:
                await browser.close()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        log.exception("PDF render failed")
        raise HTTPException(status_code=500, detail=f"PDF render failed: {exc}") from exc

    safe_name = payload.filename.replace('"', "").strip() or "report.pdf"
    if not safe_name.lower().endswith(".pdf"):
        safe_name += ".pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )