"""
app/routers/asset_reports.py

Routes:
  POST /asset-reports/{asset_id}  — generate real report from DB
  GET  /asset-reports/dummy/pdf   — generate dummy PDF for styling test
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from fastapi.background import BackgroundTasks
from sqlalchemy.orm import Session
from app.deps import get_db
from app.services.report_service import ReportService
from app.services.pdf_render import PDFRenderService
from app.schemas.report import AssetReportResponse
import uuid
import os
import traceback

router = APIRouter(prefix="/asset-reports", tags=["Asset Reports"])


# ─────────────────────────────────────────────────────────
#  REAL REPORT — pulls from DB
# ─────────────────────────────────────────────────────────
@router.post("/{asset_id}")
def generate_asset_report_endpoint(
    asset_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Generates an Asset Performance PDF and triggers an automatic browser download.
    The report is also uploaded to Supabase for permanent storage.
    """
    service = ReportService(db)
    try:
        url, pdf_path = service.generate_asset_report(asset_id)
        
        # Clean up temp file after response is sent
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


# ─────────────────────────────────────────────────────────
#  DUMMY REPORT — no DB needed, for testing PDF styling
# ─────────────────────────────────────────────────────────
@router.get("/dummy/pdf")
def generate_dummy_pdf(background_tasks: BackgroundTasks):
    """
    Generates a styled dummy PDF using hardcoded data.
    Use this to verify PDF rendering without needing a live DB asset.
    Matches the exact context shape produced by AssetContextBuilder.
    """
    try:
        # ── Context: same shape as AssetContextBuilder.build_context() ──
        dummy_context = {
            "generated_date": "April 28, 2026",
            "report_id":      "SLW04210",
            "asset": {
                "id":                     "7f31d186-f04f-4b7b-ac7d-6f0db9160f4f",
                "asset_code":             "SLW0421",
                "asset_name":             "Delivery Van 1.5T - SLW0421",
                "asset_type":             "vehicle",
                "vehicle_type":           "Delivery_Van_1.5T",
                "make":                   "Toyota",
                "model":                  "HiAce",
                "manufacture_year":       "2019",
                "registration_number":    "SLW-0421",
                "vin":                    "JT2BF22K1W0123456",
                "status":                 "active",
                "health_band":            "moderate",
                "criticality_score":      "7.8",
                "purchase_date":          "2019-06-15",
                "warranty_expiry_date":   "2024-06-15",
                "last_service_date":      "2024-01-20",
                "next_service_date":      "2024-04-20",
                "current_mileage":        "84320.5",
                "vehicle_age_years":      "5",
                "payload_capacity_kg":    "1500.0",
                "vehicle_role":           "Last Mile Delivery",
                "lifetime_service_count": "18",
                "lifetime_breakdown_count":"3",
                "description":            "Medium-duty delivery van assigned to Colombo urban routes.",
                "warehouse":              "LankaLogix - Colombo",
                "department":             "Operations",
            },
            "maintenance": [],   # no ORM rows in dummy
            "tickets":     [],
            "sensor": {
                "recorded_at":                     "2024-04-25 08:30",
                "tire_health_pct":                 "72.5",
                "brake_health_pct":                "65.0",
                "battery_health_pct":              "88.0",
                "oil_life_pct":                    "45.0",
                "hydraulic_health_pct":            "91.0",
                "coolant_temp_max_c":              "97.4",
                "engine_temp_avg_c":               "88.2",
                "active_fault_code_count":         "2",
                "days_since_last_service":         "96",
                "engine_hours_since_last_service": "420.5",
                "downtime_hours_last_90d":         "12.5",
                "fuel_level":                      "63.2",
                "odometer_km":                     "84320.5",
            },
            "metrics": {
                "total_events":              18,
                "preventive_count":          15,
                "corrective_count":           3,
                "preventive_ratio":          83.3,
                "corrective_ratio":          16.7,
                "total_cost":            245800.0,
                "avg_cost_per_event":     13655.6,
                "total_downtime_hours":      12.5,
                "total_tickets":             12,
                "open_tickets":               4,
                "high_priority_tickets":      2,
                "closed_tickets":             7,
                "health_score":              67.4,
                "failure_probability":       31.8,
                "risk_level":               "High",
                "days_until_maintenance":    14,
                "predicted_maintenance_date":"2024-05-12",
                "estimated_cost":         42500.0,
                "min_cost":               28000.0,
                "max_cost":               68000.0,
                "currency":               "LKR",
                "top_explanations": {
                    "engine_hours_since_last_service": 0.17,
                    "coolant_temp_max_c":              0.167,
                    "brake_health_pct":                0.164,
                    "days_since_last_service":         0.134,
                    "tire_health_pct":                 0.129,
                },
            },
        }

        # ── Insights: same shape as AIInsightService.generate_insights() ──
        dummy_insights = {
            "executive_summary": (
                "SLW0421 shows moderate health at 67.4% with a failure probability of 31.8%. "
                "Two active fault codes are detected and the vehicle has exceeded its 90-day "
                "service interval by 6 days. Brake health at 65% requires urgent attention."
            ),
            "maintenance_insights": [
                "Vehicle has exceeded recommended service interval by 6 days (96 vs 90 days)",
                "Brake health (65%) is below the 70% safe threshold — action required within 7 days",
                "Coolant temperature reached 97.4°C — monitor for head gasket stress",
                "2 active fault codes detected — full diagnostic scan recommended",
                "Oil life at 45% — schedule oil change at next service",
            ],
            "recommendations": {
                "critical": [
                    "Schedule brake inspection and pad replacement within 7 days",
                ],
                "high": [
                    "Perform full diagnostic scan for 2 active fault codes before next route",
                    "Book service appointment — predicted maintenance window closes 2024-05-12",
                ],
                "medium": [
                    "Monitor coolant temperature trend — consider coolant system flush",
                    "Plan tire replacement within next 30 days (health at 72.5%)",
                    "Schedule oil change at the upcoming service event",
                ],
            },
            "cost_analysis": {
                "maintenance_cost_mtd":    12500.0,
                "downtime_cost_mtd":       37500.0,
                "predicted_repair_cost":   42500.0,
                "predicted_downtime_days":  2.0,
            },
            "future_predictions": {
                "next_failure_probability":               0.318,
                "optimal_maintenance_date":               "2024-05-06",
                "suggested_maintenance_type":             "preventive",
                "predicted_maintenance_cost_next_6_months": 185000,
                "predicted_performance_in_6_months":      "declining without intervention",
                "estimated_remaining_life":               "8-10 months",
            },
            "operational_efficiency": {
                "efficiency_score":  71.0,
                "energy_consumption":"9.8 L/100km",
                "optimisation_recommendations": [
                    "Reduce idle time — vehicle idled 12.5 hours in last 90 days",
                    "Route optimization can reduce km-driven by ~15% based on trip count data",
                    "Preventive brake service now vs corrective later saves approx LKR 28,000",
                ],
            },
            "conclusion": (
                "SLW0421 requires urgent brake inspection and a full diagnostic scan before "
                "the next route assignment. Without intervention within 14 days, failure "
                "probability rises above 60%. Proactive maintenance now costs approximately "
                "LKR 42,500 versus a reactive repair cost of LKR 68,000+."
            ),
        }

        pdf_service = PDFRenderService()
        pdf_path    = pdf_service.generate_pdf(
            context=dummy_context,
            insights=dummy_insights,
            report_id=uuid.uuid4(),
        )

        # Clean up temp file after response is sent
        background_tasks.add_task(os.remove, pdf_path)

        return FileResponse(
            path=pdf_path,
            filename="dummy_asset_report.pdf",
            media_type="application/pdf",
        )

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))