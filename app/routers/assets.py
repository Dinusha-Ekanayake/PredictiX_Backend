from fastapi import APIRouter

router = APIRouter(prefix="/assets", tags=["Assets"])


@router.get("/test")
def test_assets():
    return {"message": "Assets working"}