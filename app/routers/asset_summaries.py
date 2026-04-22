from fastapi import APIRouter, HTTPException
from datetime import datetime

from app.schemas.asset_summary import AssetSummaryRequest, AssetSummaryResponse
from app.ai.services.asset_summary_service import generate_asset_summary

router = APIRouter(prefix="/asset-summaries", tags=["Asset Summaries"])


@router.post("/generate", response_model=AssetSummaryResponse)
async def generate_summary(payload: AssetSummaryRequest):
    """
    Generate a summary for asset data using the Seq2Seq model
    
    This endpoint takes formatted asset/vehicle input text and generates 
    a human-readable summary using the pre-trained Seq2Seq model hosted on HuggingFace.
    
    Input format example:
    "Vehicle: SLW0225 | Type: Light Truck 3.5T | Model: Mitsubishi Canter | Component health: oil 93.5%, brakes 79.7%, tires 58.7%, battery 66.3%, hydraulics 62.5%"
    """
    try:
        summary = generate_asset_summary(payload.input_text)
        
        return AssetSummaryResponse(
            summary=summary,
            generated_at=datetime.utcnow().isoformat(),
            model_version="1.0"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid request: {str(e)}")


@router.get("/health")
async def health_check():
    """Check if asset summary model is loaded and accessible"""
    try:
        from app.ai.services.asset_summary_service import get_asset_summary_model
        
        model = get_asset_summary_model()
        return {
            "status": "ok",
            "model_loaded": model is not None,
            "message": "Asset summary model is ready"
        }
    except Exception as e:
        return {
            "status": "error",
            "model_loaded": False,
            "message": f"Model loading failed: {str(e)}"
        }
