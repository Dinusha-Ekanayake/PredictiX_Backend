from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer,
    Table, TableStyle, PageBreak
)
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import inch
from app.services.pdf_styles import get_styles, section_divider
from sqlalchemy.orm import Session
from uuid import UUID, uuid4
from datetime import datetime
import os
from app.repositories.asset_report_repo import AssetReportRepository
from app.services.pdf_render import PDFRenderService
from app.core.storage import supabase_storage 
from app.models import Report 

def create_kpi_cards(context):

    data = [
        ["Failure Probability", f"{context['health_metrics']['failure_probability']}%"],
        ["Total Events", context["maintenance_metrics"]["total_events"]],
        ["Preventive Ratio", f"{context['maintenance_metrics']['preventive_ratio']}%"],
        ["Open Tickets", context["ticket_metrics"]["open_tickets"]],
    ]

    table = Table(data, colWidths=[250, 200])

    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("PADDING", (0, 0), (-1, -1), 10),
    ]))

    return table


def generate_asset_pdf(data):

    doc = SimpleDocTemplate("asset_report.pdf", pagesize=A4)
    elements = []
    styles = get_styles()

    context = data["context"]
    ai = data["ai"]

    # ✅ COVER
    elements.append(Paragraph("PredictiX", styles["title"]))
    elements.append(Spacer(1, 0.3 * inch))
    elements.append(Paragraph("Asset Performance Report", styles["section"]))
    elements.append(section_divider())
    elements.append(PageBreak())

    # ✅ EXECUTIVE SUMMARY
    elements.append(Paragraph("1. Executive Summary", styles["section"]))
    elements.append(section_divider())
    elements.append(create_kpi_cards(context))
    elements.append(Spacer(1, 0.3 * inch))
    elements.append(Paragraph(ai["executive_summary"], styles["normal"]))
    elements.append(PageBreak())

    # ✅ RECOMMENDATIONS
    elements.append(Paragraph("2. Recommendations", styles["section"]))
    elements.append(section_divider())

    for level, items in ai["recommendations"].items():

        elements.append(Paragraph(level.upper(), styles["section"]))

        for item in items:
            if level == "critical":
                style = styles["critical"]
            elif level == "high":
                style = styles["high"]
            else:
                style = styles["medium"]

            elements.append(Paragraph(f"• {item}", style))

        elements.append(Spacer(1, 0.2 * inch))

    elements.append(PageBreak())

    # ✅ CONCLUSION
    elements.append(Paragraph("3. Conclusion", styles["section"]))
    elements.append(section_divider())
    elements.append(Paragraph(ai["conclusion"], styles["normal"]))

    doc.build(elements)

    return "asset_report.pdf"

class ReportService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = AssetReportRepository(db)
        self.pdf_service = PDFRenderService()

    def generate_asset_report(self, asset_id: UUID, user_id: UUID = None) -> str:
        """
        1. Fetch data from DB
        2. Generate PDF
        3. Upload to Supabase Storage
        4. Save Report record
        5. Return Public URL
        """
        # 1. Fetch Data
        data = self.repo.get_asset_report_data(asset_id)
        context = data["context"]
        insights = data["insights"]
        report_id = uuid4()

        # 2. Generate PDF
        pdf_path = self.pdf_service.generate_pdf(
            context=context,
            insights=insights,
            report_id=report_id
        )

        try:
            # 3. Upload to Supabase
            bucket_name = "reports"
            file_name = f"asset_{asset_id}_{report_id}.pdf"
            
            # Assuming supabase_storage.upload_file exists in core/storage.py
            public_url = supabase_storage.upload_file(
                bucket=bucket_name,
                file_path=pdf_path,
                destination_path=file_name
            )

            # 4. Save to DB
            report = Report(
                id=report_id,
                report_type="asset_detail",
                asset_id=asset_id,
                title=f"Asset Report - {context['asset_name']}",
                generated_by=user_id,
                status="completed",
                file_path=public_url,
                report_json={"context": context, "insights": insights},
                generation_completed_at=datetime.utcnow()
            )
            self.db.add(report)
            self.db.commit()
            self.db.refresh(report)

            return public_url

        finally:
            # Cleanup temp file
            if os.path.exists(pdf_path):
                os.remove(pdf_path)