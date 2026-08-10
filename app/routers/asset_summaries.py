from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from datetime import datetime
from uuid import UUID
import logging

from app.schemas.asset_summary import AssetSummaryRequest, AssetSummaryResponse
from app.ai.services.asset_summary_service import generate_asset_summary, get_asset_summary_repo
from app.deps import (
    get_db,
    require_user,
    require_admin,
    get_current_user,
    is_admin_role,
    assert_asset_in_scope,
    user_can_view_asset,
)
from app.models import Asset, AssetFailurePrediction, Profile

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/asset-summaries",
    tags=["Asset Summaries"],
    dependencies=[Depends(require_user)],
)


def _build_asset_input_text(asset: Asset, prediction: AssetFailurePrediction | None = None) -> str:
    """Build the pipe-separated input text for the asset summary model.

    Combines static asset attributes with the latest AI prediction signals
    (health score, failure probability, risk, days-to-service) so the summary
    reflects the asset's real current condition — the same numbers shown in the
    warehouse/asset tables.
    """
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

    # ── Latest AI prediction signals (health %, failure probability, risk, days-to-service) ──
    if prediction is not None:
        if prediction.health_score is not None:
            parts.append(f"Health score: {int(round(float(prediction.health_score)))}%")
        if prediction.failure_probability is not None:
            fp = float(prediction.failure_probability)
            fp_pct = fp * 100 if fp <= 1 else fp   # accept 0-1 or 0-100 storage
            parts.append(f"Failure probability: {round(fp_pct, 1)}%")
        if prediction.risk_level:
            parts.append(f"Risk: {prediction.risk_level}")
        if prediction.days_until_maintenance is not None:
            d = int(prediction.days_until_maintenance)
            parts.append(f"Service due in: {d} day" + ("" if d == 1 else "s"))

    return " | ".join(parts)


def _latest_prediction(db: Session, asset_id) -> AssetFailurePrediction | None:
    """Most-recent failure prediction for an asset (drives the summary's health signals)."""
    return (
        db.query(AssetFailurePrediction)
        .filter(AssetFailurePrediction.asset_id == asset_id)
        .order_by(AssetFailurePrediction.created_at.desc())
        .first()
    )



@router.get("/by-asset/{asset_id}", response_model=AssetSummaryResponse)
async def get_summary_by_asset(
    asset_id: UUID,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    """
    Fetch an asset by its ID, auto-build the input text, and generate a summary.

    This is used by the ticket creation dialog to show asset context at a glance.
    """
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Previously had no current_user param at all — any authenticated
    # account of any role could pull an AI-generated summary (name, health
    # band, criticality, latest failure probability/risk) for any asset in
    # any warehouse.
    if is_admin_role(current_user):
        assert_asset_in_scope(asset, current_user)
    elif not user_can_view_asset(asset, current_user):
        raise HTTPException(status_code=404, detail="Asset not found")

    input_text = _build_asset_input_text(asset, _latest_prediction(db, asset.id))
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


@router.post("/generate", response_model=AssetSummaryResponse, dependencies=[Depends(require_admin)])
async def generate_summary(payload: AssetSummaryRequest):
    """
    Generate a summary for arbitrary asset/fleet text using the Seq2Seq model.

    This endpoint takes formatted, free-form input text — not tied to any
    specific asset a caller must own — and triggers real external HF
    inference, so it's admin-gated rather than any-authenticated-user like
    the rest of this router: a regular "user" account has no legitimate
    reason to call it directly (the warehouse report feature that uses it
    is itself admin-only), and without this gate any authenticated account
    could repeatedly trigger uncapped external-API cost with no rate limit.

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
    """Report which HF Space serves asset summaries (online inference)."""
    space = get_asset_summary_repo()
    return {
        "status": "ok" if space else "unconfigured",
        "space": space or None,
        "message": "Asset summaries served by HF Space" if space
        else "ASSET_SUMMARY_SPACE not set — deterministic fallback in use",
    }
