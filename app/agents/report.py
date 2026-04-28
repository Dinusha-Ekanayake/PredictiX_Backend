from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.agents.asset_agent import run_asset_agent
from app.services.pdf_service import generate_pdf

router = APIRouter()

@router.get("/asset-report/{asset_id}")
def generate_asset_report(asset_id: int, db: Session = Depends(get_db)):
    result = run_asset_agent(db, asset_id)

    pdf_file = generate_asset_pdf(result)

    return FileResponse(
        path=pdf_file,
        media_type="application/pdf",
        filename="asset_report.pdf"
    )
    


import pdfkit
from jinja2 import Environment, FileSystemLoader
import os

def generate_asset_pdf(data):

    env = Environment(loader=FileSystemLoader("app/templates"))
    template = env.get_template("asset_report.html")

    html_content = template.render(
        context=data["context"],
        ai=data["ai"]
    )

    output_path = "asset_report.pdf"

    # IMPORTANT for Mac path
    config = pdfkit.configuration(
        wkhtmltopdf="/opt/homebrew/bin/wkhtmltopdf"
    )

    pdfkit.from_string(
        html_content,
        output_path,
        configuration=config
    )

    return output_path

