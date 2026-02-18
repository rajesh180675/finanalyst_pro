"""
app.py
======
FinAnalyst Pro — Main Streamlit Application
Enterprise Penman-Nissim Financial Analysis Platform

Tabs:
  1. Overview
  2. PN Analysis (Penman-Nissim)
  3. Ratios
  4. Trends
  5. Scoring (Altman Z + Piotroski F)
  6. Valuation & Scenarios
  7. FCF & Value Drivers
  8. Mappings Editor
  9. Data Explorer
 10. Debug / Diagnostics
"""

import io
import json
import math
from typing import Dict, List, Optional, Any

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

from fin_platform.types import (
    FinancialData, MappingDict, PNOptions,
)
from fin_platform.parser import parse_file, merge_financial_data, expand_uploaded_files
from fin_platform.metric_patterns import (
    auto_map_metrics, get_all_targets, get_pattern_coverage,
    get_detailed_matches, get_targets_by_statement,
)
from fin_platform.analyzer import (
    get_years, analyze_financials, penman_nissim_analysis, calculate_scores,
)
from fin_platform.formatting import (
    format_indian_number, format_percent, format_ratio, year_label,
    metric_label, get_zone_color, get_piotroski_color, get_quality_color,
)

# ─── Page Configuration ───────────────────────────────────────────────────────

st.set_page_config(
    page_title="FinAnalyst Pro",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "About": "FinAnalyst Pro — Enterprise Penman-Nissim Financial Analysis Platform v8.0",
    },
)

# ─── Custom CSS ───────────────────────────────────────────────────────────────

st.markdown("""
<style>
    /* Main header */
    .main-header {
        background: linear-gradient(135deg, #1e40af 0%, #3730a3 100%);
        border-radius: 12px;
        padding: 1.2rem 1.5rem;
        color: white;
        margin-bottom: 1.5rem;
        box-shadow: 0 4px 20px rgba(30,64,175,0.3);
    }
    .main-header h1 { margin: 0; font-size: 1.6rem; font-weight: 700; letter-spacing: -0.02em; }
    .main-header p  { margin: 0.25rem 0 0; font-size: 0.85rem; opacity: 0.85; }

    /* KPI cards */
    .kpi-card {
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 1rem 1.2rem;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    }
    .kpi-label { font-size: 0.72rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.2rem; }
    .kpi-value { font-size: 1.5rem; font-weight: 700; color: #1e293b; }
    .kpi-sub   { font-size: 0.75rem; color: #94a3b8; margin-top: 0.15rem; }

    /* Section cards */
    .section-card {
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 1.2rem;
        margin-bottom: 1rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }
    .section-title {
        font-size: 0.95rem;
        font-weight: 600;
        color: #1e293b;
        margin-bottom: 0.75rem;
        padding-bottom: 0.5rem;
        border-bottom: 1px solid #f1f5f9;
    }

    /* Insight badges */
    .insight-positive { background:#dcfce7; color:#166534; padding:0.3rem 0.7rem; border-radius:6px; font-size:0.8rem; margin-bottom:0.35rem; display:block; }
    .insight-warning  { background:#fef9c3; color:#854d0e; padding:0.3rem 0.7rem; border-radius:6px; font-size:0.8rem; margin-bottom:0.35rem; display:block; }
    .insight-neutral  { background:#eff6ff; color:#1e40af; padding:0.3rem 0.7rem; border-radius:6px; font-size:0.8rem; margin-bottom:0.35rem; display:block; }

    /* Zone pills */
    .zone-safe     { background:#dcfce7; color:#166534; font-weight:600; padding:0.2rem 0.5rem; border-radius:4px; }
    .zone-grey     { background:#fef9c3; color:#854d0e; font-weight:600; padding:0.2rem 0.5rem; border-radius:4px; }
    .zone-distress { background:#fee2e2; color:#991b1b; font-weight:600; padding:0.2rem 0.5rem; border-radius:4px; }

    /* Mapping table */
    .map-high   { color:#16a34a; font-weight:600; }
    .map-medium { color:#ca8a04; font-weight:600; }
    .map-low    { color:#dc2626; font-weight:600; }

    /* Sidebar */
    .css-1aumxhk { background: #f8fafc; }

    /* Data quality bar */
    .quality-bar { height:6px; border-radius:3px; background:#e2e8f0; position:relative; }
    .quality-fill { height:100%; border-radius:3px; position:absolute; }

    /* Scenario cards */
    .scen-bear { border-left: 4px solid #ef4444; }
    .scen-base { border-left: 4px solid #3b82f6; }
    .scen-bull { border-left: 4px solid #22c55e; }

    /* Streamlit overrides */
    div.stButton > button { border-radius: 8px; font-weight: 500; }
    .stTabs [data-baseweb="tab"] { font-size: 0.82rem; padding: 0.5rem 1rem; }
    [data-testid="metric-container"] { background: white; border: 1px solid #e2e8f0; border-radius: 10px; padding: 0.8rem; }
</style>
""", unsafe_allow_html=True)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _yl(y: str) -> str:
    return year_label(y)


def _make_plotly_colors() -> List[str]:
    return ["#1e40af", "#3b82f6", "#60a5fa", "#93c5fd", "#bfdbfe",
            "#1d4ed8", "#2563eb", "#6366f1", "#8b5cf6", "#a78bfa"]


def _series_to_df(series: Dict[str, float], label: str) -> pd.DataFrame:
    rows = [{"Year": _yl(y), "Value": v, "Metric": label} for y, v in sorted(series.items())]
    return pd.DataFrame(rows)


def _build_bar(series: Dict[str, float], title: str, yaxis_title: str = "",
               pct: bool = False, color: str = "#1e40af") -> go.Figure:
    years_s = sorted(series.keys())
    labels = [_yl(y) for y in years_s]
    vals = [series[y] for y in years_s]
    colors = ["#ef4444" if v < 0 else color for v in vals]
    fig = go.Figure(go.Bar(x=labels, y=vals, marker_color=colors, name=title))
    fig.update_layout(
        title=dict(text=title, font=dict(size=14, color="#1e293b")),
        yaxis_title=yaxis_title or ("%" if pct else ""),
        paper_bgcolor="white", plot_bgcolor="#f8fafc",
        margin=dict(l=40, r=20, t=40, b=30),
        height=280, showlegend=False,
        font=dict(family="sans-serif", size=11, color="#64748b"),
        xaxis=dict(gridcolor="#e2e8f0"), yaxis=dict(gridcolor="#e2e8f0"),
    )
    return fig


def _build_line(
    multi_series: Dict[str, Dict[str, float]],
    title: str, yaxis_title: str = "", pct: bool = False
) -> go.Figure:
    fig = go.Figure()
    palette = _make_plotly_colors()
    for i, (name, series) in enumerate(multi_series.items()):
        if not series: continue
        years_s = sorted(series.keys())
        fig.add_trace(go.Scatter(
            x=[_yl(y) for y in years_s],
            y=[series[y] for y in years_s],
            name=name, mode="lines+markers",
            line=dict(color=palette[i % len(palette)], width=2.5),
            marker=dict(size=7),
        ))
    fig.update_layout(
        title=dict(text=title, font=dict(size=14, color="#1e293b")),
        yaxis_title=yaxis_title or ("%" if pct else ""),
        paper_bgcolor="white", plot_bgcolor="#f8fafc",
        margin=dict(l=40, r=20, t=40, b=30),
        height=300, legend=dict(orientation="h", y=-0.2),
        font=dict(family="sans-serif", size=11, color="#64748b"),
        xaxis=dict(gridcolor="#e2e8f0"), yaxis=dict(gridcolor="#e2e8f0"),
    )
    return fig


def _ratio_table(
    ratio_dict: Dict[str, Dict[str, float]], years: List[str], fmt_fn=None
) -> pd.DataFrame:
    if fmt_fn is None:
        fmt_fn = lambda v: f"{v:,.2f}"
    rows = []
    for metric, series in ratio_dict.items():
        row = {"Metric": metric}
        for y in years:
            v = series.get(y)
            row[_yl(y)] = fmt_fn(v) if v is not None else "—"
        rows.append(row)
    return pd.DataFrame(rows)


# ─── Session State ────────────────────────────────────────────────────────────

def _init_state() -> None:
    defaults = {
        "step": "upload",           # upload | mapping | dashboard
        "data": None,
        "mappings": None,
        "company_name": "",
        "years": [],
        "pn_cost_of_capital": 10.0,
        "pn_terminal_growth": 3.0,
        "pn_forecast_years": 5,
        "pn_forecast_method": "reoi_mean3",
        "pn_strict_mode": True,
        "pn_classification_mode": "auto",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init_state()


# ─── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("""
    <div style='text-align:center; padding:0.5rem 0 1rem;'>
        <span style='font-size:2rem;'>📊</span><br>
        <strong style='font-size:1rem; color:#1e40af;'>FinAnalyst Pro</strong><br>
        <span style='font-size:0.72rem; color:#64748b;'>Enterprise PN Framework v8.0</span>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")

    if st.session_state["step"] == "dashboard":
        st.subheader("⚙️ PN Settings")

        st.session_state["pn_cost_of_capital"] = st.slider(
            "Cost of Capital (r) %", 5.0, 25.0,
            st.session_state["pn_cost_of_capital"], 0.5,
            help="Weighted Average Cost of Capital for ReOI capital charge"
        )
        st.session_state["pn_terminal_growth"] = st.slider(
            "Terminal Growth (g) %", 0.0, 10.0,
            st.session_state["pn_terminal_growth"], 0.5,
            help="Perpetuity growth rate for terminal value"
        )
        st.session_state["pn_forecast_years"] = st.slider(
            "Forecast Horizon (years)", 3, 15,
            st.session_state["pn_forecast_years"],
            help="Explicit forecast period for ReOI discounting"
        )
        st.session_state["pn_forecast_method"] = st.selectbox(
            "Forecast Method",
            ["reoi_mean3", "reoi_last", "reoi_trend3"],
            index=["reoi_mean3", "reoi_last", "reoi_trend3"].index(
                st.session_state["pn_forecast_method"]
            ),
            help="How to seed the ReOI forecast"
        )
        st.session_state["pn_classification_mode"] = st.selectbox(
            "Investment Classification",
            ["auto", "operating", "investment"],
            index=["auto", "operating", "investment"].index(
                st.session_state["pn_classification_mode"]
            ),
            help="auto=detect holding company; operating=standard PN; investment=treat as OA"
        )
        st.session_state["pn_strict_mode"] = st.checkbox(
            "Strict Mode (no fallback assumptions)",
            value=st.session_state["pn_strict_mode"],
        )

        st.markdown("---")
        if st.button("🔄 New Analysis", use_container_width=True):
            for k in ["step", "data", "mappings", "company_name", "years"]:
                st.session_state[k] = {"step": "upload", "data": None, "mappings": None, "company_name": "", "years": []}.get(k)
            st.rerun()

    else:
        st.info("Upload financial data to begin analysis.", icon="📁")

    st.markdown("---")
    st.markdown("""
    <div style='font-size:0.7rem; color:#94a3b8; text-align:center;'>
        Penman-Nissim (2001) · Altman Z (1968)<br>
        Piotroski F (2000) · Shapley Attribution<br>
        ReOI Valuation · Scenario Analysis
    </div>
    """, unsafe_allow_html=True)


# ─── Main Header ─────────────────────────────────────────────────────────────

st.markdown("""
<div class='main-header'>
    <h1>📊 FinAnalyst Pro</h1>
    <p>Enterprise Penman-Nissim Financial Analysis Platform — Capitaline Data Specialist</p>
</div>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB RENDER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def _render_overview(analysis, pn_result, scoring, years, data, mappings):
    """Overview tab: KPIs, insights, company type, data quality."""
    st.markdown("### 🏠 Company Overview")

    # Insights
    if analysis.insights:
        st.markdown("**📋 Key Insights**")
        for ins in analysis.insights:
            if "✅" in ins:
                css = "insight-positive"
            elif "⚠️" in ins or "📉" in ins:
                css = "insight-warning"
            else:
                css = "insight-neutral"
            st.markdown(f"<span class='{css}'>{ins}</span>", unsafe_allow_html=True)
        st.markdown("")

    col1, col2 = st.columns([2, 1])

    with col1:
        # Key financial KPIs
        st.markdown("**📊 Financial Highlights**")
        kpi_metrics = ["Revenue", "Net Income", "EBIT", "Total Assets", "Total Equity", "Operating Cash Flow"]
        kpi_cols = st.columns(3)
        kpi_idx = 0

        from fin_platform.analyzer import derive_val
        for metric in kpi_metrics:
            last_yr = years[-1] if years else None
            if last_yr:
                val = derive_val(data, mappings, metric, last_yr)
                if val is not None:
                    col = kpi_cols[kpi_idx % 3]
                    with col:
                        st.metric(
                            label=metric,
                            value=format_indian_number(val),
                            delta=(f"{_yoy_pct(data, mappings, metric, years):.1f}% YoY"
                                   if _yoy_pct(data, mappings, metric, years) is not None else None),
                        )
                    kpi_idx += 1

        # Revenue & Net Income trend chart
        rev_series = {y: v for y in years if (v := derive_val(data, mappings, "Revenue", y)) is not None}
        ni_series = {y: v for y in years if (v := derive_val(data, mappings, "Net Income", y)) is not None}
        if rev_series or ni_series:
            series_to_plot = {}
            if rev_series: series_to_plot["Revenue"] = rev_series
            if ni_series: series_to_plot["Net Income"] = ni_series
            st.plotly_chart(_build_line(series_to_plot, "Revenue vs Net Income Trend", "Value"), use_container_width=True)

    with col2:
        # Company type
        if analysis.company_type:
            ct = analysis.company_type
            st.markdown("**🏢 Company Classification**")
            st.markdown(f"""
            <div class='section-card' style='font-size:0.82rem;'>
            <div><strong>Holding Co:</strong> {"✅ Yes" if ct.is_holding_company else "❌ No"}</div>
            <div><strong>Investment Co:</strong> {"✅ Yes" if ct.is_investment_company else "❌ No"}</div>
            <div><strong>Has Debt:</strong> {"Yes" if ct.has_debt else "No"}</div>
            <div style='margin-top:0.5rem;'><strong>Inv/Assets:</strong> {ct.investment_asset_ratio*100:.1f}%</div>
            <div><strong>OtherInc/Rev:</strong> {ct.other_income_ratio*100:.1f}%</div>
            <div><strong>Inv/Assets:</strong> {ct.inventory_ratio*100:.1f}%</div>
            </div>
            """, unsafe_allow_html=True)

        # Statement breakdown
        if analysis.summary.statement_breakdown:
            st.markdown("**📁 Data Coverage**")
            bd = analysis.summary.statement_breakdown
            total = sum(bd.values())
            for stmt, cnt in sorted(bd.items(), key=lambda x: -x[1]):
                pct = cnt / total * 100
                icon = {"ProfitLoss": "📋", "BalanceSheet": "🏦", "CashFlow": "💵", "Financial": "📊"}.get(stmt, "📁")
                st.markdown(f"{icon} **{stmt}**: {cnt} ({pct:.0f}%)")

        # Thesis bullets
        if pn_result.thesis:
            st.markdown("**💡 Investment Thesis**")
            thesis = pn_result.thesis
            for b in thesis.bullets[:3]:
                st.markdown(f"<span class='insight-positive'>✅ {b}</span>", unsafe_allow_html=True)
            for r in thesis.red_flags[:2]:
                st.markdown(f"<span class='insight-warning'>🚩 {r}</span>", unsafe_allow_html=True)
            for w in thesis.watch_items[:2]:
                st.markdown(f"<span class='insight-neutral'>👁 {w}</span>", unsafe_allow_html=True)


def _yoy_pct(data, mappings, metric, years):
    from fin_platform.analyzer import derive_val
    if len(years) < 2: return None
    curr = derive_val(data, mappings, metric, years[-1])
    prev = derive_val(data, mappings, metric, years[-2])
    if curr is None or prev is None or prev == 0: return None
    return (curr - prev) / abs(prev) * 100


def _render_penman_nissim(pn_result, years):
    """Penman-Nissim tab: reformulated BS/IS, PN ratios, academic metrics."""
    st.markdown("### 📐 Penman-Nissim Analysis")

    if pn_result.diagnostics:
        diag = pn_result.diagnostics
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            mode_color = "#166534" if not diag.treat_investments_as_operating else "#854d0e"
            st.markdown(f"""
            <div style='background:#f0fdf4; border-left:4px solid #16a34a; border-radius:6px;
                        padding:0.6rem 0.9rem; font-size:0.82rem; color:{mode_color};'>
            <strong>Classification:</strong> {diag.message}
            </div>
            """, unsafe_allow_html=True)
        with col_d2:
            if diag.fix_suggestions:
                with st.expander(f"🔧 {len(diag.fix_suggestions)} Fix Suggestions"):
                    for s in diag.fix_suggestions:
                        st.markdown(f"• {s}")

    yr_labels = [_yl(y) for y in years]

    subtabs = st.tabs([
        "Reformulated BS", "Reformulated IS", "PN Ratios",
        "Academic Metrics", "ROE Decomposition", "Accrual Quality",
        "📐 Nissim (2023) Profitability",
    ])

    # Reformulated Balance Sheet
    with subtabs[0]:
        bs = pn_result.reformulated_bs
        if bs:
            key_bs = ["Total Assets", "Operating Assets", "Financial Assets",
                      "Net Operating Assets", "Net Financial Assets", "Common Equity",
                      "Total Liabilities", "Operating Liabilities", "Financial Liabilities",
                      "Net Working Capital", "Invested Capital", "Net Debt"]
            rows = []
            for m in key_bs:
                if bs.get(m):
                    row = {"Metric": m}
                    for y in years:
                        v = bs[m].get(y)
                        row[_yl(y)] = format_indian_number(v) if v is not None else "—"
                    rows.append(row)
            if rows:
                df = pd.DataFrame(rows)
                st.dataframe(df, use_container_width=True, hide_index=True)

            # NOA vs NFA chart
            noa_s = bs.get("Net Operating Assets", {})
            nfa_s = bs.get("Net Financial Assets", {})
            if noa_s or nfa_s:
                fig = go.Figure()
                if noa_s:
                    fig.add_trace(go.Bar(name="NOA", x=[_yl(y) for y in sorted(noa_s)], y=list(noa_s[y] for y in sorted(noa_s)), marker_color="#1e40af"))
                if nfa_s:
                    fig.add_trace(go.Bar(name="NFA", x=[_yl(y) for y in sorted(nfa_s)], y=list(nfa_s[y] for y in sorted(nfa_s)), marker_color="#60a5fa"))
                fig.update_layout(title="NOA vs NFA", barmode="group", height=280, paper_bgcolor="white", plot_bgcolor="#f8fafc", margin=dict(l=40,r=20,t=40,b=30))
                st.plotly_chart(fig, use_container_width=True)

    # Reformulated Income Statement
    with subtabs[1]:
        ris = pn_result.reformulated_is
        if ris:
            key_is = ["Revenue", "Total Revenue", "EBIT", "NOPAT", "Net Income",
                      "EBITDA", "Gross Profit", "Interest Expense", "Other Income",
                      "Effective Tax Rate", "Net Financial Expense After Tax"]
            rows = []
            for m in key_is:
                if ris.get(m):
                    row = {"Metric": m}
                    for y in years:
                        v = ris[m].get(y)
                        if m == "Effective Tax Rate":
                            row[_yl(y)] = f"{v*100:.1f}%" if v is not None else "—"
                        else:
                            row[_yl(y)] = format_indian_number(v) if v is not None else "—"
                    rows.append(row)
            if rows:
                df = pd.DataFrame(rows)
                st.dataframe(df, use_container_width=True, hide_index=True)

            # NOPAT vs Net Income chart
            nopat_s = ris.get("NOPAT", {})
            ni_s = ris.get("Net Income", {})
            if nopat_s or ni_s:
                series = {}
                if nopat_s: series["NOPAT"] = nopat_s
                if ni_s: series["Net Income"] = ni_s
                st.plotly_chart(_build_line(series, "NOPAT vs Net Income"), use_container_width=True)

    # PN Ratios
    with subtabs[2]:
        ratios = pn_result.ratios
        key_ratios_pn = {
            "Core PN": ["RNOA %", "ROOA %", "OPM %", "NOAT"],
            "Leverage": ["FLEV", "NBC %", "Spread %"],
            "Returns": ["ROE %", "ROE (PN) %", "ROA %", "ROIC %"],
            "Growth": ["Revenue Growth %", "Net Income Growth %"],
        }
        for group, keys in key_ratios_pn.items():
            st.markdown(f"**{group}**")
            rows = []
            for m in keys:
                if ratios.get(m):
                    row = {"Ratio": m}
                    for y in years:
                        v = ratios[m].get(y)
                        row[_yl(y)] = f"{v:.2f}" if v is not None else "—"
                    rows.append(row)
            if rows:
                df = pd.DataFrame(rows)
                st.dataframe(df, use_container_width=True, hide_index=True)

        # RNOA vs ROE chart
        rnoa_s = ratios.get("RNOA %", {})
        roe_s = ratios.get("ROE %", {})
        if rnoa_s or roe_s:
            series = {}
            if rnoa_s: series["RNOA %"] = rnoa_s
            if roe_s: series["ROE %"] = roe_s
            st.plotly_chart(_build_line(series, "RNOA vs ROE", pct=True), use_container_width=True)

    # Academic metrics
    with subtabs[3]:
        if pn_result.academic:
            acad = pn_result.academic
            st.markdown("**ReOI & AEG**")
            rows = []
            for y in years:
                row = {"Year": _yl(y)}
                row["ReOI"] = format_indian_number(acad.reoi.get(y))
                row["Core ReOI"] = format_indian_number(acad.core_reoi.get(y) if acad.core_reoi else None)
                row["Cumulative ReOI"] = format_indian_number(acad.cumulative_reoi.get(y))
                row["AEG"] = format_indian_number(acad.aeg.get(y))
                rows.append(row)
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            # ReOI chart
            reoi_s = acad.core_reoi if acad.core_reoi else acad.reoi
            if reoi_s:
                fig = _build_bar(reoi_s, "Residual Operating Income (ReOI)", "Cr")
                st.plotly_chart(fig, use_container_width=True)

            # NOPAT drivers (Shapley)
            if acad.nopat_drivers:
                st.markdown("**NOPAT Driver Attribution (Shapley 3-Factor)**")
                driver_rows = []
                for y, d in sorted(acad.nopat_drivers.items()):
                    driver_rows.append({
                        "Year": _yl(y),
                        "ΔNOPAT": format_indian_number(d.delta_nopat),
                        "Margin Effect": format_indian_number(d.margin_effect),
                        "Turnover Effect": format_indian_number(d.turnover_effect),
                        "Capital Base Effect": format_indian_number(d.capital_base_effect),
                        "Residual": format_indian_number(d.residual),
                    })
                if driver_rows:
                    st.dataframe(pd.DataFrame(driver_rows), use_container_width=True, hide_index=True)

                    # Waterfall-style stacked bar
                    driver_years = sorted(acad.nopat_drivers.keys())
                    fig = go.Figure()
                    for key, color in [("margin_effect", "#1e40af"), ("turnover_effect", "#60a5fa"), ("capital_base_effect", "#93c5fd")]:
                        vals = [getattr(acad.nopat_drivers[y], key) for y in driver_years]
                        fig.add_trace(go.Bar(
                            name=key.replace("_", " ").title(),
                            x=[_yl(y) for y in driver_years], y=vals,
                            marker_color=color,
                        ))
                    fig.update_layout(
                        title="NOPAT Driver Attribution (Shapley 3-Factor)",
                        barmode="relative", height=300,
                        paper_bgcolor="white", plot_bgcolor="#f8fafc",
                        margin=dict(l=40,r=20,t=40,b=30),
                    )
                    st.plotly_chart(fig, use_container_width=True)

    # ROE Decomposition
    with subtabs[4]:
        ratios = pn_result.ratios
        st.markdown("**ROE = RNOA + FLEV × Spread**")
        roe_rows = []
        for y in years:
            rnoa = ratios.get("RNOA %", {}).get(y)
            flev = ratios.get("FLEV", {}).get(y)
            spread = ratios.get("Spread %", {}).get(y)
            roe_actual = ratios.get("ROE %", {}).get(y)
            roe_pn = ratios.get("ROE (PN) %", {}).get(y)
            roe_gap = ratios.get("ROE Gap %", {}).get(y)
            reconciled = ratios.get("ROE Reconciled", {}).get(y)
            roe_rows.append({
                "Year": _yl(y),
                "RNOA %": f"{rnoa:.1f}" if rnoa is not None else "—",
                "FLEV": f"{flev:.2f}" if flev is not None else "—",
                "Spread %": f"{spread:.1f}" if spread is not None else "—",
                "ROE (Actual)": f"{roe_actual:.1f}" if roe_actual is not None else "—",
                "ROE (PN)": f"{roe_pn:.1f}" if roe_pn is not None else "—",
                "Gap": f"{roe_gap:.2f}" if roe_gap is not None else "—",
                "✓": "✅" if reconciled == 1 else ("⚠️" if reconciled == 0 else "—"),
            })
        if roe_rows:
            st.dataframe(pd.DataFrame(roe_rows), use_container_width=True, hide_index=True)

    # Accrual Quality
    with subtabs[5]:
        if pn_result.academic:
            acad = pn_result.academic
            st.markdown("**Accrual Quality Analysis**")
            aq_rows = []
            for y in years:
                eq = acad.earnings_quality.get(y)
                ar = acad.accrual_ratio.get(y)
                ar_oa = acad.accrual_ratio_oa.get(y)
                ar_s = acad.accrual_ratio_sales.get(y)
                denom = acad.accrual_denominator_used.get(y)
                oa = acad.operating_accruals.get(y)
                color_map = {"High": "🟢", "Medium": "🟡", "Low": "🔴"}
                aq_rows.append({
                    "Year": _yl(y),
                    "Quality": f"{color_map.get(eq, '—')} {eq or '—'}",
                    "Accrual Ratio": f"{ar:.3f}" if ar is not None else "—",
                    "Denominator": denom or "—",
                    "Acc/OA": f"{ar_oa:.3f}" if ar_oa is not None else "—",
                    "Acc/Sales": f"{ar_s:.3f}" if ar_s is not None else "—",
                    "Op. Accruals": format_indian_number(oa),
                })
            if aq_rows:
                st.dataframe(pd.DataFrame(aq_rows), use_container_width=True, hide_index=True)

            # Quality tiers explanation
            st.markdown("""
            <div style='background:#f8fafc; border-radius:8px; padding:0.8rem; font-size:0.78rem; color:#64748b; margin-top:0.5rem;'>
            <strong>Earnings Quality Tiers:</strong>
            🟢 High = |Accrual Ratio| &lt; 5% — Cash earnings closely track accrual earnings<br>
            🟡 Medium = 5-15% — Some divergence; monitor direction<br>
            🔴 Low = &gt;15% — Significant accruals; increased manipulation risk
            </div>
            """, unsafe_allow_html=True)

    # ── Nissim (2023) Profitability Analysis ──────────────────────────────────
    with subtabs[6]:
        _render_nissim_profitability(pn_result, years)


def _render_nissim_profitability(pn_result, years):
    """
    Renders Nissim (2023) Profitability Analysis tab.

    Displays:
    1. Novel 3-factor RNOA decomposition: OPM × OAT / OFR
    2. Full ROCE hierarchy per Exhibit D of the paper
    3. Stability analysis of the three drivers
    4. Operations Funding Ratio deep-dive
    5. Interactive charts for each decomposition
    """
    nissim = pn_result.nissim_profitability
    if not nissim:
        st.warning("Nissim (2023) analysis not available — run PN analysis first.")
        return

    # ── Header & Citation ─────────────────────────────────────────────────────
    st.markdown("""
    <div style='background:linear-gradient(135deg,#1e3a8a 0%,#1d4ed8 100%);
                border-radius:10px; padding:1rem 1.2rem; color:white; margin-bottom:1rem;'>
    <h4 style='margin:0; font-size:1rem; font-weight:700;'>
        📐 Nissim (2023) — "Profitability Analysis"
    </h4>
    <p style='margin:0.3rem 0 0; font-size:0.78rem; opacity:0.85;'>
        Novel RNOA decomposition: <strong>RNOA = OPM × OAT / OFR</strong> &nbsp;|&nbsp;
        Full ROCE Hierarchy: ROCE → ROE → Recurring ROE → RNOA + FL Effect + Other Nonop<br>
        <em>Columbia Business School · SSRN #4064824 · November 2023</em>
    </p>
    </div>
    """, unsafe_allow_html=True)

    op = nissim.operating
    hier = nissim.roce_hierarchy

    # ── Stability Insights ─────────────────────────────────────────────────────
    if op and op.stability_notes:
        st.markdown("##### 🔍 Stability & Persistence Insights")
        for note in op.stability_notes:
            cls = "insight-positive" if "stable" in note.lower() or "anchor" in note.lower() else "insight-neutral"
            st.markdown(f"<span class='{cls}'>{note}</span>", unsafe_allow_html=True)
        st.markdown("")

    # ── Hierarchy Interpretations ──────────────────────────────────────────────
    if hier and hier.interpretation:
        for note in hier.interpretation:
            st.markdown(f"<span class='insight-neutral'>{note}</span>", unsafe_allow_html=True)
        st.markdown("")

    if not op and not hier:
        st.info("Insufficient data for Nissim decomposition. Verify BS/IS mappings.")
        return

    nissim_inner = st.tabs([
        "🔺 3-Factor RNOA", "🏛️ ROCE Hierarchy", "📊 Operating Credit",
        "📈 Charts", "📖 Methodology"
    ])

    # =========================================================================
    # TAB 1: NISSIM 3-FACTOR RNOA DECOMPOSITION
    # =========================================================================
    with nissim_inner[0]:
        st.markdown("""
        <div style='background:#eff6ff; border-left:4px solid #3b82f6; border-radius:6px;
                    padding:0.7rem 1rem; font-size:0.82rem; color:#1e40af; margin-bottom:1rem;'>
        <strong>Novel Decomposition (Nissim 2023, §5.2):</strong>
        RNOA = OPM × OAT / OFR<br>
        • <strong>OPM</strong> (Operating Profit Margin) = NOPAT / Revenue — how much of each revenue ₹ flows to capital<br>
        • <strong>OAT</strong> (Operating Asset Turnover) = Revenue / Avg OA — sales generated per ₹ of <em>all</em> operating assets<br>
        • <strong>OFR</strong> (Operations Funding Ratio) = NOA / OA — proportion of OA funded by capital (not operating credit)
        </div>
        """, unsafe_allow_html=True)

        if op:
            rows_3f = []
            for y in years:
                opm_v = op.opm.get(y)
                oat_v = op.oat.get(y)
                ofr_v = op.ofr.get(y)
                noat_v = op.noat.get(y)
                rnoa_n = op.rnoa_nissim.get(y)
                rooa_v = op.rooa.get(y)
                # OFR impact: how much operating credit amplifies RNOA
                impact_v = op.rnoa_ofr_impact.get(y)

                rows_3f.append({
                    "Year": _yl(y),
                    "OPM %": f"{opm_v:.2f}%" if opm_v is not None else "—",
                    "OAT (×)": f"{oat_v:.3f}" if oat_v is not None else "—",
                    "OFR (%)": f"{ofr_v*100:.1f}%" if ofr_v is not None else "—",
                    "= RNOA %": f"{rnoa_n:.2f}%" if rnoa_n is not None else "—",
                    "ROOA %": f"{rooa_v:.2f}%" if rooa_v is not None else "—",
                    "NOAT (std)": f"{noat_v:.3f}" if noat_v is not None else "—",
                    "OFR Amplification": f"+{impact_v:.2f}%" if (impact_v is not None and impact_v >= 0) else (f"{impact_v:.2f}%" if impact_v is not None else "—"),
                })

            if rows_3f:
                df_3f = pd.DataFrame(rows_3f)
                st.dataframe(df_3f, use_container_width=True, hide_index=True)

            # Stability CV comparison
            st.markdown("##### Stability Comparison (Lower CV = More Stable)")
            cv_cols = st.columns(3)
            for col, (label, cv, note) in zip(cv_cols, [
                ("OFR", op.ofr_stability_cv,
                 "Most stable (~0.08 empirically). Forecast using recent average."),
                ("OAT", op.oat_stability_cv,
                 "Moderately stable (~0.15). Based on capital structure of operations."),
                ("OPM", op.opm_stability_cv,
                 "Least stable (~1.0+). Mean-revert to industry benchmark."),
            ]):
                with col:
                    cv_str = f"{cv:.3f}" if cv is not None else "N/A"
                    cv_color = "#16a34a" if (cv or 999) < 0.2 else "#ca8a04" if (cv or 999) < 0.5 else "#dc2626"
                    st.markdown(f"""
                    <div class='kpi-card'>
                    <div class='kpi-label'>{label} — Coeff. of Variation</div>
                    <div class='kpi-value' style='color:{cv_color}; font-size:1.3rem;'>{cv_str}</div>
                    <div class='kpi-sub'>{note}</div>
                    </div>
                    """, unsafe_allow_html=True)

    # =========================================================================
    # TAB 2: FULL ROCE HIERARCHY
    # =========================================================================
    with nissim_inner[1]:
        st.markdown("""
        <div style='background:#f0fdf4; border-left:4px solid #16a34a; border-radius:6px;
                    padding:0.7rem 1rem; font-size:0.82rem; color:#166534; margin-bottom:1rem;'>
        <strong>Full ROCE Hierarchy (Nissim 2023, Exhibit D):</strong><br>
        ROCE = ROE + NCI Leverage Effect<br>
        ROE = Recurring ROE + Transitory ROE<br>
        Recurring ROE = <strong>RNOA + Financial Leverage Effect + Net Other Nonop Effect</strong><br>
        Financial Leverage Effect = FLEV × Financial Spread = FLEV × (RNOA − NBC)
        </div>
        """, unsafe_allow_html=True)

        if hier:
            # Level 1: ROCE → ROE
            st.markdown("**Level 1 — ROCE vs ROE**")
            l1_rows = []
            for y in years:
                roce_v = hier.roce.get(y)
                roe_v = hier.roe.get(y)
                nci_eff = hier.nci_leverage_effect.get(y)
                l1_rows.append({
                    "Year": _yl(y),
                    "ROCE %": f"{roce_v:.2f}%" if roce_v is not None else "—",
                    "ROE %": f"{roe_v:.2f}%" if roe_v is not None else "—",
                    "NCI Lev. Effect": f"{nci_eff:.3f}%" if nci_eff is not None else "—",
                    "NCI Leverage": f"{hier.nci_leverage.get(y):.3f}" if hier.nci_leverage.get(y) is not None else "—",
                    "NCI Spread": f"{hier.nci_spread.get(y):.2f}%" if hier.nci_spread.get(y) is not None else "—",
                })
            if l1_rows:
                st.dataframe(pd.DataFrame(l1_rows), use_container_width=True, hide_index=True)

            st.markdown("---")

            # Level 2: ROE → Recurring + Transitory
            st.markdown("**Level 2 — Recurring vs Transitory ROE**")
            l2_rows = []
            for y in years:
                roe_v = hier.roe.get(y)
                rec = hier.recurring_roe.get(y)
                trans = hier.transitory_roe.get(y)
                trans_inc = hier.transitory_income.get(y)
                l2_rows.append({
                    "Year": _yl(y),
                    "ROE %": f"{roe_v:.2f}%" if roe_v is not None else "—",
                    "Recurring ROE %": f"{rec:.2f}%" if rec is not None else "—",
                    "Transitory ROE %": f"{trans:.3f}%" if trans is not None else "—",
                    "Transitory Income": format_indian_number(trans_inc),
                    "Status": "✅" if (trans is not None and abs(trans) < 1) else "⚠️",
                })
            if l2_rows:
                st.dataframe(pd.DataFrame(l2_rows), use_container_width=True, hide_index=True)

            st.markdown("""
            <div style='font-size:0.75rem; color:#64748b; padding:0.4rem;'>
            📌 Transitory items proxied via exceptional/extraordinary items per Nissim (2022b).
            Recurring ROE = ROE − Transitory ROE. Mean of Transitory ROE ≈ 0 by construction.
            </div>
            """, unsafe_allow_html=True)

            st.markdown("---")

            # Level 3: Recurring ROE → RNOA + FLE + Other
            st.markdown("**Level 3 — Recurring ROE Decomposition**")
            l3_rows = []
            for y in years:
                rec = hier.recurring_roe.get(y)
                rnoa_v = hier.rnoa.get(y)
                fl_eff = hier.financial_leverage_effect.get(y)
                other_eff = hier.net_other_nonop_effect.get(y)
                flev_v = hier.financial_leverage.get(y)
                nbc_v = hier.net_borrowing_cost.get(y)
                spread_v = hier.financial_spread.get(y)

                recon_check = next((r for r in hier.roce_reconciliation if r["year"] == y), None)
                status = (recon_check["status"] if recon_check else "—")

                l3_rows.append({
                    "Year": _yl(y),
                    "Recurring ROE %": f"{rec:.2f}%" if rec is not None else "—",
                    "RNOA %": f"{rnoa_v:.2f}%" if rnoa_v is not None else "—",
                    "FLE %": f"{fl_eff:.2f}%" if fl_eff is not None else "—",
                    "Other Nonop %": f"{other_eff:.3f}%" if other_eff is not None else "—",
                    "FLEV": f"{flev_v:.3f}" if flev_v is not None else "—",
                    "NBC %": f"{nbc_v:.2f}%" if nbc_v is not None else "—",
                    "Spread %": f"{spread_v:.2f}%" if spread_v is not None else "—",
                    "✓": "✅" if status == "ok" else "⚠️",
                })
            if l3_rows:
                st.dataframe(pd.DataFrame(l3_rows), use_container_width=True, hide_index=True)

            # Reconciliation detail
            if hier.roce_reconciliation:
                with st.expander("🔍 Reconciliation Detail (RNOA + FLE + Other vs Recurring ROE)"):
                    recon_df_rows = []
                    for r in hier.roce_reconciliation:
                        recon_df_rows.append({
                            "Year": _yl(r["year"]),
                            "RNOA": f"{r['rnoa']:.2f}%",
                            "FLE": f"{r['fl_effect']:.2f}%",
                            "Other": f"{r['other_nonop_effect']:.3f}%",
                            "Reconstructed": f"{r['reconstructed_recurring_roe']:.2f}%",
                            "Reported": f"{r['reported_recurring_roe']:.2f}%",
                            "Gap": f"{r['gap']:.3f}%",
                            "Status": "✅ ok" if r["status"] == "ok" else "⚠️ warn",
                        })
                    st.dataframe(pd.DataFrame(recon_df_rows), use_container_width=True, hide_index=True)

    # =========================================================================
    # TAB 3: OPERATING CREDIT DEEP-DIVE
    # =========================================================================
    with nissim_inner[2]:
        st.markdown("""
        <div style='background:#fef9c3; border-left:4px solid #ca8a04; border-radius:6px;
                    padding:0.7rem 1rem; font-size:0.82rem; color:#854d0e; margin-bottom:1rem;'>
        <strong>Operating Credit Analysis (Nissim 2023, §5.2)</strong><br>
        Operating credit (AP, deferred revenue, accrued liabilities, deferred taxes, etc.) reduces
        the net capital invested in operations. A low OFR implies large operating credit — reflecting
        <strong>market power</strong>, supplier relationships, or future earnings reversals.
        The cost of operating credit is embedded in operating expenses (higher COGS/SG&A), which
        lowers OPM but is compensated by the higher multiplier (1/OFR) on RNOA.
        </div>
        """, unsafe_allow_html=True)

        if op:
            oc_rows = []
            for y in years:
                ofr_v = op.ofr.get(y)
                oc_pct = op.operating_credit_pct.get(y)
                rnoa_n = op.rnoa_nissim.get(y)
                rooa_v = op.rooa.get(y)
                impact = op.rnoa_ofr_impact.get(y)

                # NOA and OA from the BS
                noa_v = pn_result.reformulated_bs.get("Net Operating Assets", {}).get(y)
                oa_v = pn_result.reformulated_bs.get("Operating Assets", {}).get(y)
                ol_v = pn_result.reformulated_bs.get("Operating Liabilities", {}).get(y)

                oc_rows.append({
                    "Year": _yl(y),
                    "OA": format_indian_number(oa_v),
                    "OL": format_indian_number(ol_v),
                    "NOA": format_indian_number(noa_v),
                    "OFR %": f"{ofr_v*100:.1f}%" if ofr_v is not None else "—",
                    "Op. Credit %": f"{oc_pct:.1f}%" if oc_pct is not None else "—",
                    "ROOA %": f"{rooa_v:.2f}%" if rooa_v is not None else "—",
                    "RNOA %": f"{rnoa_n:.2f}%" if rnoa_n is not None else "—",
                    "OFR Amplif. (pp)": f"+{impact:.2f}" if (impact is not None and impact >= 0) else (f"{impact:.2f}" if impact is not None else "—"),
                })
            if oc_rows:
                st.dataframe(pd.DataFrame(oc_rows), use_container_width=True, hide_index=True)

            st.markdown("""
            **Interpretation Guide:**
            - **OFR < 55%** → >45% funded by operating credit → strong supplier/customer power
            - **OFR 55–75%** → balanced; typical for non-financial industrial firms
            - **OFR > 85%** → minimal operating credit; capital-intensive or limited credit access
            - **OFR Amplification** → percentage points by which operating credit boosts RNOA above ROOA
            - **Empirical benchmarks** (Nissim 2023, Table 1): Mean OFR ≈ 64%, Std ≈ 17%, CV ≈ 0.08
            """)

            # Forecasting implication
            if op.ofr_stability_cv is not None and op.ofr_stability_cv < 0.15:
                avg_ofr = sum(op.ofr.values()) / len(op.ofr) if op.ofr else None
                if avg_ofr is not None:
                    st.success(
                        f"**Forecasting implication:** OFR is very stable (CV={op.ofr_stability_cv:.3f}). "
                        f"Use median OFR ≈ {avg_ofr:.1%} to forecast operating liabilities: "
                        f"OL_forecast = OA_forecast × {(1-avg_ofr):.1%}"
                    )

    # =========================================================================
    # TAB 4: CHARTS
    # =========================================================================
    with nissim_inner[3]:
        st.markdown("##### 3-Factor RNOA Decomposition — Visual")

        c1, c2 = st.columns(2)

        # OPM, OAT, OFR over time
        if op and op.opm and op.oat and op.ofr:
            with c1:
                fig_opm = _build_bar(op.opm, "Operating Profit Margin (OPM %)", pct=True)
                st.plotly_chart(fig_opm, use_container_width=True)

            with c2:
                fig_ofr = _build_bar(
                    {y: v * 100 for y, v in op.ofr.items()},
                    "Operations Funding Ratio (OFR %)",
                    pct=True, color="#7c3aed"
                )
                st.plotly_chart(fig_ofr, use_container_width=True)

        c3, c4 = st.columns(2)
        if op and op.oat:
            with c3:
                fig_oat = _build_bar(op.oat, "Operating Asset Turnover (OAT ×)", pct=False, color="#0891b2")
                st.plotly_chart(fig_oat, use_container_width=True)

        if op and op.rnoa_nissim:
            with c4:
                fig_rnoa_compare = _build_line(
                    {
                        "RNOA (Nissim 3-factor)": op.rnoa_nissim,
                        "ROOA (Gross)": op.rooa,
                    },
                    "RNOA vs ROOA Comparison",
                    pct=True,
                )
                st.plotly_chart(fig_rnoa_compare, use_container_width=True)

        # ROCE Hierarchy waterfall if available
        if hier and hier.recurring_roe and hier.rnoa and hier.financial_leverage_effect:
            st.markdown("##### ROCE Hierarchy — Component Trends")
            hier_multi = {}
            if hier.recurring_roe: hier_multi["Recurring ROE"] = hier.recurring_roe
            if hier.transitory_roe: hier_multi["Transitory ROE"] = hier.transitory_roe
            if hier.rnoa: hier_multi["RNOA"] = hier.rnoa
            if hier.financial_leverage_effect: hier_multi["FL Effect"] = hier.financial_leverage_effect

            fig_hier = _build_line(hier_multi, "ROCE Hierarchy Components (%)", pct=True)
            st.plotly_chart(fig_hier, use_container_width=True)

        # OFR stability scatter
        if op and op.ofr and len(op.ofr) > 1:
            st.markdown("##### OFR Stability — Year-over-Year")
            import plotly.express as px_ex
            ofr_years = sorted(op.ofr.keys())
            ofr_vals = [op.ofr[y] * 100 for y in ofr_years]
            ofr_mean = sum(ofr_vals) / len(ofr_vals)
            fig_ofr_ts = go.Figure()
            fig_ofr_ts.add_trace(go.Scatter(
                x=[_yl(y) for y in ofr_years], y=ofr_vals,
                mode="lines+markers", name="OFR %",
                line=dict(color="#7c3aed", width=2.5),
                marker=dict(size=8),
            ))
            fig_ofr_ts.add_hline(
                y=ofr_mean, line_dash="dash", line_color="#94a3b8",
                annotation_text=f"Mean: {ofr_mean:.1f}%"
            )
            fig_ofr_ts.update_layout(
                title="Operations Funding Ratio Over Time",
                yaxis_title="%", paper_bgcolor="white", plot_bgcolor="#f8fafc",
                height=280, margin=dict(l=40, r=20, t=40, b=30),
                font=dict(size=11, color="#64748b"),
                xaxis=dict(gridcolor="#e2e8f0"), yaxis=dict(gridcolor="#e2e8f0"),
            )
            st.plotly_chart(fig_ofr_ts, use_container_width=True)

    # =========================================================================
    # TAB 5: METHODOLOGY
    # =========================================================================
    with nissim_inner[4]:
        st.markdown("""
        ### 📖 Nissim (2023) — Methodology Reference

        ---

        #### 1. Core Innovation: 3-Factor RNOA Decomposition

        **Standard (DuPont-style):**
        > RNOA = OPM × NOAT
        > where NOAT = Revenue / Avg **Net** Operating Assets

        **Shortcoming:** When NOA is small (or negative), NOAT becomes meaningless.
        Sales are generated by *all* operating assets, not just the net portion.

        **Nissim (2023) Novel Approach:**
        > RNOA = OPM × OAT / OFR
        > where OAT = Revenue / Avg **Gross** Operating Assets
        > and OFR = NOA / OA (Operations Funding Ratio)

        This is always meaningful because OA ≥ 0 by construction.

        ---

        #### 2. Operations Funding Ratio (OFR)

        OFR = NOA / OA = (OA − OL) / OA = 1 − (OL / OA)

        A **low OFR** implies:
        - Large operating credit (AP, deferred rev, accrued liabilities, deferred taxes)
        - Potential **market power** over suppliers/customers/employees
        - Financial stability (creditors extend credit only to creditworthy firms)
        - Possible overstated liabilities (restructuring reserves) → future earnings reversal
        - Low M&A activity (acquisitions inflate OA but not OL)

        **Empirical properties (Nissim 2023, Table 1):**
        - Mean OFR ≈ 64%, Median ≈ 67%, Std ≈ 17%
        - Persistence (1-year) ≈ 0.955 — most stable of the three drivers
        - CV ≈ 0.079 — vs OAT CV ≈ 0.152 vs OPM CV ≈ 1.054

        **Forecasting implication:** When projecting balance sheets, first forecast OA
        (from revenue), then derive OL = OA × (1 − median OFR).

        ---

        #### 3. Full ROCE Hierarchy (Exhibit D)

        ```
        ROCE
        ├── NCI Leverage Effect = NCI Leverage × NCI Spread
        └── ROE
            ├── Transitory ROE = Transitory Income / Avg Equity
            └── Recurring ROE
                ├── RNOA = NOPAT / Avg NOA
                ├── Financial Leverage Effect = FLEV × (RNOA − NBC)
                │   ├── FLEV = Avg Net Debt / Avg Equity
                │   └── NBC = NFE_AT / Avg Net Debt
                └── Net Other Nonop Assets Effect
                    = Relative Size × (Return on ONA − RNOA)
        ```

        **Key persistence findings (Nissim 2023, Table 3):**
        - OFR persistence (j=1): 0.955
        - OAT persistence (j=1): 0.946
        - OPM persistence (j=1): 0.723
        - RNOA persistence (j=1): 0.741

        **Out-of-sample forecast improvement (Table 6):**
        - Decomposing RNOA into OPM × OAT / OFR reduces mean squared forecast error by **8%** (j=1)
        - Decomposing ROE into Recurring + Transitory reduces MSE by **4.6%** (j=1)

        ---

        #### 4. Reformulated Financial Statements

        **Operating assets** include all assets needed for operations (AR, inventory, PP&E,
        goodwill, right-of-use assets, operating intangibles).

        **Operating liabilities** include all liabilities related to operating activities
        (AP, accrued expenses, deferred revenue, deferred taxes, operating lease obligations,
        pension obligations).

        **Financial assets** = excess cash + marketable securities + fixed income instruments.

        **Net Operating Assets (NOA)** = OA − OL = the capital invested in operations.

        **NOPAT** = Revenue − Operating Costs − Tax on Operating Income.
        Tax split: Tax on operations = EBIT_ops × effective_tax_rate.

        ---

        *Reference: Nissim, D. (2023). "Profitability Analysis." Columbia Business School.
        SSRN Working Paper Abstract #4064824. Current version: November 2023.*
        """)


def _render_ratios(analysis, pn_result, years):
    """Ratios tab: all ratio categories in tables + charts."""
    st.markdown("### 📊 Financial Ratios")

    categories = {
        "Liquidity": ("💧", "Current Ratio, Quick Ratio, Cash Ratio"),
        "Profitability": ("📈", "Margins, ROA, ROE"),
        "Leverage": ("⚖️", "D/E, Interest Coverage, Equity Multiplier"),
        "Efficiency": ("⚡", "Asset Turnover, Working Capital Days"),
    }

    for cat, (icon, desc) in categories.items():
        cat_data = analysis.ratios.get(cat, {})
        if cat_data:
            with st.expander(f"{icon} {cat} — {desc}", expanded=(cat == "Profitability")):
                rows = []
                for metric, series in cat_data.items():
                    row = {"Metric": metric}
                    for y in years:
                        v = series.get(y)
                        row[_yl(y)] = f"{v:.2f}" if v is not None else "—"
                    rows.append(row)
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

                # Mini chart for key metrics
                key_metric = list(cat_data.keys())[0] if cat_data else None
                if key_metric and cat_data[key_metric]:
                    fig = _build_bar(cat_data[key_metric], key_metric, pct="%" in key_metric)
                    st.plotly_chart(fig, use_container_width=True)


def _render_trends(analysis, years):
    """Trends tab: CAGR, YoY growth, volatility."""
    st.markdown("### 📈 Trend Analysis")

    if not analysis.trends:
        st.info("No trend data available. Check if key metrics (Revenue, Net Income) are mapped.")
        return

    for metric, trend in analysis.trends.items():
        with st.expander(f"**{metric}** — CAGR: {trend.cagr:.1f}% | Direction: {trend.direction.upper()}", expanded=(metric == "Revenue")):
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("CAGR", f"{trend.cagr:.1f}%")
            col2.metric("Latest", format_indian_number(trend.latest_value))
            col3.metric("Volatility", f"{trend.volatility:.1f}%")
            col4.metric("Direction", trend.direction.upper())

            if trend.yoy_growth:
                st.plotly_chart(
                    _build_bar(trend.yoy_growth, f"{metric} — YoY Growth %", pct=True),
                    use_container_width=True
                )


def _render_scoring(scoring, years):
    """Scoring tab: Altman Z + Piotroski F with detailed signals."""
    st.markdown("### 🛡️ Financial Scoring Models")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### Altman Z-Score (Distress Prediction)")
        st.markdown("""
        <div style='font-size:0.75rem; color:#64748b; margin-bottom:0.7rem;'>
        Z > 2.99 = Safe Zone &nbsp;|&nbsp; 1.81–2.99 = Grey Zone &nbsp;|&nbsp; Z < 1.81 = Distress Zone
        </div>
        """, unsafe_allow_html=True)

        if scoring.altman_z:
            rows = []
            for y, az in sorted(scoring.altman_z.items()):
                zone_icons = {"Safe": "✅", "Grey": "⚠️", "Distress": "🚨"}
                rows.append({
                    "Year": _yl(y),
                    "Z-Score": f"{az.score:.2f}",
                    "Zone": f"{zone_icons.get(az.zone, '?')} {az.zone}",
                })
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)

            # Gauge-style chart
            z_vals = [az.score for az in scoring.altman_z.values()]
            z_years = [_yl(y) for y in sorted(scoring.altman_z.keys())]
            colors = [get_zone_color(az.zone) for az in [scoring.altman_z[y] for y in sorted(scoring.altman_z.keys())]]
            fig = go.Figure(go.Bar(x=z_years, y=z_vals, marker_color=colors, name="Z-Score"))
            fig.add_hline(y=2.99, line_dash="dash", line_color="#22c55e", annotation_text="Safe (2.99)")
            fig.add_hline(y=1.81, line_dash="dash", line_color="#f59e0b", annotation_text="Grey (1.81)")
            fig.update_layout(title="Altman Z-Score Trend", height=260, paper_bgcolor="white", plot_bgcolor="#f8fafc", margin=dict(l=40,r=20,t=40,b=30))
            st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.markdown("#### Piotroski F-Score (Quality)")
        st.markdown("""
        <div style='font-size:0.75rem; color:#64748b; margin-bottom:0.7rem;'>
        8-9 = Strong &nbsp;|&nbsp; 5-7 = Average &nbsp;|&nbsp; 0-4 = Weak
        </div>
        """, unsafe_allow_html=True)

        if scoring.piotroski_f:
            # Latest year signals
            latest_yr = sorted(scoring.piotroski_f.keys())[-1]
            latest_pf = scoring.piotroski_f[latest_yr]
            st.markdown(f"**{_yl(latest_yr)}: F-Score = {latest_pf.score}/9**")
            for sig in latest_pf.signals:
                color = "#166534" if sig.startswith("✅") else "#991b1b"
                st.markdown(f"<span style='font-size:0.8rem; color:{color};'>{sig}</span>", unsafe_allow_html=True)

            # Score trend chart
            pf_scores = {y: pf.score for y, pf in scoring.piotroski_f.items()}
            colors_pf = [get_piotroski_color(pf.score) for pf in [scoring.piotroski_f[y] for y in sorted(pf_scores.keys())]]
            fig = go.Figure(go.Bar(
                x=[_yl(y) for y in sorted(pf_scores.keys())],
                y=[pf_scores[y] for y in sorted(pf_scores.keys())],
                marker_color=colors_pf, name="F-Score"
            ))
            fig.update_layout(title="Piotroski F-Score Trend", height=200, yaxis_range=[0, 9], paper_bgcolor="white", plot_bgcolor="#f8fafc", margin=dict(l=40,r=20,t=30,b=30))
            st.plotly_chart(fig, use_container_width=True)


def _render_valuation(pn_result, years):
    """Valuation tab: ReOI valuation, 3 scenarios, V/B ratio."""
    st.markdown("### 💰 ReOI Intrinsic Valuation")

    # Scenario cards
    if pn_result.scenarios:
        scen_cols = st.columns(3)
        scen_colors = {"bear": "#ef4444", "base": "#1e40af", "bull": "#22c55e"}
        scen_icons = {"bear": "🐻", "base": "📊", "bull": "🐂"}

        for i, scen in enumerate(pn_result.scenarios):
            with scen_cols[i]:
                color = scen_colors.get(str(scen.id), "#64748b")
                st.markdown(f"""
                <div class='section-card scen-{scen.id}'>
                <div style='color:{color}; font-weight:700; font-size:1rem;'>
                    {scen_icons.get(str(scen.id), '?')} {scen.label}
                </div>
                <hr style='margin:0.4rem 0; border-color:#e2e8f0;'>
                <div style='font-size:0.8rem;'>
                    <div><strong>Cost of Capital:</strong> {scen.cost_of_capital*100:.1f}%</div>
                    <div><strong>Terminal Growth:</strong> {scen.terminal_growth*100:.1f}%</div>
                    <div style='margin-top:0.5rem; font-size:1.1rem;'>
                        <strong>Intrinsic Value:</strong><br>
                        <span style='font-size:1.2rem; color:{color};'>{format_indian_number(scen.intrinsic_value)}</span>
                    </div>
                    <div><strong>V/NOA₀:</strong> {f"{scen.value_to_book:.2f}x" if scen.value_to_book else "—"}</div>
                    <div><strong>PV(Explicit):</strong> {format_indian_number(scen.pv_explicit)}</div>
                    <div><strong>PV(Terminal):</strong> {format_indian_number(scen.pv_terminal)}</div>
                </div>
                </div>
                """, unsafe_allow_html=True)
                if scen.warnings:
                    for w in scen.warnings:
                        st.warning(w, icon="⚠️")

    st.markdown("---")

    # Base valuation details
    if pn_result.valuation:
        v = pn_result.valuation
        st.markdown("**📐 Base Valuation Detail**")
        col_v1, col_v2, col_v3, col_v4 = st.columns(4)
        col_v1.metric("NOA₀", format_indian_number(v.noa0))
        col_v2.metric("PV(Explicit ReOI)", format_indian_number(v.pv_explicit))
        col_v3.metric("PV(Terminal)", format_indian_number(v.pv_terminal))
        col_v4.metric("Intrinsic Value", format_indian_number(v.intrinsic_value))

        if v.warnings:
            for w in v.warnings:
                st.warning(w)

        # Pro-forma forecast table for base scenario
        base_scen = next((s for s in pn_result.scenarios if s.id == "base"), None)
        if base_scen and base_scen.forecast:
            pf = base_scen.forecast
            st.markdown("**Pro-Forma Forecast (Base)**")
            pf_rows = []
            for i, yr in enumerate(pf.years):
                pf_rows.append({
                    "Period": yr,
                    "Revenue": format_indian_number(pf.revenue[i] if i < len(pf.revenue) else None),
                    "OPM %": f"{pf.opm[i]*100:.1f}%" if i < len(pf.opm) else "—",
                    "NOAT": f"{pf.noat[i]:.2f}" if i < len(pf.noat) else "—",
                    "NOPAT": format_indian_number(pf.nopat[i] if i < len(pf.nopat) else None),
                    "NOA": format_indian_number(pf.noa[i] if i < len(pf.noa) else None),
                    "ReOI": format_indian_number(pf.reoi[i] if i < len(pf.reoi) else None),
                })
            st.dataframe(pd.DataFrame(pf_rows), use_container_width=True, hide_index=True)


def _render_fcf(pn_result, years):
    """FCF & Value Drivers tab."""
    st.markdown("### 💵 Free Cash Flow & Value Drivers")

    if pn_result.fcf:
        st.markdown("**FCF Summary**")
        rows = []
        for metric, series in pn_result.fcf.items():
            if series:
                row = {"Metric": metric}
                for y in years:
                    v = series.get(y)
                    row[_yl(y)] = format_indian_number(v) if v is not None else "—"
                rows.append(row)
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        # FCF chart
        fcf_s = pn_result.fcf.get("Free Cash Flow", {})
        ocf_s = pn_result.fcf.get("Operating Cash Flow", {})
        capex_s = pn_result.fcf.get("Capital Expenditure", {})
        if fcf_s or ocf_s:
            series = {}
            if ocf_s: series["Operating Cash Flow"] = ocf_s
            if capex_s: series["Capital Expenditure"] = {y: -v for y, v in capex_s.items()}
            if fcf_s: series["Free Cash Flow"] = fcf_s
            st.plotly_chart(_build_line(series, "FCF Bridge"), use_container_width=True)

    # Value drivers
    if pn_result.value_drivers:
        st.markdown("**Value Drivers**")
        vd = pn_result.value_drivers
        opm_s = pn_result.ratios.get("OPM %", {})
        noat_s = pn_result.ratios.get("NOAT", {})
        rnoa_s = pn_result.ratios.get("RNOA %", {})

        if opm_s or noat_s:
            fig = go.Figure()
            if opm_s:
                fig.add_trace(go.Scatter(
                    x=[_yl(y) for y in sorted(opm_s)], y=[opm_s[y] for y in sorted(opm_s)],
                    name="OPM %", mode="lines+markers", yaxis="y",
                    line=dict(color="#1e40af", width=2.5)
                ))
            if noat_s:
                fig.add_trace(go.Scatter(
                    x=[_yl(y) for y in sorted(noat_s)], y=[noat_s[y] for y in sorted(noat_s)],
                    name="NOAT", mode="lines+markers", yaxis="y2",
                    line=dict(color="#f59e0b", width=2.5)
                ))
            fig.update_layout(
                title="OPM % (left) vs NOAT (right)",
                yaxis=dict(title="OPM %", side="left"),
                yaxis2=dict(title="NOAT", side="right", overlaying="y"),
                height=280, paper_bgcolor="white", plot_bgcolor="#f8fafc",
                margin=dict(l=50,r=50,t=40,b=30), legend=dict(orientation="h", y=-0.2),
            )
            st.plotly_chart(fig, use_container_width=True)


def _render_mappings(data, mappings, years):
    """Mappings editor tab."""
    st.markdown("### 🗺️ Metric Mappings")
    coverage = get_pattern_coverage(mappings)

    col_m1, col_m2, col_m3 = st.columns(3)
    col_m1.metric("Coverage", f"{coverage['coverage']:.0f}%")
    col_m2.metric("Mapped", coverage["mapped_targets"])
    col_m3.metric("Critical Missing", len(coverage["critical_missing"]))

    if coverage["critical_missing"]:
        st.warning(f"Critical missing: {', '.join(coverage['critical_missing'])}")

    # By statement breakdown
    st.markdown("**Coverage by Statement**")
    for stmt, counts in coverage["by_statement"].items():
        pct = counts["mapped"] / counts["total"] * 100 if counts["total"] > 0 else 0
        icon = {"ProfitLoss": "📋", "BalanceSheet": "🏦", "CashFlow": "💵"}.get(stmt, "📁")
        st.progress(int(pct), text=f"{icon} {stmt}: {counts['mapped']}/{counts['total']} ({pct:.0f}%)")

    st.markdown("---")
    st.markdown("**Current Mappings**")
    rows = [{"Source Metric": metric_label(src), "→ Target": tgt, "Statement": tgt.split("::")[0] if "::" in tgt else "—"}
            for src, tgt in sorted(mappings.items())]
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # Export mappings
    st.download_button(
        "⬇️ Export Mappings (JSON)",
        data=json.dumps(mappings, indent=2),
        file_name="mappings.json",
        mime="application/json",
    )


def _render_data_explorer(data, years):
    """Raw data explorer tab."""
    st.markdown("### 🔍 Raw Data Explorer")

    st.markdown(f"**{len(data)} metrics across {len(years)} years**")

    # Filter
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        search = st.text_input("Search metric names", placeholder="e.g. revenue, assets...")
    with col_f2:
        stmt_filter = st.selectbox("Filter by statement", ["All", "ProfitLoss", "BalanceSheet", "CashFlow", "Financial"])

    filtered_keys = [
        k for k in sorted(data.keys())
        if (not search or search.lower() in k.lower())
        and (stmt_filter == "All" or k.startswith(stmt_filter + "::"))
    ]

    st.markdown(f"Showing **{len(filtered_keys)}** of {len(data)} metrics")

    rows = []
    for k in filtered_keys[:500]:  # Limit for performance
        row = {"Metric": metric_label(k), "Statement": k.split("::")[0] if "::" in k else "—"}
        for y in years:
            v = data[k].get(y)
            row[_yl(y)] = format_indian_number(v) if v is not None else "—"
        rows.append(row)

    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # Export
    all_rows = []
    for k in data:
        row = {"Metric": metric_label(k), "Statement": k.split("::")[0] if "::" in k else ""}
        for y in years:
            v = data[k].get(y)
            row[_yl(y)] = v
        all_rows.append(row)
    csv_bytes = pd.DataFrame(all_rows).to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Export All Data (CSV)", data=csv_bytes, file_name="financial_data.csv", mime="text/csv")


def _render_debug(pn_result, analysis):
    """Debug/diagnostics tab."""
    st.markdown("### 🐛 Diagnostics & Debug")

    if pn_result.diagnostics:
        diag = pn_result.diagnostics

        # Data hygiene
        if diag.data_hygiene:
            st.markdown("**🩺 Data Hygiene**")
            for issue in diag.data_hygiene:
                icon = "🔴" if issue.severity == "critical" else "🟡"
                st.markdown(f"{icon} **{issue.metric}**: missing in {', '.join([_yl(y) for y in issue.missing_years])}")

        # IS reconciliation
        if diag.income_statement_checks:
            st.markdown("**📋 Income Statement Reconciliation**")
            rows = []
            for r in diag.income_statement_checks:
                rows.append({
                    "Year": _yl(r.year),
                    "Expected": format_indian_number(r.expected),
                    "Actual NI": format_indian_number(r.actual),
                    "Gap": format_indian_number(r.gap),
                    "Status": "✅" if r.status == "ok" else "⚠️",
                    "Note": r.note or "",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        # PN reconciliation
        if diag.pn_reconciliation:
            st.markdown("**⚖️ PN Balance Sheet Reconciliation (NOA + NFA = Equity)**")
            rows = []
            for r in diag.pn_reconciliation:
                gap = r.get("gap", 0) or 0
                rows.append({
                    "Year": _yl(r["year"]),
                    "NOA": format_indian_number(r.get("noa")),
                    "NFA": format_indian_number(r.get("nfa")),
                    "Equity": format_indian_number(r.get("equity")),
                    "Gap": format_indian_number(gap),
                    "OK?": "✅" if abs(gap) < 1 else "⚠️",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        # Ratio warnings
        if diag.ratio_warnings:
            st.markdown("**⚠️ Ratio Warnings (Numerical Stability)**")
            for w in diag.ratio_warnings:
                st.warning(f"{_yl(w['year'])}: {w['warning']}")

        # Assumptions
        if diag.assumptions:
            with st.expander(f"📝 Assumptions Made ({sum(len(v) for v in diag.assumptions.values())})"):
                for y, asmp_list in sorted(diag.assumptions.items()):
                    for a in asmp_list:
                        st.markdown(f"• **{_yl(y)}**: {a}")

        # Classification audit
        if diag.classification_audit:
            with st.expander("🔬 Classification Audit (full PN inputs per year)"):
                rows = []
                for r in diag.classification_audit:
                    rows.append({
                        "Year": _yl(r.year),
                        "Mode": r.mode,
                        "InvAsOp": "✅" if r.treat_investments_as_operating else "❌",
                        "Total Assets": format_indian_number(r.total_assets),
                        "Op Assets": format_indian_number(r.operating_assets),
                        "Fin Assets": format_indian_number(r.financial_assets),
                        "NOA": format_indian_number(r.net_operating_assets),
                        "NFA": format_indian_number(r.net_financial_assets),
                        "Equity": format_indian_number(r.equity),
                        "NOPAT": format_indian_number(r.nopat),
                    })
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if analysis.insights:
        with st.expander("💡 All Insights"):
            for ins in analysis.insights:
                st.markdown(f"• {ins}")


# ─── Sample Data Generator ───────────────────────────────────────────────────

def _generate_sample_data() -> FinancialData:
    """Generate realistic Reliance Industries-like sample data."""
    years = ["201903", "202003", "202103", "202203", "202303"]

    # Revenue growth from ~6L Cr to ~9L Cr
    revenues = [622809, 658651, 486326, 792756, 899688]
    net_incomes = [39588, 39880, 53739, 67845, 73670]
    total_assets = [695705, 798226, 1292823, 1479481, 1629003]
    total_equity = [344058, 397432, 636723, 697805, 783099]
    current_assets = [162321, 189432, 296452, 341209, 398023]
    current_liabilities = [143210, 165430, 198432, 242341, 287012]
    lt_debt = [177281, 188078, 196088, 249022, 270323]
    st_debt = [21984, 23421, 31045, 38921, 42310]
    inventory = [69230, 72440, 53210, 95430, 87320]
    receivables = [39230, 42310, 71200, 89230, 102310]
    payables = [72310, 79210, 91230, 114320, 127890]
    ocf = [84132, 77219, 78932, 97232, 102310]
    capex = [116214, 118942, 205121, 182321, 165231]
    interest_exp = [21890, 24201, 28321, 31230, 33210]
    pbt = [51230, 53210, 68392, 85321, 91230]
    tax = [11642, 13230, 14653, 17476, 17560]
    dep = [35210, 38210, 55430, 65210, 70230]
    other_income = [5232, 6210, 8321, 9210, 10232]
    cogs = [504231, 521032, 356021, 621032, 698320]
    share_capital = [6339, 6339, 6763, 6763, 6765]
    retained_earnings = [337719, 391093, 629960, 691042, 776334]
    lt_investments = [50320, 72310, 198321, 221032, 238310]
    cash = [30210, 38321, 62310, 72130, 81210]

    data: FinancialData = {}

    for i, y in enumerate(years):
        def s(key: str, val: float) -> None:
            data.setdefault(key, {})[y] = val

        # P&L
        s("ProfitLoss::Revenue from Operations", revenues[i])
        s("ProfitLoss::Total Revenue", revenues[i] + other_income[i])
        s("ProfitLoss::Other Income", other_income[i])
        s("ProfitLoss::Cost of Materials Consumed", cogs[i])
        s("ProfitLoss::Employee Benefit Expense", revenues[i] * 0.034)
        s("ProfitLoss::Depreciation and Amortisation", dep[i])
        s("ProfitLoss::Finance Costs", interest_exp[i])
        s("ProfitLoss::Total Expenses", cogs[i] + revenues[i] * 0.034 + dep[i] + interest_exp[i] + revenues[i] * 0.02)
        s("ProfitLoss::Profit Before Tax", pbt[i])
        s("ProfitLoss::Tax Expense", tax[i])
        s("ProfitLoss::Profit After Tax", net_incomes[i])

        # Balance Sheet
        s("BalanceSheet::Total Assets", total_assets[i])
        s("BalanceSheet::Total Equity", total_equity[i])
        s("BalanceSheet::Share Capital", share_capital[i])
        s("BalanceSheet::Reserves and Surplus", retained_earnings[i])
        s("BalanceSheet::Current Assets", current_assets[i])
        s("BalanceSheet::Total Current Assets", current_assets[i])
        s("BalanceSheet::Inventories", inventory[i])
        s("BalanceSheet::Trade Receivables", receivables[i])
        s("BalanceSheet::Cash and Cash Equivalents", cash[i])
        s("BalanceSheet::Current Liabilities", current_liabilities[i])
        s("BalanceSheet::Total Current Liabilities", current_liabilities[i])
        s("BalanceSheet::Trade Payables", payables[i])
        s("BalanceSheet::Long Term Borrowings", lt_debt[i])
        s("BalanceSheet::Short Term Borrowings", st_debt[i])
        s("BalanceSheet::Non-Current Assets", total_assets[i] - current_assets[i])
        s("BalanceSheet::Non-Current Liabilities", lt_debt[i] + total_assets[i] * 0.05)
        s("BalanceSheet::Investments - Long-term", lt_investments[i])

        # Cash Flow
        s("CashFlow::Net Cash from Operating Activities", ocf[i])
        s("CashFlow::Purchase of Property Plant and Equipment", -capex[i])
        s("CashFlow::Net Cash from Investing Activities", -capex[i] * 1.2)
        s("CashFlow::Net Cash from Financing Activities", -(ocf[i] - capex[i]) * 0.3)
        s("CashFlow::Cash and Cash Equivalents at End of the year", cash[i])
        s("CashFlow::Cash and Cash Equivalents at Beginning of the year", cash[max(0, i - 1)])

    return data


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1: UPLOAD
# ═══════════════════════════════════════════════════════════════════════════════

if st.session_state["step"] == "upload":
    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown("### 📁 Upload Financial Statements")
        st.markdown("""
        <div style='background:#eff6ff; border-radius:8px; padding:0.8rem 1rem; margin-bottom:1rem;
                    border-left:4px solid #1e40af; font-size:0.85rem; color:#1e40af;'>
        <strong>Supported formats:</strong> Excel (.xlsx, .xls) • CSV (.csv) • HTML tables (Capitaline export) • ZIP bundles (.zip)
        <br><strong>Multi-sheet:</strong> P&L, Balance Sheet, Cash Flow in one file or multiple files
        </div>
        """, unsafe_allow_html=True)

        company_name_input = st.text_input(
            "Company Name",
            placeholder="e.g. Reliance Industries Ltd",
            help="Enter the company name for labeling the analysis"
        )

        uploaded_files = st.file_uploader(
            "Upload financial statement files",
            accept_multiple_files=True,
            type=["xlsx", "xls", "csv", "html", "htm", "zip"],
            label_visibility="collapsed",
        )

        if uploaded_files:
            datasets = []
            with st.spinner("Parsing files..."):
                for f in uploaded_files:
                    try:
                        file_bytes = f.read()
                        expanded_files = expand_uploaded_files(file_bytes, f.name)

                        if f.name.lower().endswith(".zip") and not expanded_files:
                            st.warning(f"⚠️ {f.name}: ZIP contains no supported statement files")

                        for inner_name, inner_bytes in expanded_files:
                            file_data, file_years = parse_file(inner_bytes, inner_name)
                            display_name = inner_name if inner_name == f.name else f"{f.name} → {inner_name}"
                            if file_data:
                                datasets.append((file_data, display_name))
                                st.success(f"✅ {display_name}: {len(file_data)} metrics, {len(file_years)} years")
                            else:
                                st.warning(f"⚠️ {display_name}: No data extracted")
                    except Exception as e:
                        st.error(f"❌ {f.name}: {e}")

            if datasets:
                merged_data, merged_years, debug_info = merge_financial_data(datasets)
                if st.button("▶ Continue to Mapping", type="primary", use_container_width=True):
                    st.session_state.update({
                        "step": "mapping",
                        "data": merged_data,
                        "years": merged_years,
                        "company_name": company_name_input or "Company",
                        "mappings": None,
                    })
                    st.rerun()

    with col2:
        st.markdown("### 📋 What This Platform Does")
        st.markdown("""
        <div class='section-card' style='font-size:0.82rem;'>
        <div style='margin-bottom:0.5rem;'><strong>🔬 Penman-Nissim Framework</strong><br>
        Balance sheet & income statement reformulation, NOA/NFA/NOPAT computation</div>
        <div style='margin-bottom:0.5rem;'><strong>📈 ReOI Valuation</strong><br>
        V = NOA₀ + PV(Explicit ReOI) + PV(Terminal), 3 scenario analysis</div>
        <div style='margin-bottom:0.5rem;'><strong>🎯 Accrual Quality</strong><br>
        Shapley 3-factor NOPAT attribution, earnings quality tiers</div>
        <div style='margin-bottom:0.5rem;'><strong>🛡️ Scoring Models</strong><br>
        Altman Z-Score (distress) + Piotroski F-Score (quality)</div>
        <div style='margin-bottom:0.5rem;'><strong>🏢 Smart Detection</strong><br>
        Auto holding/investment company identification with adjusted PN framework</div>
        <div><strong>📊 Capitaline Native</strong><br>
        90+ pattern auto-mapper for Capitaline export formats</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("### 🔧 Sample Data")
        if st.button("Load Reliance Sample Data", use_container_width=True):
            # Generate realistic sample data
            sample_data = _generate_sample_data()
            st.session_state.update({
                "step": "mapping",
                "data": sample_data,
                "years": ["201903", "202003", "202103", "202203", "202303"],
                "company_name": "Reliance Industries Ltd (Sample)",
                "mappings": None,
            })
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2: MAPPING EDITOR
# ═══════════════════════════════════════════════════════════════════════════════

elif st.session_state["step"] == "mapping":
    data: FinancialData = st.session_state["data"]
    years = st.session_state["years"]
    company_name = st.session_state["company_name"]

    st.markdown(f"### 🗺️ Metric Mapping — {company_name}")
    st.markdown(f"""
    <div style='background:#eff6ff; border-radius:8px; padding:0.7rem 1rem; margin-bottom:1rem;
                font-size:0.82rem; color:#1e40af; border-left:4px solid #1e40af;'>
    <strong>{len(data)}</strong> raw metrics detected across <strong>{len(years)}</strong> periods.
    Auto-mapper has applied fuzzy pattern matching. Review mappings below and adjust if needed.
    </div>
    """, unsafe_allow_html=True)

    # Run auto-mapper
    source_metrics = list(data.keys())
    auto_mappings, unmapped = auto_map_metrics(source_metrics)
    
    if st.session_state.get("mappings") is None:
        st.session_state["mappings"] = dict(auto_mappings)

    current_mappings = st.session_state["mappings"]
    coverage = get_pattern_coverage(current_mappings)
    all_targets = [""] + sorted(get_all_targets())

    col_stats = st.columns(4)
    col_stats[0].metric("Total Metrics", len(data))
    col_stats[1].metric("Auto-Mapped", len(current_mappings), f"{coverage['coverage']:.0f}% coverage")
    col_stats[2].metric("Unmapped", len(unmapped))
    col_stats[3].metric("Critical Missing", len(coverage["critical_missing"]))

    if coverage["critical_missing"]:
        st.warning(f"⚠️ Critical metrics missing: {', '.join(coverage['critical_missing'])}")

    st.markdown("---")

    # Filter
    filter_col, btn_col = st.columns([3, 1])
    with filter_col:
        search_filter = st.text_input("Search metrics", placeholder="Filter by name...")
    with btn_col:
        show_unmapped_only = st.checkbox("Unmapped only", value=False)

    # Render mapping table
    filtered = {
        src: tgt for src, tgt in current_mappings.items()
        if (not search_filter or search_filter.lower() in src.lower())
        and (not show_unmapped_only or tgt == "")
    }
    unmapped_filtered = [
        s for s in unmapped
        if (not search_filter or search_filter.lower() in s.lower())
    ] if show_unmapped_only or not search_filter else []

    # Mapped metrics editor
    if filtered or not show_unmapped_only:
        st.markdown("**✅ Auto-Mapped Metrics**")
        changed = False
        for src in list(current_mappings.keys()):
            if search_filter and search_filter.lower() not in src.lower():
                continue
            col1, col2 = st.columns([2, 2])
            with col1:
                st.text(metric_label(src))
            with col2:
                current_tgt = current_mappings.get(src, "")
                idx = all_targets.index(current_tgt) if current_tgt in all_targets else 0
                new_tgt = st.selectbox(
                    f"##tgt_{src}", all_targets, index=idx, key=f"map_{src}",
                    label_visibility="collapsed"
                )
                if new_tgt != current_tgt:
                    if new_tgt == "":
                        del current_mappings[src]
                    else:
                        # Remove existing mapping to same target
                        to_remove = [k for k, v in current_mappings.items() if v == new_tgt and k != src]
                        for k in to_remove: del current_mappings[k]
                        current_mappings[src] = new_tgt
                    changed = True

    # Unmapped metrics
    if unmapped:
        with st.expander(f"🔴 Unmapped Metrics ({len(unmapped)})"):
            for src in unmapped:
                if search_filter and search_filter.lower() not in src.lower():
                    continue
                col1, col2 = st.columns([2, 2])
                with col1:
                    st.text(metric_label(src))
                with col2:
                    new_tgt = st.selectbox(
                        f"##tgt_{src}", all_targets, index=0, key=f"map_u_{src}",
                        label_visibility="collapsed"
                    )
                    if new_tgt:
                        current_mappings[src] = new_tgt
                        unmapped.remove(src) if src in unmapped else None

    st.markdown("---")
    col_btn1, col_btn2 = st.columns([1, 3])
    with col_btn1:
        if st.button("← Back to Upload"):
            st.session_state["step"] = "upload"
            st.rerun()
    with col_btn2:
        if st.button("▶ Run Analysis", type="primary", use_container_width=True):
            st.session_state["mappings"] = current_mappings
            st.session_state["step"] = "dashboard"
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3: DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

elif st.session_state["step"] == "dashboard":
    data: FinancialData = st.session_state["data"]
    mappings: MappingDict = st.session_state["mappings"]
    company_name: str = st.session_state["company_name"]
    years: List[str] = get_years(data)

    # ── Build results ─────────────────────────────────────────────────────────
    @st.cache_data(ttl=60)
    def _run_analysis(_data_key: str, _map_key: str):
        return analyze_financials(data, mappings)

    @st.cache_data(ttl=60)
    def _run_pn(_data_key: str, _map_key: str, r: float, g: float, n: int, meth: str, strict: bool, mode: str):
        return penman_nissim_analysis(data, mappings, PNOptions(
            strict_mode=strict,
            classification_mode=mode,  # type: ignore
            cost_of_capital=r / 100,
            terminal_growth=g / 100,
            forecast_years=n,
            forecast_method=meth,  # type: ignore
        ))

    @st.cache_data(ttl=60)
    def _run_scoring(_data_key: str, _map_key: str):
        return calculate_scores(data, mappings)

    _data_key = str(id(data))
    _map_key = str(sorted(mappings.items()))

    analysis = _run_analysis(_data_key, _map_key)
    pn_result = _run_pn(
        _data_key, _map_key,
        st.session_state["pn_cost_of_capital"],
        st.session_state["pn_terminal_growth"],
        st.session_state["pn_forecast_years"],
        st.session_state["pn_forecast_method"],
        st.session_state["pn_strict_mode"],
        st.session_state["pn_classification_mode"],
    )
    scoring = _run_scoring(_data_key, _map_key)

    # ── Company header ────────────────────────────────────────────────────────
    col_h1, col_h2, col_h3, col_h4, col_h5 = st.columns(5)
    col_h1.metric("Company", company_name[:20] + "…" if len(company_name) > 20 else company_name)
    col_h2.metric("Metrics", analysis.summary.total_metrics)
    col_h3.metric("Years", f"{analysis.summary.years_covered} ({analysis.summary.year_range})")
    col_h4.metric("Data Quality", f"{analysis.summary.completeness:.0f}%")
    col_h5.metric("Mapped", len(mappings))

    st.markdown("---")

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tabs = st.tabs([
        "🏠 Overview", "📐 Penman-Nissim", "📊 Ratios", "📈 Trends",
        "🛡️ Scoring", "💰 Valuation", "💵 FCF & Value Drivers",
        "🗺️ Mappings", "🔍 Data Explorer", "🐛 Debug",
    ])

    # ──────────────────────────────────────────────────────────────────────────
    # TAB 1: OVERVIEW
    # ──────────────────────────────────────────────────────────────────────────
    with tabs[0]:
        _render_overview(analysis, pn_result, scoring, years, data, mappings)

    # ──────────────────────────────────────────────────────────────────────────
    # TAB 2: PENMAN-NISSIM
    # ──────────────────────────────────────────────────────────────────────────
    with tabs[1]:
        _render_penman_nissim(pn_result, years)

    # ──────────────────────────────────────────────────────────────────────────
    # TAB 3: RATIOS
    # ──────────────────────────────────────────────────────────────────────────
    with tabs[2]:
        _render_ratios(analysis, pn_result, years)

    # ──────────────────────────────────────────────────────────────────────────
    # TAB 4: TRENDS
    # ──────────────────────────────────────────────────────────────────────────
    with tabs[3]:
        _render_trends(analysis, years)

    # ──────────────────────────────────────────────────────────────────────────
    # TAB 5: SCORING
    # ──────────────────────────────────────────────────────────────────────────
    with tabs[4]:
        _render_scoring(scoring, years)

    # ──────────────────────────────────────────────────────────────────────────
    # TAB 6: VALUATION
    # ──────────────────────────────────────────────────────────────────────────
    with tabs[5]:
        _render_valuation(pn_result, years)

    # ──────────────────────────────────────────────────────────────────────────
    # TAB 7: FCF & VALUE DRIVERS
    # ──────────────────────────────────────────────────────────────────────────
    with tabs[6]:
        _render_fcf(pn_result, years)

    # ──────────────────────────────────────────────────────────────────────────
    # TAB 8: MAPPINGS
    # ──────────────────────────────────────────────────────────────────────────
    with tabs[7]:
        _render_mappings(data, mappings, years)

    # ──────────────────────────────────────────────────────────────────────────
    # TAB 9: DATA EXPLORER
    # ──────────────────────────────────────────────────────────────────────────
    with tabs[8]:
        _render_data_explorer(data, years)

    # ──────────────────────────────────────────────────────────────────────────
    # TAB 10: DEBUG
    # ──────────────────────────────────────────────────────────────────────────
    with tabs[9]:
        _render_debug(pn_result, analysis)


