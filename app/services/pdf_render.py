"""
app/services/pdf_render.py

Generates a multi-page PDF Asset Performance Report using ReportLab.
Page 1: Fleet Overview with matplotlib charts
Page 2+: Asset-specific details
"""

import os
import uuid
import tempfile
import io
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, Image, PageBreak, KeepTogether,
)

from app.services.pdf_styles import (
    COLORS, get_styles, section_divider, thin_divider,
    data_table_style, kpi_card_style, info_grid_style,
    risk_color, risk_style_key,
)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np


# ─────────────────────────────────────────────────────────
#  Chart helpers
# ─────────────────────────────────────────────────────────

def _pie_chart(labels, values, colors_hex, title="", size=(3.2, 2.8)) -> Image:
    fig, ax = plt.subplots(figsize=size, facecolor="none")
    wedge_colors = [c for c in colors_hex]
    wedges, texts, autotexts = ax.pie(
        values, labels=None, colors=wedge_colors,
        autopct=lambda p: f"{p:.0f}%" if p > 4 else "",
        startangle=90, pctdistance=0.75,
        wedgeprops=dict(linewidth=1.5, edgecolor="white"),
    )
    for at in autotexts:
        at.set_fontsize(7)
        at.set_color("white")
        at.set_fontweight("bold")
    if title:
        ax.set_title(title, fontsize=9, fontweight="bold", color="#1e293b", pad=6)
    ax.axis("equal")

    legend = ax.legend(
        wedges, [f"{l} ({v})" for l, v in zip(labels, values)],
        loc="lower center", bbox_to_anchor=(0.5, -0.22),
        ncol=2, fontsize=6.5, frameon=False,
        labelcolor="#1e293b",
    )

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                facecolor="none", transparent=True)
    plt.close(fig)
    buf.seek(0)
    img = Image(buf)
    img.drawWidth  = size[0] * cm * 1.1
    img.drawHeight = size[1] * cm * 1.1
    return img


def _bar_chart(labels, values, color_hex="#0f766e", title="", size=(6.5, 2.8)) -> Image:
    fig, ax = plt.subplots(figsize=size, facecolor="none")
    x = np.arange(len(labels))
    bars = ax.bar(x, values, color=color_hex, edgecolor="white", linewidth=0.8, width=0.6)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=6.5, color="#1e293b")
    ax.set_yticks([])
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="x", length=0)
    for bar in bars:
        h = bar.get_height()
        ax.text(bar.get_x() + bar.get_width() / 2, h + max(values) * 0.02,
                str(int(h)), ha="center", va="bottom", fontsize=6, color="#1e293b")
    if title:
        ax.set_title(title, fontsize=9, fontweight="bold", color="#1e293b", pad=6)
    ax.set_facecolor("none")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                facecolor="none", transparent=True)
    plt.close(fig)
    buf.seek(0)
    img = Image(buf)
    img.drawWidth  = size[0] * cm
    img.drawHeight = size[1] * cm
    return img


# ─────────────────────────────────────────────────────────
#  Page header / footer callbacks
# ─────────────────────────────────────────────────────────

def _make_header_footer(asset_name: str, report_id: str, generated_date: str):
    def on_page(canvas, doc):
        canvas.saveState()
        W, H = A4
        # Header bar
        canvas.setFillColor(COLORS.TEAL)
        canvas.rect(0, H - 1.1 * cm, W, 1.1 * cm, fill=1, stroke=0)
        canvas.setFillColor(COLORS.WHITE)
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawString(1 * cm, H - 0.75 * cm, "PredictiX — Asset Performance Report")
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(W - 1 * cm, H - 0.75 * cm, asset_name)
        # Footer
        canvas.setFillColor(COLORS.TEXT_MUTED)
        canvas.setFont("Helvetica-Oblique", 7)
        canvas.drawString(1 * cm, 0.6 * cm,
            f"Generated: {generated_date}  |  Report ID: {report_id}  |  Confidential — LankaLogix")
        canvas.drawRightString(W - 1 * cm, 0.6 * cm, f"Page {doc.page}")
        canvas.restoreState()
    return on_page


# ─────────────────────────────────────────────────────────
#  Main service
# ─────────────────────────────────────────────────────────

class PDFRenderService:

    def generate_pdf(self, context: dict, insights: dict, report_id: uuid.UUID) -> str:
        out_path = os.path.join(tempfile.gettempdir(), f"asset_report_{report_id}.pdf")
        styles   = get_styles()
        asset    = context.get("asset", {})
        metrics  = context.get("metrics", {})
        fleet    = context.get("fleet", {})
        sensor   = context.get("sensor", {})
        maintenance = context.get("maintenance", [])
        tickets     = context.get("tickets", [])
        gen_date    = context.get("generated_date", datetime.now().strftime("%B %d, %Y"))
        rpt_id      = context.get("report_id", str(report_id)[:8].upper())
        asset_name  = asset.get("asset_name", "Asset Report")

        doc = SimpleDocTemplate(
            out_path, pagesize=A4,
            topMargin=1.4 * cm, bottomMargin=1.2 * cm,
            leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        )

        story = []
        cb = _make_header_footer(asset_name, rpt_id, gen_date)

        # ══════════════════════════════════════════════════
        #  PAGE 1 — Fleet Overview
        # ══════════════════════════════════════════════════
        story += self._fleet_page(fleet, styles, gen_date, asset_name)
        story.append(PageBreak())

        # ══════════════════════════════════════════════════
        #  PAGE 2+ — Asset Details
        # ══════════════════════════════════════════════════
        story += self._asset_cover(asset, metrics, gen_date, rpt_id, styles)
        story += self._section_asset_overview(asset, styles)
        story += self._section_health_risk(metrics, styles)
        story += self._section_sensor(sensor, styles)
        story += self._section_maintenance(maintenance, metrics, styles)
        story += self._section_tickets(tickets, metrics, styles)
        story += self._section_ai_insights(insights, styles)

        doc.build(story, onFirstPage=cb, onLaterPages=cb)
        return out_path

    # ─────────────────────────────────────────────────────
    #  PAGE 1 BUILDER
    # ─────────────────────────────────────────────────────
    def _fleet_page(self, fleet: dict, styles: dict, gen_date: str, asset_name: str) -> list:
        story = []

        # Title
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph("Fleet Overview Dashboard", styles["cover_title"]))
        story.append(Paragraph(f"LankaLogix · {gen_date}", styles["cover_subtitle"]))
        story.append(section_divider())
        story.append(Spacer(1, 0.3 * cm))

        # ── KPI strip ──
        total   = fleet.get("total_assets", 0)
        health  = fleet.get("fleet_health", 0)
        crit    = fleet.get("critical_alerts", 0)
        open_t  = fleet.get("open_tickets", 0)
        high_t  = fleet.get("high_priority_tickets", 0)
        pred_f  = fleet.get("predicted_failures", 0)
        est_c   = fleet.get("est_maintenance_cost", 0)

        def kpi(label, value):
            return [Paragraph(str(value), styles["kpi_value"]),
                    Paragraph(label, styles["kpi_label"])]

        kpi_data = [[
            kpi("Total Assets",        total),
            kpi("Fleet Health %",      f"{health}%"),
            kpi("Critical Alerts",     crit),
            kpi("Open Tickets",        open_t),
            kpi("High Priority",       high_t),
            kpi("Pred. Failures",      pred_f),
            kpi("Est. Cost (LKR)",     f"{est_c:,.0f}"),
        ]]
        kpi_tbl = Table(kpi_data, colWidths=[2.4 * cm] * 7)
        kpi_tbl.setStyle(TableStyle(kpi_card_style()))
        story.append(kpi_tbl)
        story.append(Spacer(1, 0.5 * cm))

        # ── Charts row 1: Status Pie + Health Band Pie ──
        status_dist = fleet.get("status_distribution", [])
        health_dist = fleet.get("health_distribution", [])

        chart_row = []

        if status_dist:
            s_labels = [d["name"] for d in status_dist]
            s_values = [d["count"] for d in status_dist]
            s_colors = ["#10b981", "#ef4444", "#f59e0b", "#6366f1", "#94a3b8"][:len(s_labels)]
            chart_row.append(
                _pie_chart(s_labels, s_values, s_colors, title="Asset Status Distribution")
            )
        else:
            chart_row.append(Spacer(1, 1))

        if health_dist:
            h_labels = [d["name"] for d in health_dist]
            h_values = [d["count"] for d in health_dist]
            h_colors = ["#10b981", "#22d3ee", "#f59e0b", "#f97316", "#ef4444"][:len(h_labels)]
            chart_row.append(
                _pie_chart(h_labels, h_values, h_colors, title="Health Band Distribution")
            )
        else:
            chart_row.append(Spacer(1, 1))

        chart_tbl = Table([chart_row], colWidths=[8.5 * cm, 8.5 * cm])
        chart_tbl.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(chart_tbl)
        story.append(Spacer(1, 0.4 * cm))

        # ── Bar chart: Vehicle Type Distribution ──
        vehicle_dist = fleet.get("vehicle_distribution", [])
        if vehicle_dist:
            v_labels = [d["name"].replace("_", " ") for d in vehicle_dist]
            v_values = [d["count"] for d in vehicle_dist]
            bar = _bar_chart(v_labels, v_values, color_hex="#0f766e",
                             title="Assets by Vehicle Type", size=(15 * cm / 2.54, 2.8))
            bar.drawWidth  = 15 * cm
            bar.drawHeight = 5.5 * cm
            story.append(bar)
            story.append(Spacer(1, 0.4 * cm))

        # ── Top At-Risk Assets table ──
        top_risk = fleet.get("top_risk_assets", [])
        if top_risk:
            story.append(thin_divider())
            story.append(Paragraph("Top At-Risk Assets", styles["subsection"]))
            story.append(Spacer(1, 0.2 * cm))
            risk_data = [[
                Paragraph("Asset", styles["table_header"]),
                Paragraph("Location", styles["table_header"]),
                Paragraph("Health", styles["table_header"]),
                Paragraph("Fail Prob.", styles["table_header"]),
                Paragraph("Days to Maint.", styles["table_header"]),
            ]]
            for r in top_risk:
                fp = r.get("failureProbability", 0)
                hs = r.get("healthScore", 0)
                dtm = r.get("daysToMaintenance", 0)
                risk_data.append([
                    Paragraph(str(r.get("name", "—")), styles["table_cell"]),
                    Paragraph(str(r.get("location", "—")), styles["table_cell"]),
                    Paragraph(f"{hs}%", styles[risk_style_key("critical" if hs < 30 else "high")]),
                    Paragraph(f"{fp * 100:.1f}%", styles["table_cell"]),
                    Paragraph(str(dtm) if dtm is not None else "—", styles["table_cell"]),
                ])
            risk_tbl = Table(risk_data, colWidths=[5.5 * cm, 4 * cm, 2 * cm, 2.5 * cm, 3 * cm])
            risk_tbl.setStyle(TableStyle(data_table_style()))
            story.append(risk_tbl)

        return story

    # ─────────────────────────────────────────────────────
    #  ASSET COVER
    # ─────────────────────────────────────────────────────
    def _asset_cover(self, asset, metrics, gen_date, rpt_id, styles) -> list:
        story = [Spacer(1, 0.3 * cm)]
        story.append(Paragraph("Asset Performance Report", styles["cover_title"]))
        story.append(Paragraph(
            f"{asset.get('asset_name', '—')}  ·  {asset.get('asset_code', '—')}",
            styles["cover_subtitle"],
        ))
        story.append(Paragraph(
            f"Generated: {gen_date}  |  Report ID: {rpt_id}  |  Warehouse: {asset.get('warehouse', '—')}",
            styles["cover_meta"],
        ))
        story.append(section_divider())
        story.append(Spacer(1, 0.4 * cm))

        # KPI strip
        currency = metrics.get("currency", "LKR")
        def kpi(label, value):
            return [Paragraph(str(value), styles["kpi_value"]),
                    Paragraph(label, styles["kpi_label"])]

        kpi_data = [[
            kpi("Health Score",         f"{metrics.get('health_score', '—')}%"),
            kpi("Failure Prob.",        f"{metrics.get('failure_probability', '—')}%"),
            kpi("Risk Level",           metrics.get("risk_level", "—")),
            kpi("Open Tickets",         metrics.get("open_tickets", "—")),
            kpi("Maint. Events",        metrics.get("total_events", "—")),
            kpi(f"Est. Cost ({currency})", f"{metrics.get('estimated_cost', 0):,.0f}"),
        ]]
        kpi_tbl = Table(kpi_data, colWidths=[2.8 * cm] * 6)
        kpi_tbl.setStyle(TableStyle(kpi_card_style()))
        story.append(kpi_tbl)
        story.append(Spacer(1, 0.4 * cm))
        return story

    # ─────────────────────────────────────────────────────
    #  SECTION: Asset Overview
    # ─────────────────────────────────────────────────────
    def _section_asset_overview(self, asset, styles) -> list:
        story = [Paragraph("1. Asset Overview", styles["section"]), section_divider()]
        left = [
            ["Asset Name",    asset.get("asset_name", "—")],
            ["Asset Code",    asset.get("asset_code", "—")],
            ["Type",          f"{asset.get('asset_type','—')} · {asset.get('vehicle_type','—')}"],
            ["Make / Model",  f"{asset.get('make','—')} {asset.get('model','—')} {asset.get('manufacture_year','—')}"],
            ["Status",        asset.get("status", "—")],
            ["Health Band",   asset.get("health_band", "—")],
        ]
        right = [
            ["Registration",  asset.get("registration_number", "—")],
            ["VIN",           asset.get("vin", "—")],
            ["Purchase Date", asset.get("purchase_date", "—")],
            ["Warranty Exp.", asset.get("warranty_expiry_date", "—")],
            ["Last Service",  asset.get("last_service_date", "—")],
            ["Next Service",  asset.get("next_service_date", "—")],
        ]
        rows = max(len(left), len(right))
        tbl_data = []
        for i in range(rows):
            l = left[i]  if i < len(left)  else ["", ""]
            r = right[i] if i < len(right) else ["", ""]
            tbl_data.append([
                Paragraph(l[0], styles["small"]),
                Paragraph(str(l[1]), styles["normal_bold"]),
                Paragraph(r[0], styles["small"]),
                Paragraph(str(r[1]), styles["normal_bold"]),
            ])
        tbl = Table(tbl_data, colWidths=[3.5 * cm, 5 * cm, 3.5 * cm, 5 * cm])
        tbl.setStyle(TableStyle(info_grid_style()))
        story += [tbl, Spacer(1, 0.5 * cm)]
        return story

    # ─────────────────────────────────────────────────────
    #  SECTION: Health & Risk
    # ─────────────────────────────────────────────────────
    def _section_health_risk(self, metrics, styles) -> list:
        story = [Paragraph("2. Health & Risk Analysis", styles["section"]), section_divider()]
        hs  = metrics.get("health_score", 0)
        fp  = metrics.get("failure_probability", 0)
        rl  = metrics.get("risk_level", "—")
        dtm = metrics.get("days_until_maintenance")
        pmd = metrics.get("predicted_maintenance_date", "—")

        data = [
            ["Health Score",             f"{hs}%"],
            ["Failure Probability",      f"{fp}%"],
            ["Risk Level",               rl],
            ["Days Until Maintenance",   str(dtm) if dtm is not None else "—"],
            ["Predicted Maint. Date",    pmd],
        ]
        tbl_data = [[
            Paragraph(r[0], styles["small"]),
            Paragraph(r[1], styles[risk_style_key(rl.lower()) if r[0] == "Risk Level" else "normal_bold"]),
        ] for r in data]
        tbl = Table(tbl_data, colWidths=[6 * cm, 11 * cm])
        tbl.setStyle(TableStyle(info_grid_style()))
        story += [tbl, Spacer(1, 0.5 * cm)]
        return story

    # ─────────────────────────────────────────────────────
    #  SECTION: Sensor Data
    # ─────────────────────────────────────────────────────
    def _section_sensor(self, sensor, styles) -> list:
        if not sensor:
            return []
        story = [Paragraph("3. Latest Sensor Snapshot", styles["section"]), section_divider()]
        fields = [
            ("Recorded At",             sensor.get("recorded_at")),
            ("Tire Health",             f"{sensor.get('tire_health_pct','—')}%"),
            ("Brake Health",            f"{sensor.get('brake_health_pct','—')}%"),
            ("Battery Health",          f"{sensor.get('battery_health_pct','—')}%"),
            ("Oil Life",                f"{sensor.get('oil_life_pct','—')}%"),
            ("Hydraulic Health",        f"{sensor.get('hydraulic_health_pct','—')}%"),
            ("Coolant Temp Max (°C)",   sensor.get("coolant_temp_max_c")),
            ("Engine Temp Avg (°C)",    sensor.get("engine_temp_avg_c")),
            ("Active Fault Codes",      sensor.get("active_fault_code_count")),
            ("Days Since Service",      sensor.get("days_since_last_service")),
            ("Engine Hours",            sensor.get("engine_hours_since_last_service")),
            ("Downtime Last 90d (h)",   sensor.get("downtime_hours_last_90d")),
            ("Fuel Level",              f"{sensor.get('fuel_level','—')}%"),
            ("Odometer (km)",           sensor.get("odometer_km")),
        ]
        left  = fields[:7]
        right = fields[7:]
        rows  = max(len(left), len(right))
        tbl_data = []
        for i in range(rows):
            l = left[i]  if i < len(left)  else ("", "")
            r = right[i] if i < len(right) else ("", "")
            tbl_data.append([
                Paragraph(l[0], styles["small"]),
                Paragraph(str(l[1] or "—"), styles["normal_bold"]),
                Paragraph(r[0], styles["small"]),
                Paragraph(str(r[1] or "—"), styles["normal_bold"]),
            ])
        tbl = Table(tbl_data, colWidths=[3.5 * cm, 5 * cm, 3.5 * cm, 5 * cm])
        tbl.setStyle(TableStyle(info_grid_style()))
        story += [tbl, Spacer(1, 0.5 * cm)]
        return story

    # ─────────────────────────────────────────────────────
    #  SECTION: Maintenance
    # ─────────────────────────────────────────────────────
    def _section_maintenance(self, maintenance, metrics, styles) -> list:
        story = [Paragraph("4. Maintenance Summary", styles["section"]), section_divider()]
        currency = metrics.get("currency", "LKR")
        summary_data = [
            ["Total Events",        str(metrics.get("total_events", 0))],
            ["Preventive",          f"{metrics.get('preventive_count',0)} ({metrics.get('preventive_ratio',0)}%)"],
            ["Corrective",          f"{metrics.get('corrective_count',0)} ({metrics.get('corrective_ratio',0)}%)"],
            ["Total Cost",          f"{currency} {metrics.get('total_cost',0):,.0f}"],
            ["Avg Cost/Event",      f"{currency} {metrics.get('avg_cost_per_event',0):,.0f}"],
            ["Total Downtime (h)",  str(metrics.get("total_downtime_hours", 0))],
        ]
        tbl_data = [[Paragraph(r[0], styles["small"]), Paragraph(r[1], styles["normal_bold"])]
                    for r in summary_data]
        tbl = Table(tbl_data, colWidths=[6 * cm, 11 * cm])
        tbl.setStyle(TableStyle(info_grid_style()))
        story.append(tbl)

        if maintenance:
            story.append(Spacer(1, 0.3 * cm))
            story.append(Paragraph("Recent Maintenance Events", styles["subsection"]))
            rows = [[
                Paragraph("Date",        styles["table_header"]),
                Paragraph("Type",        styles["table_header"]),
                Paragraph("Description", styles["table_header"]),
                Paragraph("Cost (LKR)",  styles["table_header"]),
                Paragraph("Downtime",    styles["table_header"]),
            ]]
            for m in maintenance[:8]:
                rows.append([
                    Paragraph(str(m.get("performed_at","—"))[:10], styles["table_cell"]),
                    Paragraph(str(m.get("event_type","—")),         styles["table_cell"]),
                    Paragraph(str(m.get("description","—"))[:60],   styles["table_cell"]),
                    Paragraph(f"{m.get('cost_amount',0):,.0f}",      styles["table_cell"]),
                    Paragraph(f"{m.get('downtime_hours','—')}h",     styles["table_cell"]),
                ])
            mt = Table(rows, colWidths=[2.5*cm, 2.5*cm, 6*cm, 2.5*cm, 2*cm])
            mt.setStyle(TableStyle(data_table_style()))
            story.append(mt)

        story.append(Spacer(1, 0.5 * cm))
        return story

    # ─────────────────────────────────────────────────────
    #  SECTION: Tickets
    # ─────────────────────────────────────────────────────
    def _section_tickets(self, tickets, metrics, styles) -> list:
        story = [Paragraph("5. Ticket Summary", styles["section"]), section_divider()]
        summary = [
            ["Total Tickets",   str(metrics.get("total_tickets", 0))],
            ["Open",            str(metrics.get("open_tickets", 0))],
            ["High Priority",   str(metrics.get("high_priority_tickets", 0))],
            ["Closed",          str(metrics.get("closed_tickets", 0))],
        ]
        tbl_data = [[Paragraph(r[0], styles["small"]), Paragraph(r[1], styles["normal_bold"])]
                    for r in summary]
        tbl = Table(tbl_data, colWidths=[6 * cm, 11 * cm])
        tbl.setStyle(TableStyle(info_grid_style()))
        story.append(tbl)

        if tickets:
            story.append(Spacer(1, 0.3 * cm))
            story.append(Paragraph("Recent Tickets", styles["subsection"]))
            rows = [[
                Paragraph("ID",       styles["table_header"]),
                Paragraph("Title",    styles["table_header"]),
                Paragraph("Priority", styles["table_header"]),
                Paragraph("Status",   styles["table_header"]),
                Paragraph("Created",  styles["table_header"]),
            ]]
            for t in tickets[:8]:
                pri = str(t.get("priority","—")).lower()
                rows.append([
                    Paragraph(str(t.get("ticket_number","—")),    styles["table_cell"]),
                    Paragraph(str(t.get("title","—"))[:55],        styles["table_cell"]),
                    Paragraph(str(t.get("priority","—")).title(),  styles[risk_style_key(pri)]),
                    Paragraph(str(t.get("status","—")).title(),    styles["table_cell"]),
                    Paragraph(str(t.get("created_at","—"))[:10],   styles["table_cell"]),
                ])
            tt = Table(rows, colWidths=[2.5*cm, 6.5*cm, 2.2*cm, 2.3*cm, 2.5*cm])
            tt.setStyle(TableStyle(data_table_style()))
            story.append(tt)

        story.append(Spacer(1, 0.5 * cm))
        return story

    # ─────────────────────────────────────────────────────
    #  SECTION: AI Insights
    # ─────────────────────────────────────────────────────
    def _section_ai_insights(self, insights, styles) -> list:
        story = [Paragraph("6. AI Insights & Recommendations", styles["section"]), section_divider()]

        if insights.get("executive_summary"):
            story.append(Paragraph("Executive Summary", styles["subsection"]))
            story.append(Paragraph(insights["executive_summary"], styles["normal"]))
            story.append(Spacer(1, 0.3 * cm))

        recs = insights.get("recommendations", {})
        for level in ("critical", "high", "medium"):
            items = recs.get(level, [])
            if items:
                story.append(Paragraph(f"{level.title()} Recommendations", styles["subsection"]))
                for item in items:
                    story.append(Paragraph(f"• {item}", styles["bullet"]))
                story.append(Spacer(1, 0.2 * cm))

        if insights.get("conclusion"):
            story.append(thin_divider())
            story.append(Paragraph("Conclusion", styles["subsection"]))
            story.append(Paragraph(insights["conclusion"], styles["normal"]))

        return story