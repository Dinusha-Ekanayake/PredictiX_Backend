from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.deps import get_db, require_user
from app.models import ReportSource
from app.schemas.misc import ReportSourceCreate, ReportSourceOut

router = APIRouter(
    prefix="/report-sources",
    tags=["Report Sources"],
    dependencies=[Depends(require_user)],
)


@router.post("/", response_model=ReportSourceOut)
def create_report_source(payload: ReportSourceCreate, db: Session = Depends(get_db)):
    obj = ReportSource(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/", response_model=list[ReportSourceOut])
def list_report_sources(
    report_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(ReportSource)
    if report_id:
        q = q.filter(ReportSource.report_id == report_id)
    return q.order_by(ReportSource.created_at.desc()).all()