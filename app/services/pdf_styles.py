"""
app/services/pdf_styles.py

Brand colors, typography, and table/card style presets that match
the PredictiX Warehouse AI Report visual identity (teal #0f766e).

Drop this file into app/services/pdf_styles.py — replaces existing file.
"""

from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import HRFlowable


# ─────────────────────────────────────────────────────────
#  BRAND COLOR PALETTE
# ─────────────────────────────────────────────────────────
class COLORS:
    # Brand
    TEAL          = colors.HexColor("#0f766e")   # primary teal
    TEAL_LIGHT    = colors.HexColor("#ccfbf1")   # soft teal tint
    TEAL_MID      = colors.HexColor("#5eead4")   # mid teal stripe

    # Surfaces
    WHITE         = colors.white
    SURFACE       = colors.HexColor("#f8fafc")   # card bg
    SURFACE_ALT   = colors.HexColor("#f1f5f9")   # alternate row
    BORDER        = colors.HexColor("#e2e8f0")   # light border
    BORDER_MED    = colors.HexColor("#cbd5e1")   # medium border

    # Text
    TEXT_DARK     = colors.HexColor("#0f172a")
    TEXT_BODY     = colors.HexColor("#334155")
    TEXT_MUTED    = colors.HexColor("#64748b")
    TEXT_ON_TEAL  = colors.white

    # Risk / status
    CRITICAL      = colors.HexColor("#ef4444")
    CRITICAL_BG   = colors.HexColor("#fef2f2")
    HIGH          = colors.HexColor("#f97316")
    HIGH_BG       = colors.HexColor("#fff7ed")
    MEDIUM        = colors.HexColor("#eab308")
    MEDIUM_BG     = colors.HexColor("#fefce8")
    LOW           = colors.HexColor("#22c55e")
    LOW_BG        = colors.HexColor("#f0fdf4")
    BLUE          = colors.HexColor("#3b82f6")


# ─────────────────────────────────────────────────────────
#  TYPOGRAPHY
# ─────────────────────────────────────────────────────────
def get_styles() -> dict:
    def s(name, **kw):
        base = dict(fontName="Helvetica", fontSize=10,
                    textColor=COLORS.TEXT_BODY, leading=15, spaceAfter=0)
        base.update(kw)
        return ParagraphStyle(name, **base)

    return {
        # Cover
        "cover_brand":    s("CoverBrand",   fontName="Helvetica-Bold", fontSize=20, textColor=COLORS.TEAL,     leading=24, spaceAfter=4),
        "cover_title":    s("CoverTitle",   fontName="Helvetica-Bold", fontSize=18, textColor=COLORS.TEXT_DARK,leading=22, spaceAfter=6),
        "cover_subtitle": s("CoverSub",     fontName="Helvetica",      fontSize=12, textColor=COLORS.TEXT_MUTED,leading=17, spaceAfter=4),
        "cover_meta":     s("CoverMeta",    fontName="Helvetica",      fontSize=9,  textColor=COLORS.TEXT_MUTED,leading=14),

        # Section / subsection
        "section":        s("Section",      fontName="Helvetica-Bold", fontSize=16, textColor=COLORS.TEAL,     leading=20, spaceBefore=10, spaceAfter=6),
        "subsection":     s("Subsection",   fontName="Helvetica-Bold", fontSize=12, textColor=COLORS.TEXT_DARK,leading=17, spaceBefore=8,  spaceAfter=5),

        # Body
        "normal":         s("Normal",       fontName="Helvetica",      fontSize=10, textColor=COLORS.TEXT_BODY,leading=16, spaceAfter=5),
        "normal_bold":    s("NormalBold",   fontName="Helvetica-Bold", fontSize=10, textColor=COLORS.TEXT_BODY,leading=16, spaceAfter=5),
        "small":          s("Small",        fontName="Helvetica",      fontSize=8.5,textColor=COLORS.TEXT_MUTED,leading=13,spaceAfter=2),
        "bullet":         s("Bullet",       fontName="Helvetica",      fontSize=10, textColor=COLORS.TEXT_BODY,leading=16, leftIndent=12, spaceAfter=4),

        # KPI cards
        "kpi_value":      s("KPIValue",     fontName="Helvetica-Bold", fontSize=18, textColor=COLORS.TEAL,     leading=22, spaceAfter=2),
        "kpi_label":      s("KPILabel",     fontName="Helvetica",      fontSize=8,  textColor=COLORS.TEXT_MUTED,leading=11, spaceAfter=0),

        # Tables
        "table_header":   s("TH",           fontName="Helvetica-Bold", fontSize=8.5,textColor=COLORS.TEXT_MUTED,leading=12),
        "table_cell":     s("TC",           fontName="Helvetica",      fontSize=9,  textColor=COLORS.TEXT_DARK, leading=13),
        "table_cell_bold":s("TCB",          fontName="Helvetica-Bold", fontSize=9,  textColor=COLORS.TEXT_DARK, leading=13),
        "table_cell_c":   s("TCC",          fontName="Helvetica",      fontSize=9,  textColor=COLORS.TEXT_DARK, leading=13, alignment=TA_CENTER),
        "table_cell_r":   s("TCR",          fontName="Helvetica",      fontSize=9,  textColor=COLORS.TEXT_DARK, leading=13, alignment=TA_RIGHT),

        # Risk labels
        "critical":       s("Critical",     fontName="Helvetica-Bold", fontSize=9,  textColor=COLORS.CRITICAL, leading=13),
        "high":           s("High",         fontName="Helvetica-Bold", fontSize=9,  textColor=COLORS.HIGH,     leading=13),
        "medium":         s("Medium",       fontName="Helvetica-Bold", fontSize=9,  textColor=COLORS.MEDIUM,   leading=13),
        "low":            s("Low",          fontName="Helvetica-Bold", fontSize=9,  textColor=COLORS.LOW,      leading=13),

        # Footer
        "footer":         s("Footer",       fontName="Helvetica",      fontSize=7.5,textColor=COLORS.TEXT_MUTED,leading=11, alignment=TA_CENTER),
    }


# ─────────────────────────────────────────────────────────
#  DIVIDERS
# ─────────────────────────────────────────────────────────
def section_divider():
    """Teal 2pt rule — place under every section heading."""
    return HRFlowable(width="100%", thickness=2, color=COLORS.TEAL, spaceBefore=6, spaceAfter=10)


def thin_divider():
    """Light grey 0.5pt rule — between sub-sections."""
    return HRFlowable(width="100%", thickness=0.5, color=COLORS.BORDER, spaceBefore=4, spaceAfter=4)


# ─────────────────────────────────────────────────────────
#  STATUS HELPERS
# ─────────────────────────────────────────────────────────
_RISK = {
    "critical":  ("critical", COLORS.CRITICAL, COLORS.CRITICAL_BG),
    "high":      ("high",     COLORS.HIGH,     COLORS.HIGH_BG),
    "at-risk":   ("high",     COLORS.HIGH,     COLORS.HIGH_BG),
    "medium":    ("medium",   COLORS.MEDIUM,   COLORS.MEDIUM_BG),
    "moderate":  ("medium",   COLORS.MEDIUM,   COLORS.MEDIUM_BG),
    "low":       ("low",      COLORS.LOW,      COLORS.LOW_BG),
}

def risk_style_key(level: str) -> str:
    return _RISK.get(str(level).lower().strip(), ("medium", None, None))[0]

def risk_color(level: str):
    return _RISK.get(str(level).lower().strip(), ("medium", COLORS.MEDIUM, None))[1]

def risk_bg(level: str):
    return _RISK.get(str(level).lower().strip(), ("medium", None, COLORS.MEDIUM_BG))[2]


# ─────────────────────────────────────────────────────────
#  TABLE STYLE PRESETS
# ─────────────────────────────────────────────────────────
def kpi_card_style() -> list:
    return [
        ("BACKGROUND",    (0,0),(-1,-1), COLORS.SURFACE),
        ("BOX",           (0,0),(-1,-1), 1,   COLORS.BORDER),
        ("INNERGRID",     (0,0),(-1,-1), 0.5, COLORS.BORDER),
        ("TOPPADDING",    (0,0),(-1,-1), 16),
        ("BOTTOMPADDING", (0,0),(-1,-1), 16),
        ("LEFTPADDING",   (0,0),(-1,-1), 14),
        ("RIGHTPADDING",  (0,0),(-1,-1), 14),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
    ]

def data_table_style() -> list:
    return [
        # Header row
        ("BACKGROUND",    (0,0),(-1,0),  COLORS.SURFACE),
        ("FONTNAME",      (0,0),(-1,0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0,0),(-1,0),  8.5),
        ("TEXTCOLOR",     (0,0),(-1,0),  COLORS.TEXT_MUTED),
        ("TOPPADDING",    (0,0),(-1,0),  8),
        ("BOTTOMPADDING", (0,0),(-1,0),  8),
        ("LINEBELOW",     (0,0),(-1,0),  1, COLORS.BORDER_MED),
        # Body
        ("FONTNAME",      (0,1),(-1,-1), "Helvetica"),
        ("FONTSIZE",      (0,1),(-1,-1), 9),
        ("TOPPADDING",    (0,1),(-1,-1), 6),
        ("BOTTOMPADDING", (0,1),(-1,-1), 6),
        ("ROWBACKGROUNDS",(0,1),(-1,-1), [COLORS.WHITE, COLORS.SURFACE_ALT]),
        ("LINEBELOW",     (0,1),(-1,-1), 0.4, COLORS.BORDER),
        ("LEFTPADDING",   (0,0),(-1,-1), 10),
        ("RIGHTPADDING",  (0,0),(-1,-1), 10),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
    ]

def info_grid_style() -> list:
    return [
        ("ROWBACKGROUNDS",(0,0),(-1,-1), [COLORS.SURFACE, COLORS.WHITE]),
        ("BOX",           (0,0),(-1,-1), 0.5, COLORS.BORDER),
        ("INNERGRID",     (0,0),(-1,-1), 0.3, COLORS.BORDER),
        ("TOPPADDING",    (0,0),(-1,-1), 5),
        ("BOTTOMPADDING", (0,0),(-1,-1), 4),
        ("LEFTPADDING",   (0,0),(-1,-1), 10),
        ("RIGHTPADDING",  (0,0),(-1,-1), 10),
        ("VALIGN",        (0,0),(-1,-1), "TOP"),
    ]