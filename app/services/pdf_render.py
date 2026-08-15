"""
app/services/pdf_render.py

Builds the full Asset Performance Report PDF using reportlab.
Visual style matches the PredictiX Warehouse AI Report:
  - Teal header bar + footer on every page
  - KPI stat cards (big teal number + muted label)
  - Section cards with teal left-border strip
  - Alternating-row data tables
  - Inline horizontal bar charts (drawn via Flowable)
  - 6 sections: Cover, Asset Overview, Sensor Health,
    Maintenance Analysis, Ticket Management, Predictions & Conclusion
"""

import os
import uuid
import tempfile
from datetime import datetime
from typing import Dict, Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, Flowable
)
from reportlab.pdfgen import canvas as rl_canvas

from app.services.pdf_styles import (
    COLORS, get_styles, section_divider, thin_divider,
    kpi_card_style, data_table_style, info_grid_style,
    risk_style_key, risk_color, health_band_color,
)
from app.services.health_bands import band_for

PAGE_W, PAGE_H = A4
MARGIN    = 15 * mm
CONTENT_W = PAGE_W - 2 * MARGIN


# ─────────────────────────────────────────────────────────
#  HEADER / FOOTER CANVAS
# ─────────────────────────────────────────────────────────
class _HFCanvas(rl_canvas.Canvas):
    def __init__(self, *args, **kwargs):
        self._asset_name = kwargs.pop("asset_name", "Asset Report")
        super().__init__(*args, **kwargs)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self._draw(total)
            rl_canvas.Canvas.showPage(self)
        rl_canvas.Canvas.save(self)

    def _draw(self, total):
        page = self._pageNumber
        if page > 1:
            # Teal header bar
            self.setFillColor(COLORS.TEAL)
            self.rect(0, PAGE_H - 17*mm, PAGE_W, 17*mm, fill=1, stroke=0)
            self.setFillColor(COLORS.TEAL_MID)
            self.rect(0, PAGE_H - 18.5*mm, PAGE_W, 1.5*mm, fill=1, stroke=0)
            # Brand left
            self.setFillColor(COLORS.TEXT_ON_TEAL)
            self.setFont("Helvetica-Bold", 12)
            self.drawString(MARGIN, PAGE_H - 10*mm, "PredictiX")
            # Asset name right
            self.setFont("Helvetica", 8.5)
            self.setFillColor(colors.HexColor("#a7f3d0"))
            self.drawRightString(PAGE_W - MARGIN, PAGE_H - 10*mm, self._asset_name)

        # Footer
        self.setFillColor(COLORS.SURFACE)
        self.rect(0, 0, PAGE_W, 11*mm, fill=1, stroke=0)
        self.setStrokeColor(COLORS.BORDER)
        self.setLineWidth(0.5)
        self.line(0, 11*mm, PAGE_W, 11*mm)
        self.setFont("Helvetica", 7.5)
        self.setFillColor(COLORS.TEXT_MUTED)
        self.drawString(MARGIN, 4*mm,
                        f"Generated: {datetime.now().strftime('%B %d, %Y  %H:%M')}  |  PredictiX AI Platform")
        self.drawRightString(PAGE_W - MARGIN, 4*mm, f"Page {page} of {total}")
        self.setFont("Helvetica-Oblique", 7)
        self.setFillColor(colors.HexColor("#94a3b8"))
        self.drawCentredString(PAGE_W / 2, 4*mm, "CONFIDENTIAL — Internal Use Only")


# ─────────────────────────────────────────────────────────
#  INLINE HORIZONTAL BAR CHART
# ─────────────────────────────────────────────────────────
class HBarChart(Flowable):
    """
    bars: list of (label, value, max_value, color)
    Renders as an inline horizontal bar chart.
    """
    def __init__(self, bars, bar_h=10, gap=4, lbl_w=130):
        super().__init__()
        self.bars  = bars
        self.bar_h = bar_h
        self.gap   = gap
        self.lbl_w = lbl_w
        self.val_w = 50
        self.width  = CONTENT_W
        self.height = len(bars) * (bar_h + gap) + 8

    def draw(self):
        c       = self.canv
        bar_area = self.width - self.lbl_w - self.val_w
        row_h   = self.bar_h + self.gap
        y       = self.height - row_h

        for label, value, max_val, bar_color in self.bars:
            fill_w = (float(value) / float(max_val) * bar_area) if max_val else 0
            # Track
            c.setFillColor(COLORS.SURFACE_ALT)
            c.roundRect(self.lbl_w, y, bar_area, self.bar_h, 3, fill=1, stroke=0)
            # Bar fill
            if fill_w > 4:
                c.setFillColor(bar_color)
                c.roundRect(self.lbl_w, y, fill_w, self.bar_h, 3, fill=1, stroke=0)
            # Label
            c.setFont("Helvetica", 8)
            c.setFillColor(COLORS.TEXT_BODY)
            c.drawString(0, y + 3, str(label)[:24])
            # Value
            c.setFont("Helvetica-Bold", 8)
            c.setFillColor(COLORS.TEAL)
            c.drawString(self.lbl_w + bar_area + 5, y + 3, str(value))
            y -= row_h


# ─────────────────────────────────────────────────────────
#  LAYOUT HELPERS
# ─────────────────────────────────────────────────────────
def _kpi_row(pairs: list, styles: dict) -> Table:
    """
    pairs: [(value_str, label_str), ...]
    Renders a single-row KPI card table matching warehouse report style.
    """
    n     = len(pairs)
    col_w = CONTENT_W / n
    vals  = [Paragraph(str(v), styles["kpi_value"]) for v, _ in pairs]
    lbls  = [Paragraph(l,      styles["kpi_label"])  for _, l in pairs]
    tbl   = Table([vals, lbls], colWidths=[col_w] * n)
    tbl.setStyle(TableStyle(kpi_card_style()))
    return tbl


def _section_card(elements: list) -> Table:
    """
    Wraps a list of flowables in a card with a teal left-border strip —
    exactly like warehouse report section cards.
    """
    inner = Table([[el] for el in elements], colWidths=[CONTENT_W - 8])
    inner.setStyle(TableStyle([
        ("LEFTPADDING",  (0,0),(-1,-1), 14),
        ("RIGHTPADDING", (0,0),(-1,-1), 6),
        ("TOPPADDING",   (0,0),(-1,-1), 5),
        ("BOTTOMPADDING",(0,0),(-1,-1), 5),
    ]))
    card = Table([[
        Table([[""]], colWidths=[4],
              style=TableStyle([
                  ("BACKGROUND",    (0,0),(-1,-1), COLORS.TEAL),
                  ("TOPPADDING",    (0,0),(-1,-1), 0),
                  ("BOTTOMPADDING", (0,0),(-1,-1), 0),
                  ("LEFTPADDING",   (0,0),(-1,-1), 0),
                  ("RIGHTPADDING",  (0,0),(-1,-1), 0),
              ])),
        inner,
    ]], colWidths=[4, CONTENT_W - 4])
    card.setStyle(TableStyle([
        ("BOX",          (0,0),(-1,-1), 0.5, COLORS.BORDER),
        ("LEFTPADDING",  (0,0),(-1,-1), 0),
        ("RIGHTPADDING", (0,0),(-1,-1), 0),
        ("TOPPADDING",   (0,0),(-1,-1), 0),
        ("BOTTOMPADDING",(0,0),(-1,-1), 0),
        ("BACKGROUND",   (0,0),(-1,-1), COLORS.WHITE),
    ]))
    return card


def _info_grid(fields: list, styles: dict, cols=2) -> Table:
    """2-column label/value grid."""
    col_w = CONTENT_W / cols
    rows  = []
    for i in range(0, len(fields), cols):
        chunk = fields[i:i+cols]
        while len(chunk) < cols:
            chunk.append(("", ""))
        rows.append([Paragraph(lbl,      styles["small"])      for lbl, _ in chunk])
        rows.append([Paragraph(str(val), styles["normal_bold"]) for _, val in chunk])
    tbl = Table(rows, colWidths=[col_w] * cols)
    tbl.setStyle(TableStyle(info_grid_style()))
    return tbl


def _data_table(headers, rows, col_widths, styles, risk_col=None) -> Table:
    hdr = [Paragraph(h, styles["table_header"]) for h in headers]
    data = [hdr]
    for row in rows:
        cells = []
        for j, cell in enumerate(row):
            txt = str(cell) if cell is not None else "—"
            if risk_col is not None and j == risk_col:
                st = styles.get(risk_style_key(txt), styles["table_cell"])
            else:
                st = styles["table_cell"]
            cells.append(Paragraph(txt, st))
        data.append(cells)
    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle(data_table_style()))
    return tbl


def _safe(d: dict, key: str, default="—") -> str:
    v = d.get(key)
    return str(v) if v not in (None, "", "None") else default


# ─────────────────────────────────────────────────────────
#  COVER PAGE
# ─────────────────────────────────────────────────────────
def _cover(story, ctx, styles):
    asset   = ctx["asset"]
    metrics = ctx["metrics"]

    # Teal top band
    band = Table(
        [[Paragraph("PredictiX", styles["cover_brand"])]],
        colWidths=[CONTENT_W],
    )
    band.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), COLORS.TEAL),
        ("TOPPADDING",    (0,0),(-1,-1), 26),
        ("BOTTOMPADDING", (0,0),(-1,-1), 26),
        ("LEFTPADDING",   (0,0),(-1,-1), 20),
        ("RIGHTPADDING",  (0,0),(-1,-1), 20),
    ]))
    story.append(band)
    story.append(Spacer(1, 8*mm))

    story.append(Paragraph("Asset Performance Report", styles["cover_title"]))
    story.append(Paragraph(_safe(asset, "asset_name"), styles["cover_subtitle"]))
    story.append(Spacer(1, 3*mm))
    story.append(section_divider())
    story.append(Spacer(1, 5*mm))

    story.append(Paragraph(
        f"Report Date: {ctx['generated_date']}  |  "
        f"Asset Code: {_safe(asset,'asset_code')}  |  "
        f"Warehouse: {_safe(asset,'warehouse')}",
        styles["cover_meta"]
    ))
    story.append(Spacer(1, 8*mm))


# ─────────────────────────────────────────────────────────
#  SECTION 1 — ASSET OVERVIEW
# ─────────────────────────────────────────────────────────
def _asset_overview(story, ctx, styles):
    asset   = ctx["asset"]
    metrics = ctx["metrics"]

    story.append(Paragraph("Asset Overview", styles["section"]))
    story.append(section_divider())

    story.append(_info_grid([
        ("Asset Code",           _safe(asset, "asset_code")),
        ("Asset Name",           _safe(asset, "asset_name")),
        ("Type / Category",      f"{_safe(asset,'asset_type')} / {_safe(asset,'category','—')}"),
        ("Vehicle Type",         _safe(asset, "vehicle_type")),
        ("Make",                 _safe(asset, "make")),
        ("Model",                _safe(asset, "model")),
        ("Manufacture Year",     _safe(asset, "manufacture_year")),
        ("Registration No.",     _safe(asset, "registration_number")),
        ("VIN",                  _safe(asset, "vin")),
        ("Status",               _safe(asset, "status")),
        ("Health Band",          _safe(asset, "health_band")),
        ("Criticality Score",    _safe(asset, "criticality_score")),
        ("Purchase Date",        _safe(asset, "purchase_date")),
        ("Warranty Expiry",      _safe(asset, "warranty_expiry_date")),
        ("Last Service Date",    _safe(asset, "last_service_date")),
        ("Next Service Date",    _safe(asset, "next_service_date")),
        ("Current Mileage (km)", _safe(asset, "current_mileage")),
        ("Vehicle Age (yrs)",    _safe(asset, "vehicle_age_years")),
        ("Payload Capacity (kg)",_safe(asset, "payload_capacity_kg")),
        ("Vehicle Role",         _safe(asset, "vehicle_role")),
        ("Lifetime Services",    _safe(asset, "lifetime_service_count")),
        ("Lifetime Breakdowns",  _safe(asset, "lifetime_breakdown_count")),
        ("Warehouse",            _safe(asset, "warehouse")),
        ("Department",           _safe(asset, "department")),
    ], styles, cols=2))

    story.append(Spacer(1, 5*mm))

    # Summary card
    story.append(_section_card([
        Paragraph("Asset Health Summary", styles["subsection"]),
        _info_grid([
            ("Health Score",           f"{metrics['health_score']}%"),
            ("Risk Level",             str(metrics["risk_level"])),
            ("Failure Probability",    f"{metrics['failure_probability']}%"),
            ("Predicted Maint. Date",  str(metrics["predicted_maintenance_date"])),
            ("Days Until Maintenance", str(metrics["days_until_maintenance"]) if metrics["days_until_maintenance"] else "—"),
            ("Est. Repair Cost",       f"{metrics['currency']} {metrics['estimated_cost']:,.0f}"),
        ], styles, cols=2),
    ]))

    story.append(Spacer(1, 5*mm))


# ─────────────────────────────────────────────────────────
#  SECTION 2 — SENSOR HEALTH SNAPSHOT
# ─────────────────────────────────────────────────────────
def _sensor_section(story, ctx, styles):
    sensor  = ctx.get("sensor", {})
    metrics = ctx["metrics"]

    story.append(Paragraph("Sensor Health Snapshot", styles["section"]))
    story.append(section_divider())

    if not sensor:
        story.append(Paragraph("No sensor data available for this asset.", styles["normal"]))
        story.append(Spacer(1, 5*mm))
        return

    story.append(_info_grid([
        ("Last Reading",                  _safe(sensor, "recorded_at")),
        ("Active Fault Codes",            _safe(sensor, "active_fault_code_count")),
        ("Days Since Last Service",       _safe(sensor, "days_since_last_service")),
        ("Engine Hours Since Service",    _safe(sensor, "engine_hours_since_last_service")),
        ("Odometer (km)",                 _safe(sensor, "odometer_km")),
        ("Downtime Hours (90d)",          _safe(sensor, "downtime_hours_last_90d")),
        ("Fuel Level",                    _safe(sensor, "fuel_level")),
        ("Coolant Temp Max (°C)",         _safe(sensor, "coolant_temp_max_c")),
        ("Engine Temp Avg (°C)",          _safe(sensor, "engine_temp_avg_c")),
        ("Battery Health",                _safe(sensor, "battery_health_pct") + "%"),
    ], styles, cols=2))

    story.append(Spacer(1, 5*mm))

    # Component health bars
    def _pct(key):
        v = sensor.get(key, "—")
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    bars = [
        ("Tire Health",          _pct("tire_health_pct"),     100, COLORS.TEAL),
        ("Brake Health",         _pct("brake_health_pct"),    100, COLORS.BLUE),
        ("Battery Health",       _pct("battery_health_pct"),  100, COLORS.LOW),
        ("Oil Life",             _pct("oil_life_pct"),        100, COLORS.TEAL),
        ("Hydraulic Health",     _pct("hydraulic_health_pct"),100, COLORS.BLUE),
    ]
    # Only show bars that have real data
    bars = [(l, v, m, c) for l, v, m, c in bars if v > 0]
    if bars:
        story.append(Paragraph("Component Health Overview", styles["subsection"]))
        story.append(HBarChart(bars))

    # AI top failure drivers
    top_exp = metrics.get("top_explanations") or {}
    if top_exp and isinstance(top_exp, dict):
        story.append(Spacer(1, 5*mm))
        story.append(Paragraph("Top AI-Identified Failure Drivers", styles["subsection"]))
        exp_items = sorted(top_exp.items(), key=lambda x: abs(float(x[1])) if str(x[1]).replace('.','',1).lstrip('-').isdigit() else 0, reverse=True)[:8]
        max_score = max(abs(float(v)) for _, v in exp_items) if exp_items else 1
        exp_bars = [
            (k.replace("_", " ").title(), round(abs(float(v)), 2), max_score, COLORS.HIGH)
            for k, v in exp_items
        ]
        story.append(HBarChart(exp_bars))

    story.append(PageBreak())


# ─────────────────────────────────────────────────────────
#  SECTION 3 — MAINTENANCE ANALYSIS
# ─────────────────────────────────────────────────────────
def _maintenance_section(story, ctx, insights, styles):
    metrics     = ctx["metrics"]
    maintenance = ctx["maintenance"]

    story.append(Paragraph("Maintenance Analysis", styles["section"]))
    story.append(section_divider())

    story.append(_kpi_row([
        (str(metrics["total_events"]),                "Total Events"),
        (str(metrics["preventive_count"]),            "Preventive"),
        (str(metrics["corrective_count"]),            "Corrective"),
        (f"{metrics['currency']} {metrics['total_cost']:,.0f}", "Total Cost"),
    ], styles))
    story.append(Spacer(1, 5*mm))

    # Breakdown bar chart
    if metrics["total_events"]:
        story.append(Paragraph("Maintenance Type Breakdown", styles["subsection"]))
        story.append(HBarChart([
            ("Preventive", metrics["preventive_count"], metrics["total_events"], COLORS.TEAL),
            ("Corrective", metrics["corrective_count"], metrics["total_events"], COLORS.HIGH),
        ]))
        story.append(Spacer(1, 5*mm))

    # AI cost analysis
    cost = insights.get("cost_analysis", {})
    if cost:
        story.append(_section_card([
            Paragraph("Cost Analysis", styles["subsection"]),
            _info_grid([
                ("Maintenance Cost (MTD)",  f"LKR {cost.get('maintenance_cost_mtd', 0):,.0f}"),
                ("Downtime Cost (MTD)",     f"LKR {cost.get('downtime_cost_mtd', 0):,.0f}"),
                ("Predicted Repair Cost",   f"LKR {cost.get('predicted_repair_cost', 0):,.0f}"),
                ("Predicted Downtime",      f"{cost.get('predicted_downtime_days', 0)} days"),
                ("Est. Cost (DB Model)",    f"{metrics['currency']} {metrics['estimated_cost']:,.0f}"),
                ("Cost Range",             f"{metrics['currency']} {metrics['min_cost']:,.0f} – {metrics['max_cost']:,.0f}"),
            ], styles, cols=2),
        ]))
        story.append(Spacer(1, 5*mm))

    # Maintenance history table
    if maintenance:
        story.append(Paragraph("Maintenance History (Recent 3)", styles["subsection"]))
        rows = []
        for m in maintenance[:3]:
            rows.append([
                _datetime(m.get("performed_at")) if m.get("performed_at") else _datetime(m.get("scheduled_date")),
                m.get("event_type") or "—",
                m.get("title") or "—",
                m.get("vendor_name") or "—",
                f"LKR {float(m['cost_amount']):,.0f}" if m.get("cost_amount") else "—",
                f"{float(m['downtime_hours']):.1f}h" if m.get("downtime_hours") else "—",
            ])
        story.append(_data_table(
            ["Date", "Type", "Title", "Vendor", "Cost", "Downtime"],
            rows,
            [CONTENT_W*0.17, CONTENT_W*0.12, CONTENT_W*0.30,
             CONTENT_W*0.18, CONTENT_W*0.13, CONTENT_W*0.10],
            styles,
        ))

    story.append(Spacer(1, 5*mm))


# ─────────────────────────────────────────────────────────
#  SECTION 4 — TICKET MANAGEMENT
# ─────────────────────────────────────────────────────────
def _tickets_section(story, ctx, styles):
    metrics = ctx["metrics"]
    tickets = ctx["tickets"]

    story.append(Paragraph("Ticket Management", styles["section"]))
    story.append(section_divider())

    story.append(_kpi_row([
        (str(metrics["total_tickets"]),         "Total Tickets"),
        (str(metrics["open_tickets"]),          "Open"),
        (str(metrics["high_priority_tickets"]), "High Priority"),
        (str(metrics["closed_tickets"]),        "Closed / Resolved"),
    ], styles))
    story.append(Spacer(1, 5*mm))

    if tickets:
        story.append(Paragraph("Ticket Details (Recent 3)", styles["subsection"]))
        rows = []
        for t in tickets[:3]:
            rows.append([
                str(t.get("ticket_number") or "—"),
                str(t.get("title") or "—")[:55],
                str(t.get("priority") or "—"),
                str(t.get("status") or "—"),
                str(t.get("final_category") or t.get("predicted_category") or "—"),
                str(t.get("opened_at"))[:10] if t.get("opened_at") else "—",
            ])
        story.append(_data_table(
            ["Ticket #", "Title", "Priority", "Status", "Category", "Opened"],
            rows,
            [CONTENT_W*0.12, CONTENT_W*0.34, CONTENT_W*0.10,
             CONTENT_W*0.12, CONTENT_W*0.16, CONTENT_W*0.16],
            styles,
            risk_col=2,
        ))

    story.append(Spacer(1, 5*mm))


# ─────────────────────────────────────────────────────────
#  SECTION 5 — AI PREDICTIONS & RECOMMENDATIONS
# ─────────────────────────────────────────────────────────
def _predictions_section(story, ctx, insights, styles):
    metrics = ctx["metrics"]
    future  = insights.get("future_predictions", {})
    eff     = insights.get("operational_efficiency", {})

    story.append(Paragraph("AI Predictions & Recommendations", styles["section"]))
    story.append(section_divider())

    story.append(_kpi_row([
        (f"{metrics['health_score']}%",         "Health Score"),
        (f"{metrics['failure_probability']}%",  "Failure Probability"),
        (str(metrics["risk_level"]),             "Risk Level"),
        (str(metrics["days_until_maintenance"]) + " days" if metrics["days_until_maintenance"] else "N/A",
         "Days Until Maintenance"),
    ], styles))
    story.append(Spacer(1, 5*mm))

    # Health score bar
    health = metrics["health_score"]
    bar_color = health_band_color(band_for(health))
    story.append(Paragraph("Asset Health Score", styles["subsection"]))
    story.append(HBarChart([("Health Score", health, 100, bar_color)], bar_h=12))
    story.append(Spacer(1, 5*mm))

    # AI executive summary
    summary = insights.get("executive_summary", "")
    if summary:
        story.append(_section_card([
            Paragraph("AI Executive Summary", styles["subsection"]),
            Paragraph(summary, styles["normal"]),
        ]))
        story.append(Spacer(1, 5*mm))

    # Recommendations
    recs = insights.get("recommendations", {})
    if recs:
        story.append(Paragraph("AI Recommendations", styles["subsection"]))
        for level in ("critical", "high", "medium"):
            items = recs.get(level, [])
            if not items:
                continue
            story.append(Paragraph(level.upper(), styles["normal_bold"]))
            for item in items:
                story.append(Paragraph(f"• {item}", styles.get(level, styles["normal"])))
            story.append(Spacer(1, 3*mm))
        story.append(Spacer(1, 3*mm))

    # Maintenance insights bullets
    maint_insights = insights.get("maintenance_insights", [])
    if maint_insights:
        story.append(_section_card([
            Paragraph("Maintenance Insights", styles["subsection"]),
            *[Paragraph(f"• {i}", styles["bullet"]) for i in maint_insights],
        ]))
        story.append(Spacer(1, 5*mm))

    # Future predictions grid
    if future:
        story.append(_section_card([
            Paragraph("Future Predictions", styles["subsection"]),
            _info_grid([
                ("Next Failure Probability",    f"{float(future.get('next_failure_probability',0))*100:.1f}%"),
                ("Optimal Maintenance Date",    str(future.get("optimal_maintenance_date", "—"))),
                ("Suggested Maintenance Type",  str(future.get("suggested_maintenance_type","—"))),
                ("Est. 6-Month Cost",           f"LKR {future.get('predicted_maintenance_cost_next_6_months', 0):,.0f}"),
                ("Performance in 6 Months",     str(future.get("predicted_performance_in_6_months","—"))),
                ("Est. Remaining Life",         str(future.get("estimated_remaining_life","—"))),
            ], styles, cols=2),
        ]))

    story.append(Spacer(1, 5*mm))


# ─────────────────────────────────────────────────────────
#  SECTION 6 — CONCLUSION
# ─────────────────────────────────────────────────────────
def _conclusion(story, ctx, insights, styles):
    story.append(Paragraph("Conclusions & Next Steps", styles["section"]))
    story.append(section_divider())

    conclusion = insights.get("conclusion") or insights.get("executive_summary", "No conclusion available.")
    story.append(_section_card([
        Paragraph("Executive Conclusion", styles["subsection"]),
        Paragraph(conclusion, styles["normal"]),
    ]))
    story.append(Spacer(1, 6*mm))

    opt = (insights.get("operational_efficiency") or {}).get("optimisation_recommendations", [])
    if opt:
        story.append(Paragraph("Optimisation Recommendations", styles["subsection"]))
        for item in opt:
            story.append(Paragraph(f"• {item}", styles["bullet"]))
        story.append(Spacer(1, 4*mm))

    story.append(thin_divider())
    story.append(Paragraph(
        "PredictiX AI Platform  |  Asset Management Solution  |  © 2026 All Rights Reserved",
        styles["footer"]
    ))


# ─────────────────────────────────────────────────────────
#  HELPERS (used inside sections)
# ─────────────────────────────────────────────────────────
def _datetime(val) -> str:
    if val is None:
        return "—"
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%d")
    return str(val)[:10]



# ─────────────────────────────────────────────────────────
#  CONTEXT NORMALIZER
#  Accepts old flat dummy shape OR new nested shape.
# ─────────────────────────────────────────────────────────
def _normalize_context(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Converts the old flat dummy context (from asset_reports.py dummy endpoint)
    to the new nested shape that all render functions expect.
    If already in nested shape, returns as-is.
    """
    if "asset" in ctx and isinstance(ctx.get("asset"), dict) and "metrics" in ctx:
        return ctx

    health = float(ctx.get("health_score", 100))
    return {
        "generated_date": datetime.now().strftime("%B %d, %Y"),
        "report_id":      str(ctx.get("asset_id", "DUMMY"))[:8].upper(),
        "asset": {
            "id":                     str(ctx.get("asset_id", "—")),
            "asset_code":             str(ctx.get("asset_id", "—"))[:8],
            "asset_name":             ctx.get("asset_name", "Asset Report"),
            "asset_type":             ctx.get("asset_type", "—"),
            "vehicle_type":           ctx.get("vehicle_type", "—"),
            "make":                   ctx.get("make", "—"),
            "model":                  ctx.get("model", "—"),
            "manufacture_year":       "—",
            "registration_number":    "—",
            "vin":                    "—",
            "status":                 ctx.get("status", "active"),
            "health_band":            ctx.get("alert_level", "—"),
            "criticality_score":      str(ctx.get("criticality", "—")),
            "purchase_date":          ctx.get("purchase_date", "—"),
            "warranty_expiry_date":   ctx.get("warranty_expiry_date", "—"),
            "last_service_date":      ctx.get("last_maintenance_date", "—"),
            "next_service_date":      ctx.get("next_maintenance_date", "—"),
            "current_mileage":        str(ctx.get("total_runtime_hours", "—")),
            "vehicle_age_years":      "—",
            "payload_capacity_kg":    "—",
            "vehicle_role":           ctx.get("functional_location", "—"),
            "lifetime_service_count": "—",
            "lifetime_breakdown_count":"—",
            "description":            str(ctx.get("location", "")),
            "warehouse":              "—",
            "department":             ctx.get("department", "—"),
        },
        "maintenance": [],
        "tickets":     [],
        "sensor":      {},
        "metrics": {
            "total_events":              0,
            "preventive_count":          0,
            "corrective_count":          0,
            "preventive_ratio":          0,
            "corrective_ratio":          0,
            "total_cost":                0.0,
            "avg_cost_per_event":        0.0,
            "total_downtime_hours":      0.0,
            "total_tickets":             0,
            "open_tickets":              0,
            "high_priority_tickets":     0,
            "closed_tickets":            0,
            "health_score":              health,
            "failure_probability":       round(float(ctx.get("failure_probability", 0)), 1),
            "risk_level":                str(ctx.get("risk_level", "Low")),
            "days_until_maintenance":    ctx.get("maintenance_cycle_days"),
            "predicted_maintenance_date":ctx.get("next_maintenance_date", "—"),
            "estimated_cost":            0.0,
            "min_cost":                  0.0,
            "max_cost":                  0.0,
            "currency":                  "LKR",
            "top_explanations":          {},
        },
    }

# ─────────────────────────────────────────────────────────
#  MAIN SERVICE CLASS
# ─────────────────────────────────────────────────────────
class PDFRenderService:

    def generate_pdf(self, context: Dict[str, Any],
                     insights: Dict[str, Any],
                     report_id: uuid.UUID) -> str:
        """
        Builds the full Asset Performance PDF.
        Returns path to a temp file — caller is responsible for deletion.
        """
        context    = _normalize_context(context)
        asset_name = context["asset"].get("asset_name", "Asset Report")
        styles     = get_styles()

        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)

        doc = SimpleDocTemplate(
            path,
            pagesize=A4,
            topMargin=20*mm,
            bottomMargin=16*mm,
            leftMargin=MARGIN,
            rightMargin=MARGIN,
            title=f"Asset Report — {asset_name}",
            author="PredictiX AI Platform",
        )

        story = []
        _cover(story, context, styles)
        _asset_overview(story, context, styles)
        _maintenance_section(story, context, insights, styles)
        _predictions_section(story, context, insights, styles)
        _conclusion(story, context, insights, styles)

        def _canvas_maker(filename, **kwargs):
            kwargs.pop("pagesize", None)
            return _HFCanvas(filename, pagesize=A4,
                             asset_name=asset_name, **kwargs)

        doc.build(story, canvasmaker=_canvas_maker)
        return path
    