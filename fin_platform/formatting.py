"""
fin_platform/formatting.py
===========================
Indian number system formatting (Crores/Lakhs), percent, year labels,
and colour helpers for financial data display.
"""
from __future__ import annotations
from typing import Optional


def format_indian_number(value: Optional[float], decimals: int = 2) -> str:
    """
    Format number in Indian notation: Cr / L / K.
    e.g. 150000 → ₹1,50,000  or  1500 Cr → ₹1,500 Cr
    """
    if value is None:
        return "—"
    if value == 0:
        return "0"

    abs_val = abs(value)
    sign = "-" if value < 0 else ""

    if abs_val >= 1_00_00_000:  # ≥ 10 Crore
        cr = abs_val / 1_00_00_000
        if cr >= 1_000:
            return f"{sign}{cr:,.0f} Cr"
        return f"{sign}{cr:,.{decimals}f} Cr"
    elif abs_val >= 1_00_000:  # ≥ 1 Lakh
        l = abs_val / 1_00_000
        return f"{sign}{l:,.{decimals}f} L"
    elif abs_val >= 1_000:
        k = abs_val / 1_000
        return f"{sign}{k:,.{decimals}f} K"
    else:
        return f"{sign}{abs_val:,.{decimals}f}"


def format_crores(value: Optional[float], decimals: int = 0) -> str:
    """Format value assuming it's already in Crores."""
    if value is None:
        return "—"
    sign = "-" if value < 0 else ""
    abs_val = abs(value)
    if abs_val >= 1_000:
        return f"{sign}₹{abs_val:,.{decimals}f} Cr"
    return f"{sign}₹{abs_val:,.{decimals}f} Cr"


def format_percent(value: Optional[float], decimals: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value:+.{decimals}f}%" if abs(value) < 1000 else f"{value:,.{decimals}f}%"


def format_ratio(value: Optional[float], decimals: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{decimals}f}x"


def format_number(value: Optional[float], decimals: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:,.{decimals}f}"


def year_label(year_code: str) -> str:
    """
    Convert internal year code (YYYYMM) → display label.
    e.g. "202403" → "FY24", "202303" → "FY23"
    """
    if len(year_code) == 6 and year_code.isdigit():
        y = int(year_code[:4])
        m = int(year_code[4:])
        if m == 3:
            return f"FY{str(y)[2:]}"
        return f"{y}-{m:02d}"
    return year_code


def metric_label(metric: str) -> str:
    """Strip statement prefix from metric key."""
    if "::" in metric:
        return metric.split("::", 1)[1].strip()
    return metric


def get_zone_color(zone: str) -> str:
    """Return colour string for Altman Z-Score zones."""
    return {"Safe": "#10b981", "Grey": "#f59e0b", "Distress": "#ef4444"}.get(zone, "#6b7280")


def get_piotroski_color(score: int) -> str:
    """Return colour for Piotroski F-Score."""
    if score >= 7:
        return "#10b981"
    elif score >= 5:
        return "#f59e0b"
    return "#ef4444"


def get_quality_color(tier: str) -> str:
    return {"High": "#10b981", "Medium": "#f59e0b", "Low": "#ef4444"}.get(tier, "#6b7280")


def get_trend_color(direction: str) -> str:
    return {"up": "#10b981", "down": "#ef4444", "stable": "#6b7280"}.get(direction, "#6b7280")
