"""
Debug endpoint to verify EXACT values in PostgreSQL
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from app.deps import get_db
from app.models import Asset, Ticket, AssetFailurePrediction, AssetCostPrediction

router = APIRouter(prefix="/debug", tags=["Debug"])

@router.get("/exact-db-values")
def get_exact_db_values(db: Session = Depends(get_db)):
    """
    Returns EXACT raw counts from PostgreSQL - no calculations, no filters
    """
    
    # Total Assets
    total_assets = db.query(Asset.id).count()
    
    # Total AssetFailurePrediction records
    total_predictions = db.query(AssetFailurePrediction.id).count()
    
    # Health scores - get all
    all_health_scores = db.query(AssetFailurePrediction.health_score).all()
    health_scores_list = [int(h[0]) for h in all_health_scores if h[0] is not None]
    
    # Average health
    avg_health = sum(health_scores_list) / len(health_scores_list) if health_scores_list else 0
    
    # Count by health score ranges
    healthy_count = db.query(AssetFailurePrediction.id).filter(AssetFailurePrediction.health_score >= 80).count()
    at_risk_count = db.query(AssetFailurePrediction.id).filter(AssetFailurePrediction.health_score < 60).count()
    critical_count = db.query(AssetFailurePrediction.id).filter(AssetFailurePrediction.health_score < 50).count()
    
    # Tickets
    total_tickets = db.query(Ticket.id).count()
    open_tickets = db.query(Ticket.id).filter(text("status != 'closed'")).count()
    
    # Costs
    total_cost = db.query(func.sum(AssetCostPrediction.estimated_cost)).scalar() or 0
    
    return {
        "status": "success",
        "exact_values": {
            "total_assets": total_assets,
            "total_asset_failures_predictions": total_predictions,
            "all_health_scores": health_scores_list[:20],  # First 20 for inspection
            "total_health_scores_count": len(health_scores_list),
            "average_health_score": round(avg_health, 2),
            "healthy_assets_count_>=80": healthy_count,
            "at_risk_assets_count_<60": at_risk_count,
            "critical_assets_count_<50": critical_count,
            "total_tickets": total_tickets,
            "open_tickets": open_tickets,
            "total_maintenance_cost_sum": int(total_cost),
        }
    }

@router.get("/asset-prediction-sample")
def get_asset_prediction_sample(db: Session = Depends(get_db), limit: int = 10):
    """
    Returns sample of Asset + AssetFailurePrediction joined data
    """
    results = db.query(Asset, AssetFailurePrediction)\
        .join(AssetFailurePrediction, Asset.id == AssetFailurePrediction.asset_id, isouter=True)\
        .limit(limit).all()
    
    data = []
    for asset, pred in results:
        data.append({
            "asset_id": asset.id,
            "asset_code": asset.asset_code,
            "asset_name": asset.asset_name,
            "prediction_id": pred.id if pred else None,
            "health_score": pred.health_score if pred else None,
        })
    
    return {
        "status": "success",
        "sample_count": len(data),
        "data": data
    }
