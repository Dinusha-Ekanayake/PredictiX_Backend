"""
app/services/report_service.py

Full pipeline:
  context_builder → AIInsightService → PDFRenderService → Supabase Storage → Report row saved

Used by app/routers/asset_reports.py.
"""

import uuid
import os
from uuid import UUID
from datetime import datetime, timezone

from fastapi import HTTPException
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv(override=True)

from app.services.context_builder import AssetContextBuilder
from app.services.ai_insight import AIInsightService
from app.services.pdf_render import PDFRenderService
from app.core.storage import supabase_storage


def _get_supabase() -> Client:
    return create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))


class ReportService:
    def __init__(self, db=None):
        # db param kept for backwards compatibility — not used
        self.supabase        = _get_supabase()
        self.context_builder = AssetContextBuilder(db)
        self.ai_insight      = AIInsightService()
        self.pdf_render      = PDFRenderService()

    def generate_asset_report(self, asset_id: UUID, user_id: UUID = None) -> str:
        """
        Full pipeline:
          1. Build context  (Supabase REST via AssetContextBuilder)
          2. AI insights    (Groq LLM via AIInsightService)
          3. Render PDF     (reportlab via PDFRenderService)
          4. Upload PDF     (Supabase Storage)
          5. Save Report    (insert row into reports table via Supabase REST)
          6. Return public URL
        """
        # ── 1. Build context ──────────────────────────────
        context = self.context_builder.build_context(asset_id)

        # ── 2. AI insights ────────────────────────────────
        try:
            insights = self.ai_insight.generate_insights(context)
        except Exception as e:
            insights = {
                "executive_summary":      f"AI insight generation failed: {e}",
                "maintenance_insights":   [],
                "recommendations":        {},
                "cost_analysis":          {},
                "future_predictions":     {},
                "operational_efficiency": {},
                "conclusion":             "See maintenance and sensor data above for asset status.",
            }

        # ── 3. Render PDF ─────────────────────────────────
        report_id = uuid.uuid4()
        pdf_path  = self.pdf_render.generate_pdf(context, insights, report_id)

        try:
            # ── 4. Upload to Supabase Storage ─────────────
            bucket_name = "reports"
            file_name   = f"asset_{asset_id}_{report_id}.pdf"

            public_url = supabase_storage.upload_file(
                bucket=bucket_name,
                file_path=pdf_path,
                destination_path=file_name,
            )

            # ── 5. Record in reports table via Supabase REST ──
            asset_name = context["asset"].get("asset_name", "Asset")
            report_row = {
                "id":                       str(report_id),
                "report_type":              "asset_report",
                "status":                   "generated",
                "asset_id":                 str(asset_id),
                "title":                    f"Asset Performance Report — {asset_name}",
                "generated_by":             str(user_id) if user_id else None,
                "file_path":                public_url,
                "report_json":              {
                    "metrics":  context["metrics"],
                    "insights": {
                        k: v for k, v in insights.items()
                        if k in ("executive_summary", "recommendations", "conclusion")
                    },
                },
                "generation_completed_at":  datetime.now(timezone.utc).isoformat(),
            }

            try:
                self.supabase.table("reports").insert(report_row).execute()
            except Exception as db_err:
                # Log but don't fail — PDF was generated and uploaded successfully
                print(f"[report_service] WARNING: Could not save report row to DB: {db_err}")

            return public_url, pdf_path

        except Exception as e:
            # Clean up local PDF on failure
            if pdf_path and os.path.exists(pdf_path):
                os.remove(pdf_path)
            raise e