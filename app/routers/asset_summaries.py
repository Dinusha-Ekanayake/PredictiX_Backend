from fastapi import APIRouter, HTTPException
from datetime import datetime
import logging

from app.schemas.asset_summary import AssetSummaryRequest, AssetSummaryResponse
from app.ai.services.asset_summary_service import generate_asset_summary, get_asset_summary_repo, get_hf_credentials

logger = logging.getLogger(__name__)

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
