"""
app/routers/asset_reports.py
Routes:
  POST /asset-reports/{asset_id}  — generate real PDF report
  GET  /asset-reports/dummy/pdf   — dummy PDF for styling test
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from fastapi.background import BackgroundTasks
from app.services.report_service import ReportService
from app.services.pdf_render import PDFRenderService
from app.deps import require_user
import uuid
import os
import traceback

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