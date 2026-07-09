from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.deps import get_db, require_admin, require_user
from app.models import Asset, Profile, Report, Ticket, Warehouse
from app.schemas.report import ReportCreate, ReportUpdate, ReportOut

router = APIRouter(
    prefix="/reports",
    tags=["Reports"],
    dependencies=[Depends(require_user)],
)


@router.post("/", response_model=ReportOut)
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


@router.get("/", response_model=list[ReportOut])
def list_reports(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return db.query(Report).order_by(Report.created_at.desc()).offset(offset).limit(limit).all()


@router.get("/{report_id}", response_model=ReportOut)
def get_report(report_id: str, db: Session = Depends(get_db)):
    obj = db.query(Report).filter(Report.id == report_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Report not found")
    return obj


@router.put("/{report_id}", response_model=ReportOut)
def update_report(report_id: str, payload: ReportUpdate, db: Session = Depends(get_db)):
    obj = db.query(Report).filter(Report.id == report_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Report not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, key, value)

    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{report_id}", dependencies=[Depends(require_admin)])
def delete_report(report_id: str, db: Session = Depends(get_db)):
    obj = db.query(Report).filter(Report.id == report_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Report not found")
    db.delete(obj)
    db.commit()
    return {"message": "Report deleted"}