from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from datetime import datetime
import logging

from app.schemas.asset_summary import AssetSummaryRequest, AssetSummaryResponse
from app.ai.services.asset_summary_service import generate_asset_summary, get_asset_summary_repo, get_hf_credentials
from app.deps import get_db, require_user
from app.models import Asset

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/asset-summaries",
    tags=["Asset Summaries"],
    dependencies=[Depends(require_user)],
)


def _build_asset_input_text(asset: Asset) -> str:
    """Build the pipe-separated input text for the asset summary model from an Asset ORM object."""
    parts = []

    name = asset.asset_name or asset.asset_code or "Unknown Asset"
    parts.append(f"Asset: {name}")

    if asset.asset_type:
        parts.append(f"Type: {asset.asset_type}")
    if asset.vehicle_type:
        parts.append(f"Vehicle type: {asset.vehicle_type}")
    if asset.make and asset.model:
        parts.append(f"Model: {asset.make} {asset.model}")
    elif asset.make:
        parts.append(f"Make: {asset.make}")
    if asset.manufacture_year:
        parts.append(f"Year: {asset.manufacture_year}")
    if asset.fuel_type:
        parts.append(f"Fuel: {asset.fuel_type}")
    if asset.status:
        parts.append(f"Status: {asset.status}")
    if asset.health_band:
        parts.append(f"Health: {asset.health_band}")
    if asset.criticality_score is not None:
        parts.append(f"Criticality score: {asset.criticality_score}")
    if asset.current_mileage is not None:
        parts.append(f"Mileage: {asset.current_mileage} km")
    if asset.maintenance_priority:
        parts.append(f"Maintenance priority: {asset.maintenance_priority}")

    return " | ".join(parts)



@router.get("/by-asset/{asset_id}", response_model=AssetSummaryResponse)
async def get_summary_by_asset(asset_id: str, db: Session = Depends(get_db)):
    """
    Fetch an asset by its ID, auto-build the input text, and generate a summary.

    This is used by the ticket creation dialog to show asset context at a glance.
    """
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    input_text = _build_asset_input_text(asset)
    try:
        logger.info(f"[AssetSummary] Generating summary for asset {asset_id}: {input_text[:80]}...")
        summary = generate_asset_summary(input_text)
        logger.info(f"[AssetSummary] ✓ Summary generated for asset {asset_id}")
        return AssetSummaryResponse(
            summary=summary,
            generated_at=datetime.utcnow().isoformat(),
            model_version="1.0",
        )
    except Exception as e:
        logger.error(f"[AssetSummary] ✗ Failed for asset {asset_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Summary generation failed: {str(e)}")


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
        logger.info(f"[AssetSummary] Generating summary for input: {payload.input_text[:80]}...")
        summary = generate_asset_summary(payload.input_text)
        logger.info(f"[AssetSummary] ✓ Summary generated successfully")
        
        return AssetSummaryResponse(
            summary=summary,
            generated_at=datetime.utcnow().isoformat(),
            model_version="1.0"
        )
    except ValueError as e:
        error_msg = f"Invalid input: {str(e)}"
        logger.warning(f"[AssetSummary] ✗ {error_msg}")
        raise HTTPException(status_code=400, detail=error_msg)
    except RuntimeError as e:
        error_msg = str(e)
        logger.error(f"[AssetSummary] ✗ Runtime error: {error_msg}")
        
        # Provide specific error details to help debugging
        if "HF_TOKEN" in error_msg:
            raise HTTPException(status_code=500, detail="HuggingFace API token not configured (HF_TOKEN missing)")
        elif "HF_ASSET_SUMMARIZATION_REPO" in error_msg:
            raise HTTPException(status_code=500, detail="Asset summary model repository not configured (HF_ASSET_SUMMARIZATION_REPO missing)")
        elif "HF API 401" in error_msg or "authentication" in error_msg.lower():
            raise HTTPException(status_code=401, detail="HuggingFace authentication failed - invalid API token")
        elif "HF API 404" in error_msg:
            raise HTTPException(status_code=404, detail="Asset summary model not found in HuggingFace repository")
        elif "HF API 429" in error_msg:
            raise HTTPException(status_code=429, detail="HuggingFace API rate limit exceeded - please retry later")
        elif "loading" in error_msg.lower() or "503" in error_msg:
            raise HTTPException(status_code=503, detail="Asset summary model is cold-starting - please retry in a few seconds")
        else:
            raise HTTPException(status_code=500, detail=f"Summary generation failed: {error_msg}")
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.error(f"[AssetSummary] ✗ {error_msg}")
        raise HTTPException(status_code=500, detail=error_msg)


@router.get("/health")
async def health_check():
    """Check if asset summary model is loaded and accessible"""
    try:
        logger.info("[AssetSummary] Health check started...")
        
        # Check if credentials are set
        try:
            token, repo = get_hf_credentials()
            has_token = bool(token)
            has_repo = bool(repo)
        except Exception as e:
            return {
                "status": "error",
                "model_loaded": False,
                "message": str(e),
                "details": {
                    "has_token": False,
                    "has_repo": False,
                    "error": "Credentials not properly configured"
                }
            }
        
        # Check if model can be loaded
        try:
            from app.ai.services.asset_summary_service import get_asset_summary_model
            model = get_asset_summary_model()
            model_loaded = model is not None
            repo = get_asset_summary_repo()
            
            logger.info(f"[AssetSummary] Health check: model={model_loaded}, repo={repo}")
            
            return {
                "status": "ok" if model_loaded else "warning",
                "model_loaded": model_loaded,
                "message": "Asset summary model is ready" if model_loaded else "Model initialized but not yet warmed up",
                "details": {
                    "has_token": has_token,
                    "has_repo": has_repo,
                    "repo": repo,
                    "model_loaded": model_loaded
                }
            }
        except Exception as e:
            logger.error(f"[AssetSummary] Health check failed: {e}")
            return {
                "status": "error",
                "model_loaded": False,
                "message": f"Model loading failed: {str(e)}",
                "details": {
                    "has_token": has_token,
                    "has_repo": has_repo,
                    "error": str(e)
                }
            }
    except Exception as e:
        logger.error(f"[AssetSummary] Health check exception: {e}")
        return {
            "status": "error",
            "model_loaded": False,
            "message": f"Health check failed: {str(e)}"
        }
