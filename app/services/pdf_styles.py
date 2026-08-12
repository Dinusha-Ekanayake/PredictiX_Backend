"""
app/services/pdf_styles.py

Shared colors, styles, and table style factories for PredictiX PDF reports.
"""

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import HRFlowable


# ─────────────────────────────────────────────────────────
#  COLOR PALETTE
# ─────────────────────────────────────────────────────────
class COLORS:
    TEAL          = colors.HexColor("#0f766e")
    TEAL_MID      = colors.HexColor("#14b8a6")
    TEAL_LIGHT    = colors.HexColor("#ccfbf1")
    BLUE          = colors.HexColor("#2563eb")
    WHITE         = colors.HexColor("#ffffff")
    SURFACE       = colors.HexColor("#f8fafc")
    SURFACE_ALT   = colors.HexColor("#f1f5f9")
    BORDER        = colors.HexColor("#e2e8f0")
    TEXT_BODY     = colors.HexColor("#1e293b")
    TEXT_MUTED    = colors.HexColor("#64748b")
    TEXT_ON_TEAL  = colors.HexColor("#ffffff")

    # Risk / status colors
    CRITICAL      = colors.HexColor("#ef4444")
    HIGH          = colors.HexColor("#f97316")
    MEDIUM        = colors.HexColor("#f59e0b")
    LOW           = colors.HexColor("#10b981")


# ─────────────────────────────────────────────────────────
#  RISK HELPERS
# ─────────────────────────────────────────────────────────
def risk_color(level: str) -> colors.Color:
    mapping = {
        "critical": COLORS.CRITICAL,
        "high":     COLORS.HIGH,
        "medium":   COLORS.MEDIUM,
        "low":      COLORS.LOW,
    }
    return mapping.get((level or "").lower(), COLORS.TEXT_MUTED)


def health_band_color(band: str | None) -> colors.Color:
    """Colour for a health band from app/services/health_bands.py.

    The health bar previously coloured itself from raw thresholds written
    inline (``health >= 80 ? LOW : health >= 60 ? MEDIUM : CRITICAL``). Those
    cut-offs belonged to no shared definition and the top one was unreachable —
    fleet health scores peak at 79 — so every asset report rendered an amber or
    red bar and none could ever be green.

    Five bands against four risk colours, so ``good`` borrows the mid-teal:
    it reads as positive without being the same green as ``excellent``.
    """
    mapping = {
        "excellent": COLORS.LOW,
        "good":      COLORS.TEAL_MID,
        "moderate":  COLORS.MEDIUM,
        "poor":      COLORS.HIGH,
        "critical":  COLORS.CRITICAL,
    }
    return mapping.get((band or "").lower(), COLORS.TEXT_MUTED)


def risk_style_key(level: str) -> str:
    mapping = {
        "critical": "risk_critical",
        "high":     "risk_high",
        "medium":   "risk_medium",
        "low":      "risk_low",
    }
    return mapping.get((level or "").lower(), "table_cell")


# ─────────────────────────────────────────────────────────
#  DIVIDERS
# ─────────────────────────────────────────────────────────
def section_divider():
    return HRFlowable(
        width="100%", thickness=2,
        color=COLORS.TEAL, spaceAfter=6, spaceBefore=2,
    )


def thin_divider():
    return HRFlowable(
        width="100%", thickness=0.5,
        color=COLORS.BORDER, spaceAfter=4, spaceBefore=4,
    )


# ─────────────────────────────────────────────────────────
#  PARAGRAPH STYLES
# ─────────────────────────────────────────────────────────
def get_styles() -> dict:
    base = getSampleStyleSheet()

    def _style(name, **kwargs):
        return ParagraphStyle(name=name, **kwargs)

    return {
        # ── Cover page ──────────────────────────────────
        "cover_brand": _style(
            "cover_brand",
            fontName="Helvetica-Bold", fontSize=22,
            textColor=COLORS.TEXT_ON_TEAL, alignment=TA_LEFT,
        ),
        "cover_title": _style(
            "cover_title",
            fontName="Helvetica-Bold", fontSize=26,
            textColor=COLORS.TEXT_BODY, spaceAfter=6,
        ),
        "cover_subtitle": _style(
            "cover_subtitle",
            fontName="Helvetica", fontSize=14,
            textColor=COLORS.TEXT_MUTED, spaceAfter=4,
        ),
        "cover_meta": _style(
            "cover_meta",
            fontName="Helvetica", fontSize=9,
            textColor=COLORS.TEXT_MUTED,
        ),

        # ── Section / sub-section headers ───────────────
        "section": _style(
            "section",
            fontName="Helvetica-Bold", fontSize=13,
            textColor=COLORS.TEAL, spaceBefore=10, spaceAfter=2,
        ),
        "subsection": _style(
            "subsection",
            fontName="Helvetica-Bold", fontSize=10,
            textColor=COLORS.TEXT_BODY, spaceBefore=6, spaceAfter=3,
        ),

        # ── Body text ────────────────────────────────────
        "normal": _style(
            "normal",
            fontName="Helvetica", fontSize=9,
            textColor=COLORS.TEXT_BODY, spaceAfter=3, leading=13,
        ),
        "normal_bold": _style(
            "normal_bold",
            fontName="Helvetica-Bold", fontSize=9,
            textColor=COLORS.TEXT_BODY, spaceAfter=2,
        ),
        "small": _style(
            "small",
            fontName="Helvetica", fontSize=8,
            textColor=COLORS.TEXT_MUTED, spaceAfter=1,
        ),
        "bullet": _style(
            "bullet",
            fontName="Helvetica", fontSize=9,
            textColor=COLORS.TEXT_BODY, leftIndent=10,
            spaceAfter=2, leading=13,
        ),
        "footer": _style(
            "footer",
            fontName="Helvetica-Oblique", fontSize=7.5,
            textColor=COLORS.TEXT_MUTED, alignment=TA_CENTER,
        ),

        # ── KPI cards ────────────────────────────────────
        "kpi_value": _style(
            "kpi_value",
            fontName="Helvetica-Bold", fontSize=20,
            textColor=COLORS.TEAL, alignment=TA_CENTER,
        ),
        "kpi_label": _style(
            "kpi_label",
            fontName="Helvetica", fontSize=8,
            textColor=COLORS.TEXT_MUTED, alignment=TA_CENTER,
        ),

        # ── Data tables ──────────────────────────────────
        "table_header": _style(
            "table_header",
            fontName="Helvetica-Bold", fontSize=8,
            textColor=COLORS.TEXT_ON_TEAL,
        ),
        "table_cell": _style(
            "table_cell",
            fontName="Helvetica", fontSize=8,
            textColor=COLORS.TEXT_BODY,
        ),

        # ── Risk level cells ─────────────────────────────
        "risk_critical": _style(
            "risk_critical",
            fontName="Helvetica-Bold", fontSize=8,
            textColor=COLORS.CRITICAL,
        ),
        "risk_high": _style(
            "risk_high",
            fontName="Helvetica-Bold", fontSize=8,
            textColor=COLORS.HIGH,
        ),
        "risk_medium": _style(
            "risk_medium",
            fontName="Helvetica-Bold", fontSize=8,
            textColor=COLORS.MEDIUM,
        ),
        "risk_low": _style(
            "risk_low",
            fontName="Helvetica-Bold", fontSize=8,
            textColor=COLORS.LOW,
        ),
    }


# ─────────────────────────────────────────────────────────
#  TABLE STYLE FACTORIES
# ─────────────────────────────────────────────────────────
def kpi_card_style() -> list:
    return [
        ("BACKGROUND",    (0, 0), (-1, -1), COLORS.SURFACE),
        ("BOX",           (0, 0), (-1, -1), 0.5, COLORS.BORDER),
        ("INNERGRID",     (0, 0), (-1, -1), 0.5, COLORS.BORDER),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]


def data_table_style() -> list:
    return [
        # Header row
        ("BACKGROUND",    (0, 0), (-1, 0),  COLORS.TEAL),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  COLORS.TEXT_ON_TEAL),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0),  8),
        ("TOPPADDING",    (0, 0), (-1, 0),  6),
        ("BOTTOMPADDING", (0, 0), (-1, 0),  6),
        # Data rows
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 1), (-1, -1), 8),
        ("TOPPADDING",    (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        # Alternating row colors
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [COLORS.WHITE, COLORS.SURFACE_ALT]),
        # Border
        ("BOX",           (0, 0), (-1, -1), 0.5, COLORS.BORDER),
        ("INNERGRID",     (0, 0), (-1, -1), 0.3, COLORS.BORDER),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]


def info_grid_style() -> list:
    return [
        ("FONTNAME",      (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW",     (0, 0), (-1, -1), 0.3, COLORS.BORDER),
    ]