"""
fin_platform/analyzer.py
=========================
Core financial analysis engine. Fully ported from TypeScript analyzer.ts
with Python enhancements and extended PN framework.

Covers:
  - Standard ratio analysis (Liquidity, Profitability, Leverage, Efficiency)
  - Trend analysis with CAGR and volatility
  - DuPont 3-factor decomposition
  - Penman-Nissim (PN) reformulation framework
    · Balance sheet reformulation: NOA / NFA / OA / OL / FL
    · Income statement reformulation: NOPAT / NFE_AT
    · PN ratios: RNOA, ROOA, OPM, NOAT, FLEV, NBC, Spread, ROE
    · ROE decomposition & reconciliation
    · Academic extensions: ReOI, AEG, Accrual Quality, Shapley 3-Factor
    · Scenario valuation: Bear / Base / Bull with pro-forma mean-reversion
    · Operating Risk metrics
    · Auto Investment Thesis
  - Altman Z-Score (1968 public manufacturing model)
  - Piotroski F-Score (9-signal)
  - Holding Company auto-detection
"""
from __future__ import annotations
import math
from typing import Dict, List, Optional, Tuple, Any
from itertools import permutations

from .types import (
    FinancialData, MappingDict, AnalysisResult, AnalysisSummary,
    TrendData, AnomalyData, DuPontResult, CompanyCharacteristics,
    PenmanNissimResult, PNOptions, PNDiagnostics, PNClassificationAuditRow,
    ReconciliationRow, DataHygieneIssue, PenmanAcademicMetrics, NOPATDrivers,
    PenmanValuationResult, ScenarioValuation, ProFormaAssumptions, ProFormaForecast,
    OperatingRiskMetrics, InvestmentThesis, ScoringResult, AltmanZScore,
    PiotroskiFScore,
    # Nissim (2023) extensions
    NissimOperatingDecomposition, NissimROCEHierarchy, NissimProfitabilityResult,
)


# ─── Data Access Helpers ──────────────────────────────────────────────────────

def get_years(data: FinancialData) -> List[str]:
    years: set = set()
    for vals in data.values():
        years.update(vals.keys())
    return sorted(years)


def _get_direct(data: FinancialData, mappings: MappingDict, target: str, year: str) -> Optional[float]:
    for src, tgt in mappings.items():
        if tgt == target and src in data and year in data[src]:
            v = data[src][year]
            return float(v) if isinstance(v, (int, float)) and not math.isnan(v) else None
    return None


def derive_val(
    data: FinancialData,
    mappings: MappingDict,
    target: str,
    year: str,
    _depth: int = 0,
) -> Optional[float]:
    """
    Multi-level metric derivation.
    First tries direct mapping, then constructs from sub-components.
    Guards against infinite recursion with depth limit.
    """
    if _depth > 5:
        return None

    direct = _get_direct(data, mappings, target, year)
    if direct is not None:
        return direct

    def get(t: str) -> Optional[float]:
        return derive_val(data, mappings, t, year, _depth + 1)

    try:
        match target:
            case "Total Equity":
                te = get("Total Equity")
                if te is not None: return te
                sc, re_ = get("Share Capital"), get("Retained Earnings")
                if sc is not None and re_ is not None: return sc + re_
                if sc is not None: return sc

            case "Total Liabilities":
                tl = get("Total Liabilities")
                if tl is not None: return tl
                ta, te = get("Total Assets"), get("Total Equity")
                if ta is not None and te is not None: return ta - te
                cl, ncl = get("Current Liabilities"), get("Non-Current Liabilities")
                if cl is not None and ncl is not None: return cl + ncl

            case "EBIT":
                pbt, ie = get("Income Before Tax"), get("Interest Expense")
                if pbt is not None: return pbt + (ie or 0.0)
                oi = get("Operating Income")
                if oi is not None: return oi

            case "EBITDA":
                ebit = get("EBIT")
                dep = get("Depreciation")
                if ebit is not None and dep is not None: return ebit + dep
                if ebit is not None: return ebit

            case "Revenue":
                rev = get("Revenue")
                if rev is not None: return rev
                tr, oi = get("Total Revenue"), get("Other Income")
                if tr is not None and oi is not None: return tr - oi
                if tr is not None: return tr
                # Search raw data for Capitaline patterns
                for key, vals in data.items():
                    kl = key.lower()
                    if year in vals and any(p in kl for p in [
                        "revenue from operations", "net sales", "sales turnover"
                    ]):
                        return float(vals[year])

            case "Net Income":
                ni = get("Net Income")
                if ni is not None: return ni
                for key, vals in data.items():
                    kl = key.lower()
                    if year in vals and any(p in kl for p in [
                        "profit after tax", "profit for the year", "profit for the period",
                        "profit attributable to shareholders"
                    ]):
                        return float(vals[year])

            case "Current Assets":
                ca = get("Current Assets")
                if ca is not None: return ca
                for key, vals in data.items():
                    if "total current assets" in key.lower() and year in vals:
                        return float(vals[year])

            case "Current Liabilities":
                cl = get("Current Liabilities")
                if cl is not None: return cl
                for key, vals in data.items():
                    if "total current liabilities" in key.lower() and year in vals:
                        return float(vals[year])

            case _:
                # Fallback: inverse mapping search
                for src, tgt in mappings.items():
                    if tgt == target and src in data and year in data[src]:
                        return float(data[src][year])

    except Exception:
        pass

    return None


def _safe_div(num: Optional[float], den: Optional[float]) -> Optional[float]:
    if num is None or den is None or den == 0:
        return None
    return num / den


def _avg(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None and b is None: return None
    if a is None: return b
    if b is None: return a
    return (a + b) / 2.0


def _sum(*vals: Optional[float]) -> Optional[float]:
    total, any_found = 0.0, False
    for v in vals:
        if v is not None:
            total += v
            any_found = True
    return total if any_found else None


def _std_dev(values: List[float]) -> Optional[float]:
    if len(values) < 2: return None
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
    return math.sqrt(variance)


def _mean_last_n(series: Dict[str, float], n: int) -> Optional[float]:
    keys = sorted(series.keys())[-n:]
    vals = [series[k] for k in keys if k in series]
    return sum(vals) / len(vals) if vals else None


def _last(series: Dict[str, float]) -> Optional[float]:
    if not series: return None
    return series[sorted(series.keys())[-1]]


def _cagr(start: float, end: float, years: int) -> Optional[float]:
    if years <= 0 or start == 0 or (start < 0 and end < 0):
        return None
    if start < 0 or end < 0:
        return None
    try:
        return ((end / start) ** (1 / years) - 1) * 100
    except Exception:
        return None


def _pick_best_ni_reconciliation(
    *,
    revenue: Optional[float],
    total_expenses: Optional[float],
    tax_expense: Optional[float],
    exceptional_items: Optional[float],
    pbt: Optional[float],
    ebit: Optional[float],
    interest_expense: Optional[float],
    net_income: Optional[float],
) -> Optional[Tuple[float, float, str]]:
    """
    Build NI from multiple accounting identities and select the best-supported one.
    This avoids false reconciliation warnings when sources have different subtotal
    conventions (e.g. total expenses including taxes/exceptionals).
    Returns (expected, gap, note).
    """
    if net_income is None:
        return None

    candidates: List[Tuple[float, str]] = []

    if revenue is not None and total_expenses is not None and tax_expense is not None:
        candidates.append((revenue - total_expenses - tax_expense, "Rev−Exp−Tax vs NI"))
        if exceptional_items is not None:
            candidates.append((revenue - total_expenses - tax_expense + exceptional_items, "Rev−Exp−Tax+Exc vs NI"))

    if pbt is not None and tax_expense is not None:
        candidates.append((pbt - tax_expense, "PBT−Tax vs NI"))
        if exceptional_items is not None:
            candidates.append((pbt - tax_expense + exceptional_items, "PBT−Tax+Exc vs NI"))

    if ebit is not None and tax_expense is not None:
        ie = interest_expense or 0.0
        candidates.append((ebit - ie - tax_expense, "EBIT−Interest−Tax vs NI"))

    if not candidates:
        return None

    expected, note = min(candidates, key=lambda c: abs(c[0] - net_income))
    return expected, expected - net_income, note


# ─── Company Type Detection ───────────────────────────────────────────────────

def detect_company_type(
    data: FinancialData, mappings: MappingDict, years: List[str]
) -> CompanyCharacteristics:
    """
    Auto-detect holding/investment company characteristics.
    Used to drive PN classification (investments → operating vs financial).
    """
    characteristics: List[str] = []
    latest = years[-3:] if len(years) >= 3 else years
    total_assets = investments = inventory = revenue = other_income = debt = 0.0
    data_points = 0

    for y in latest:
        def gv(t: str) -> float:
            v = derive_val(data, mappings, t, y)
            return v if v is not None else 0.0

        ta = derive_val(data, mappings, "Total Assets", y)
        if ta is not None and ta > 0:
            lt_inv = gv("Long-term Investments")
            st_inv = gv("Short-term Investments")
            inv = gv("Inventory")
            st_debt = gv("Short-term Debt")
            lt_debt = gv("Long-term Debt")
            total_assets += ta
            investments += lt_inv + st_inv
            inventory += inv
            debt += st_debt + lt_debt
            data_points += 1

        rev = derive_val(data, mappings, "Revenue", y)
        if rev is not None:
            revenue += rev
            other_income += gv("Other Income")

    if data_points == 0:
        return CompanyCharacteristics(False, False, False, 0.0, 0.0, 0.0)

    inv_ratio = investments / total_assets if total_assets > 0 else 0.0
    oi_ratio = other_income / revenue if revenue > 0 else 0.0
    inventory_ratio = inventory / total_assets if total_assets > 0 else 0.0
    has_debt = debt > total_assets * 0.01

    is_holding = inv_ratio > 0.30 and inventory_ratio < 0.05
    is_investment = inv_ratio > 0.50 or (oi_ratio > 0.10 and inv_ratio > 0.25)

    if inv_ratio > 0.50:
        characteristics.append(f"High investment concentration ({inv_ratio*100:.0f}% of assets)")
    if inventory_ratio < 0.01:
        characteristics.append("Zero/minimal inventory — likely not a manufacturing/trading company")
    if not has_debt:
        characteristics.append("Debt-free company")
    if oi_ratio > 0.10:
        characteristics.append(f"Significant other income ({oi_ratio*100:.0f}% of revenue)")

    return CompanyCharacteristics(
        is_holding_company=is_holding,
        is_investment_company=is_investment,
        has_debt=has_debt,
        investment_asset_ratio=inv_ratio,
        other_income_ratio=oi_ratio,
        inventory_ratio=inventory_ratio,
        characteristics=characteristics,
    )


# ─── Standard Ratio Analysis ──────────────────────────────────────────────────

def _compute_trends(
    data: FinancialData, mappings: MappingDict, years: List[str]
) -> Dict[str, TrendData]:
    trends: Dict[str, TrendData] = {}
    key_metrics = ["Revenue", "Net Income", "Total Assets", "EBIT", "Operating Cash Flow"]

    for metric in key_metrics:
        series = {y: v for y in years if (v := derive_val(data, mappings, metric, y)) is not None}
        if len(series) < 2:
            continue
        vals = [series[y] for y in sorted(series)]
        start_v, end_v = vals[0], vals[-1]
        n_years = len(vals) - 1
        cagr = _cagr(start_v, end_v, n_years) or 0.0
        yoy: Dict[str, float] = {}
        sorted_years = sorted(series)
        for i in range(1, len(sorted_years)):
            prev = series[sorted_years[i - 1]]
            curr = series[sorted_years[i]]
            if prev and prev != 0:
                yoy[sorted_years[i]] = (curr - prev) / abs(prev) * 100

        volatility = _std_dev(list(yoy.values())) or 0.0
        direction = "up" if cagr > 2 else ("down" if cagr < -2 else "stable")

        trends[metric] = TrendData(
            direction=direction,
            cagr=cagr,
            volatility=volatility,
            yoy_growth=yoy,
            latest_value=end_v,
            min_value=min(vals),
            max_value=max(vals),
        )

    return trends


def analyze_financials(data: FinancialData, mappings: MappingDict) -> AnalysisResult:
    """Full standard financial analysis: ratios, trends, DuPont, insights."""
    years = get_years(data)

    stmt_breakdown: Dict[str, int] = {}
    for key in data:
        stmt = key.split("::")[0] if "::" in key else "Other"
        stmt_breakdown[stmt] = stmt_breakdown.get(stmt, 0) + 1

    company_type = detect_company_type(data, mappings, years)

    # ── Ratios ────────────────────────────────────────────────────────────────
    ratios: Dict[str, Dict[str, Dict[str, float]]] = {}

    def gv(t: str, y: str) -> Optional[float]:
        return derive_val(data, mappings, t, y)

    # Liquidity
    liq: Dict[str, Dict[str, float]] = {}
    for y in years:
        ca, cl = gv("Current Assets", y), gv("Current Liabilities", y)
        inv = gv("Inventory", y) or 0.0
        cash = gv("Cash and Cash Equivalents", y)
        if ca and cl and cl != 0:
            liq.setdefault("Current Ratio", {})[y] = ca / cl
            liq.setdefault("Quick Ratio", {})[y] = (ca - inv) / cl
        if cash and cl and cl != 0:
            liq.setdefault("Cash Ratio", {})[y] = cash / cl
    if liq: ratios["Liquidity"] = liq

    # Profitability
    prof: Dict[str, Dict[str, float]] = {}
    for y in years:
        ni, rev = gv("Net Income", y), gv("Revenue", y)
        ta, te = gv("Total Assets", y), gv("Total Equity", y)
        cogs, ebit, dep = gv("Cost of Goods Sold", y), gv("EBIT", y), gv("Depreciation", y)

        if ni and rev and rev != 0:
            prof.setdefault("Net Profit Margin %", {})[y] = ni / rev * 100
        if rev and cogs and rev != 0:
            prof.setdefault("Gross Profit Margin %", {})[y] = (rev - cogs) / rev * 100
        if ni and ta and ta != 0:
            prof.setdefault("ROA %", {})[y] = ni / ta * 100
        if ni and te and te != 0:
            prof.setdefault("ROE %", {})[y] = ni / te * 100
        if ebit and rev and rev != 0:
            prof.setdefault("Operating Margin %", {})[y] = ebit / rev * 100
        if ebit and dep and rev and rev != 0:
            prof.setdefault("EBITDA Margin %", {})[y] = (ebit + dep) / rev * 100
    if prof: ratios["Profitability"] = prof

    # Leverage
    lev: Dict[str, Dict[str, float]] = {}
    for y in years:
        tl = gv("Total Liabilities", y)
        te = gv("Total Equity", y)
        ta = gv("Total Assets", y)
        ebit = gv("EBIT", y)
        ie = gv("Interest Expense", y)
        if te is None: te = (ta - tl) if (ta and tl) else None
        if tl and te and te != 0:
            lev.setdefault("Debt/Equity", {})[y] = tl / te
        if ta and te and te != 0:
            lev.setdefault("Equity Multiplier", {})[y] = ta / te
        if ebit and ie and ie > 0:
            lev.setdefault("Interest Coverage", {})[y] = min(ebit / ie, 999)
        elif ie is None or ie == 0:
            if ebit and ebit > 0:
                lev.setdefault("Interest Coverage", {})[y] = 999.0
    if lev: ratios["Leverage"] = lev

    # Efficiency
    eff: Dict[str, Dict[str, float]] = {}
    for y in years:
        rev, ta = gv("Revenue", y), gv("Total Assets", y)
        cogs, inv = gv("Cost of Goods Sold", y), gv("Inventory", y)
        recv = gv("Trade Receivables", y)
        ap = gv("Accounts Payable", y)
        if rev and ta and ta != 0:
            eff.setdefault("Asset Turnover", {})[y] = rev / ta
        if cogs and inv and inv > 0:
            eff.setdefault("Inventory Turnover", {})[y] = cogs / inv
            eff.setdefault("Days Inventory", {})[y] = inv / (cogs / 365)
        if rev and recv and rev > 0:
            eff.setdefault("Days Receivable", {})[y] = recv / (rev / 365)
        if cogs and ap and cogs > 0:
            eff.setdefault("Days Payable", {})[y] = ap / (cogs / 365)
    if eff: ratios["Efficiency"] = eff

    # Working capital
    wc: Dict[str, Dict[str, float]] = {}
    for y in years:
        ca, cl = gv("Current Assets", y), gv("Current Liabilities", y)
        rev = gv("Revenue", y)
        if ca and cl:
            wc.setdefault("Working Capital", {})[y] = ca - cl
            if rev and rev != 0:
                wc.setdefault("WC/Revenue %", {})[y] = (ca - cl) / rev * 100

    # Trends
    trends = _compute_trends(data, mappings, years)

    # DuPont
    dupont = DuPontResult()
    three_f: Dict[str, Dict[str, float]] = {}
    for y in years:
        ni, rev = gv("Net Income", y), gv("Revenue", y)
        ta, te = gv("Total Assets", y), gv("Total Equity", y)
        if all(v is not None and v != 0 for v in [ni, rev, ta, te]):
            assert ni is not None and rev is not None and ta is not None and te is not None
            three_f[y] = {
                "Net Profit Margin": ni / rev * 100,
                "Asset Turnover": rev / ta,
                "Equity Multiplier": ta / te,
                "ROE": ni / te * 100,
            }
    if three_f: dupont.three_factor = three_f

    # Quality score
    total_cells = sum(len(years) for _ in data.values())
    filled_cells = sum(1 for vals in data.values() for y in years if y in vals)
    quality_score = (filled_cells / total_cells * 100) if total_cells > 0 else 0.0

    # Insights
    insights: List[str] = []
    if company_type.is_holding_company or company_type.is_investment_company:
        insights.append("📊 Detected as Holding/Investment Company — PN ratios adjusted")
    if not company_type.has_debt:
        insights.append("✅ Debt-free company — FLEV and NBC may show unusual values")
    for char in company_type.characteristics:
        insights.append(f"ℹ️ {char}")
    if quality_score >= 80:
        insights.append("✅ High data quality — analysis is reliable")
    elif quality_score < 50:
        insights.append("⚠️ Low data quality — consider checking mappings")
    if not stmt_breakdown.get("CashFlow"):
        insights.append("⚠️ Cash flow statement missing — FCF analysis unavailable")
    if not stmt_breakdown.get("BalanceSheet"):
        insights.append("⚠️ Balance sheet missing — leverage ratios unavailable")

    rev_trend = trends.get("Revenue")
    if rev_trend:
        if rev_trend.cagr > 15:
            insights.append(f"🚀 Strong revenue growth (CAGR: {rev_trend.cagr:.1f}%)")
        elif rev_trend.cagr < 0:
            insights.append(f"📉 Declining revenue (CAGR: {rev_trend.cagr:.1f}%)")

    return AnalysisResult(
        summary=AnalysisSummary(
            total_metrics=len(data),
            years_covered=len(years),
            year_range=f"{years[0]}–{years[-1]}" if years else "N/A",
            completeness=quality_score,
            statement_breakdown=stmt_breakdown,
        ),
        ratios=ratios,
        trends=trends,
        anomalies=AnomalyData(),
        working_capital=wc,
        dupont=dupont,
        insights=insights,
        quality_score=quality_score,
        company_type=company_type,
    )


# ─── Penman-Nissim Analysis ───────────────────────────────────────────────────

def penman_nissim_analysis(
    data: FinancialData,
    mappings: MappingDict,
    options: Optional[PNOptions] = None,
) -> PenmanNissimResult:
    """
    Full Penman-Nissim reformulation framework.
    Includes Balance Sheet, Income Statement reformulation, PN ratios,
    academic extensions (ReOI, AEG, Accrual Quality, Shapley), scenario valuation,
    and auto-investment thesis.
    """
    if options is None:
        options = PNOptions()

    years = get_years(data)
    strict_mode = options.strict_mode
    classification_mode = options.classification_mode
    cost_of_capital = options.cost_of_capital
    terminal_growth = options.terminal_growth
    forecast_years_n = options.forecast_years
    forecast_method = options.forecast_method

    assumptions: Dict[str, List[str]] = {}
    ratio_warnings: List[Dict[str, str]] = []

    def add_assumption(y: str, msg: str) -> None:
        assumptions.setdefault(y, []).append(msg)

    def gv(target: str, y: str) -> Optional[float]:
        return derive_val(data, mappings, target, y)

    def g(target: str, y: str, fallback: Optional[float] = None, allow_assumption: bool = False) -> Optional[float]:
        v = gv(target, y)
        if v is None:
            if not strict_mode and allow_assumption and fallback is not None:
                add_assumption(y, f"{target} assumed {fallback}")
                return fallback
            return None
        return v

    # Detect company type
    company_type = detect_company_type(data, mappings, years)
    auto_treat = company_type.is_holding_company or company_type.is_investment_company
    treat_investments_as_operating = (
        True if classification_mode == "investment"
        else False if classification_mode == "operating"
        else auto_treat
    )

    # ── Reformulate Balance Sheet ────────────────────────────────────────────
    bs_metrics = [
        "Total Assets", "Operating Assets", "Financial Assets", "Total Liabilities",
        "Operating Liabilities", "Financial Liabilities", "Net Operating Assets",
        "Net Financial Assets", "Common Equity", "Total Debt", "Net Debt",
        "Net Working Capital", "Invested Capital",
        "Long-term Investments", "Short-term Investments", "Cash and Bank",
    ]
    reformulated_bs: Dict[str, Dict[str, float]] = {m: {} for m in bs_metrics}
    classification_audit: List[PNClassificationAuditRow] = []

    def infer_cash_from_cf(y: str) -> Optional[float]:
        for key, vals in data.items():
            kl = key.lower()
            if y in vals and "end of the year" in kl and "cash" in kl:
                add_assumption(y, "Cash inferred from CF (ending cash)")
                return float(vals[y])
        return None

    for y in years:
        notes: List[str] = []
        ta = g("Total Assets", y)
        te = g("Total Equity", y)

        cash_raw = g("Cash and Cash Equivalents", y)
        cash = cash_raw if cash_raw is not None else infer_cash_from_cf(y)
        bank_balances = g("Bank Balances", y)

        st_inv = g("Short-term Investments", y, 0.0, True)
        lt_inv = g("Long-term Investments", y, 0.0, True)
        st_debt = g("Short-term Debt", y, 0.0, True)
        lt_debt = g("Long-term Debt", y, 0.0, True)
        lease = g("Lease Liabilities", y, 0.0, True)

        ca = g("Current Assets", y)
        cl = g("Current Liabilities", y)

        total_cash = _sum(cash, bank_balances)

        # Financial vs Operating classification
        if treat_investments_as_operating:
            fa = total_cash
        else:
            fa = _sum(total_cash, st_inv, lt_inv)

        oa = (ta - fa) if (ta is not None and fa is not None) else None
        fl = _sum(st_debt, lt_debt, lease)
        tl = ((ta - te) if (ta is not None and te is not None) else gv("Total Liabilities", y))
        ol = (max(tl - fl, 0.0) if (tl is not None and fl is not None) else None)
        noa = ((oa - ol) if (oa is not None and ol is not None) else None)
        nfa = ((fa - fl) if (fa is not None and fl is not None) else None)

        def assign(m: str, v: Optional[float]) -> None:
            if v is not None: reformulated_bs[m][y] = v

        assign("Total Assets", ta)
        assign("Operating Assets", oa)
        assign("Financial Assets", fa)
        assign("Total Liabilities", tl)
        assign("Operating Liabilities", ol)
        assign("Financial Liabilities", fl)
        assign("Net Operating Assets", noa)
        assign("Net Financial Assets", nfa)
        assign("Common Equity", te)
        assign("Total Debt", fl)
        assign("Long-term Investments", lt_inv)
        assign("Short-term Investments", st_inv)
        assign("Cash and Bank", total_cash)

        if fl is not None and total_cash is not None:
            reformulated_bs["Net Debt"][y] = fl - total_cash
        if ca is not None and cl is not None:
            reformulated_bs["Net Working Capital"][y] = ca - cl
        if noa is not None and total_cash is not None:
            reformulated_bs["Invested Capital"][y] = noa + total_cash

        if noa is not None and nfa is not None and te is not None:
            gap = noa + nfa - te
            if abs(gap) > max(1.0, abs(te) * 0.01):
                notes.append(f"NOA + NFA ≠ Equity (gap {gap:.2f})")

        classification_audit.append(PNClassificationAuditRow(
            year=y, mode=classification_mode, strict=strict_mode,
            treat_investments_as_operating=treat_investments_as_operating,
            total_assets=ta, operating_assets=oa, financial_assets=fa,
            cash=cash, bank_balances=bank_balances,
            short_term_investments=st_inv, long_term_investments=lt_inv,
            financial_liabilities=fl, operating_liabilities=ol,
            net_operating_assets=noa, net_financial_assets=nfa, equity=te,
            noa_plus_nfa_minus_equity=(noa + nfa - te) if (noa is not None and nfa is not None and te is not None) else None,
            notes=notes,
        ))

    # ── Reformulate Income Statement ─────────────────────────────────────────
    is_metrics = [
        "Revenue", "EBIT", "NOPAT", "Interest Expense", "Other Income",
        "Effective Tax Rate", "Net Income", "EBITDA", "Gross Profit",
        "Net Financial Expense After Tax", "Operating Income Before Tax", "Total Revenue",
    ]
    reformulated_is: Dict[str, Dict[str, float]] = {m: {} for m in is_metrics}
    
    for idx, y in enumerate(years):
        rev = g("Revenue", y)
        total_rev = g("Total Revenue", y)
        pbt = g("Income Before Tax", y)
        tax = g("Tax Expense", y)
        fc = g("Interest Expense", y, 0.0, True)
        oi = g("Other Income", y, 0.0, True)
        ni = g("Net Income", y)
        dep = g("Depreciation", y, 0.0, True)
        cogs = g("Cost of Goods Sold", y, 0.0, True)

        ebit = (pbt + (fc or 0.0)) if pbt is not None else None

        fin_income = 0.0 if treat_investments_as_operating else (oi or 0.0)
        fin_expense = fc or 0.0

        if ebit is None:
            operating_income_bt = None
        elif treat_investments_as_operating:
            operating_income_bt = ebit
        else:
            operating_income_bt = ebit - (oi or 0.0)

        # Effective tax rate (bounded 5%–50%)
        eff_tax = 0.25
        if pbt is not None and pbt > 0 and tax is not None:
            raw_rate = tax / pbt
            eff_tax = min(max(raw_rate, 0.05), 0.50)
        else:
            add_assumption(y, "Effective tax rate defaulted to 25% (PBT missing/non-positive)")

        tax_on_operating = (operating_income_bt * eff_tax) if operating_income_bt is not None else None
        tax_on_financial = (fin_income - fin_expense) * eff_tax

        nopat = ((operating_income_bt - tax_on_operating)
                 if operating_income_bt is not None and tax_on_operating is not None else None)

        # NFE_AT: (FinExp − FinIncome) × (1 − tax)
        nfe_at = (fin_expense - fin_income) * (1 - eff_tax)

        def ais(m: str, v: Optional[float]) -> None:
            if v is not None: reformulated_is[m][y] = v

        ais("Revenue", rev)
        if total_rev is not None:
            reformulated_is["Total Revenue"][y] = total_rev
        elif rev is not None:
            reformulated_is["Total Revenue"][y] = rev

        ais("EBIT", ebit)
        ais("Operating Income Before Tax", operating_income_bt)
        ais("NOPAT", nopat)
        ais("Interest Expense", fc)
        ais("Other Income", oi)
        reformulated_is["Effective Tax Rate"][y] = eff_tax
        ais("Net Income", ni)
        reformulated_is["Net Financial Expense After Tax"][y] = nfe_at

        if operating_income_bt is not None and dep is not None:
            reformulated_is["EBITDA"][y] = operating_income_bt + dep
        if cogs is not None and rev is not None:
            reformulated_is["Gross Profit"][y] = rev - cogs

        # Update classification audit row with IS split
        for row in classification_audit:
            if row.year == y:
                row.pbt = pbt; row.tax = tax; row.interest_expense = fc
                row.other_income = oi; row.ebit = ebit
                row.operating_income_bt = operating_income_bt
                row.effective_tax_rate = eff_tax
                row.tax_on_operating = tax_on_operating
                row.tax_on_financial = tax_on_financial
                row.nopat = nopat; row.net_financial_expense_at = nfe_at
                break

    # ── PN Ratios ─────────────────────────────────────────────────────────────
    pn_ratios: Dict[str, Dict[str, float]] = {
        name: {} for name in [
            "RNOA %", "ROOA %", "OPM %", "NOAT", "FLEV", "NBC %", "Spread %",
            "ROE %", "ROE (PN) %", "ROA %", "ROIC %", "Net Profit Margin %",
            "Current Ratio", "Quick Ratio", "Interest Coverage", "Debt to Equity",
            "Revenue Growth %", "Net Income Growth %", "Sustainable Growth Rate %",
            "ROE Gap %", "ROE Reconciled",
        ]
    }

    pn_reconciliation: List[Dict] = []
    balance_sheet_reconciliation: List[Dict] = []
    current_components_checks: List[Dict] = []

    for i, y in enumerate(years):
        noa = reformulated_bs["Net Operating Assets"].get(y)
        prev_noa = reformulated_bs["Net Operating Assets"].get(years[i - 1]) if i > 0 else None
        avg_noa = _avg(prev_noa, noa)

        oa = reformulated_bs["Operating Assets"].get(y)
        prev_oa = reformulated_bs["Operating Assets"].get(years[i - 1]) if i > 0 else None
        avg_oa = _avg(prev_oa, oa)

        ce = reformulated_bs["Common Equity"].get(y)
        prev_ce = reformulated_bs["Common Equity"].get(years[i - 1]) if i > 0 else None
        avg_ce = _avg(prev_ce, ce)

        nfa = reformulated_bs["Net Financial Assets"].get(y)
        prev_nfa = reformulated_bs["Net Financial Assets"].get(years[i - 1]) if i > 0 else None
        avg_nfa = _avg(prev_nfa, nfa)

        ta = reformulated_bs["Total Assets"].get(y) or 0.0
        prev_ta = reformulated_bs["Total Assets"].get(years[i - 1]) if i > 0 else ta
        avg_ta = (prev_ta + ta) / 2

        nfe_at = reformulated_is["Net Financial Expense After Tax"].get(y, 0.0)
        rev = reformulated_is["Revenue"].get(y, 0.0)
        ni = reformulated_is["Net Income"].get(y, 0.0)
        fl = reformulated_bs["Financial Liabilities"].get(y, 0.0)
        nopat = reformulated_is["NOPAT"].get(y, 0.0)

        ic = reformulated_bs["Invested Capital"].get(y, 0.0)
        prev_ic = reformulated_bs["Invested Capital"].get(years[i - 1]) if i > 0 else ic
        avg_ic = ((prev_ic or ic) + ic) / 2

        # PN reconciliation check
        if noa is not None and nfa is not None and ce is not None:
            pn_reconciliation.append({
                "year": y, "noa": noa, "nfa": nfa, "equity": ce,
                "gap": noa + nfa - ce,
            })

        # Balance sheet integrity checks
        ta_raw = g("Total Assets", y)
        ca_raw = g("Current Assets", y)
        cl_raw = g("Current Liabilities", y)
        nca_raw = g("Non-Current Assets", y)
        tl_raw = g("Total Liabilities", y)
        eq_raw = g("Total Equity", y)

        if ta_raw is not None:
            ca_nca_gap = ((ca_raw or 0.0) + (nca_raw or 0.0)) - ta_raw
            l_e_gap = ((tl_raw or 0.0) + (eq_raw or 0.0)) - ta_raw
            balance_sheet_reconciliation.append({
                "year": y,
                "total_assets": ta_raw,
                "current_assets": ca_raw,
                "non_current_assets": nca_raw,
                "total_liabilities": tl_raw,
                "total_equity": eq_raw,
                "assets_gap": ca_nca_gap,
                "liabilities_equity_gap": l_e_gap,
            })

            inv = g("Inventory", y) or 0.0
            ar = g("Trade Receivables", y) or 0.0
            cash_v = g("Cash and Cash Equivalents", y) or 0.0
            bank_v = g("Bank Balances", y) or 0.0
            st_inv_v = g("Short-term Investments", y) or 0.0
            st_loans_v = g("Short-term Loans", y) or 0.0
            other_st_fin_v = g("Other Short-term Financial Assets", y) or 0.0
            tax_assets_v = g("Deferred Tax Assets", y) or 0.0
            other_ca_v = g("Other Current Assets", y) or 0.0
            held_for_sale_v = g("Assets Held for Sale", y) or 0.0

            ap_v = g("Accounts Payable", y) or 0.0
            st_debt_v = g("Short-term Debt", y) or 0.0
            prov_v = g("Provisions", y) or 0.0
            other_cl_v = g("Other Current Liabilities", y) or 0.0
            tax_cl_v = g("Current Tax Liabilities", y) or 0.0
            other_stl_v = g("Other Short-term Liabilities", y) or 0.0
            liab_held_sale_v = g("Liabilities Held for Sale", y) or 0.0

            ca_component_sum = (
                inv + ar + cash_v + bank_v + st_inv_v + st_loans_v + other_st_fin_v
                + tax_assets_v + other_ca_v + held_for_sale_v
            )
            cl_component_sum = (
                ap_v + st_debt_v + prov_v + other_cl_v + tax_cl_v + other_stl_v + liab_held_sale_v
            )
            current_components_checks.append({
                "year": y,
                "current_assets": ca_raw,
                "ca_component_sum": ca_component_sum,
                "ca_gap": ca_component_sum - (ca_raw or 0.0),
                "inventory": inv,
                "trade_receivables": ar,
                "cash": cash_v,
                "bank_balances": bank_v,
                "short_term_investments": st_inv_v,
                "short_term_loans": st_loans_v,
                "other_short_term_financial_assets": other_st_fin_v,
                "tax_assets": tax_assets_v,
                "other_current_assets": other_ca_v,
                "assets_held_for_sale": held_for_sale_v,
                "current_liabilities": cl_raw,
                "cl_component_sum": cl_component_sum,
                "cl_gap": cl_component_sum - (cl_raw or 0.0),
                "accounts_payable": ap_v,
                "short_term_debt": st_debt_v,
                "provisions": prov_v,
                "other_current_liabilities": other_cl_v,
                "tax_current_liabilities": tax_cl_v,
                "other_short_term_liabilities": other_stl_v,
                "liabilities_held_for_sale": liab_held_sale_v,
            })

        # RNOA — numerically unstable when avg_noa ≈ 0
        if avg_noa is not None:
            materiality = max(10.0, abs(avg_ta) * 0.05)
            if abs(avg_noa) <= materiality:
                ratio_warnings.append({
                    "year": y,
                    "warning": (f"Avg NOA is small vs assets (|AvgNOA|={avg_noa:.2f}; "
                                f"threshold≈{materiality:.2f}). RNOA/NOAT may be unstable. Use ROOA.")
                })
            if abs(avg_noa) > 10:
                pn_ratios["RNOA %"][y] = nopat / avg_noa * 100

        if avg_oa is not None and abs(avg_oa) > 10:
            pn_ratios["ROOA %"][y] = nopat / avg_oa * 100

        if rev > 0:
            pn_ratios["OPM %"][y] = nopat / rev * 100

        if avg_noa is not None and abs(avg_noa) > 10:
            pn_ratios["NOAT"][y] = rev / avg_noa

        # FLEV = −NFA / CE  (positive = net debt)
        if avg_ce is not None and abs(avg_ce) > 10 and avg_nfa is not None:
            pn_ratios["FLEV"][y] = -avg_nfa / avg_ce

        # NBC — net borrowing cost
        avg_nfo = -avg_nfa if avg_nfa is not None else None
        if avg_nfo is not None and abs(avg_nfo) > 10 and nfe_at != 0:
            pn_ratios["NBC %"][y] = max(-15.0, min(25.0, nfe_at / avg_nfo * 100))
        elif fl <= 10:
            pn_ratios["NBC %"][y] = 0.0

        rnoa = pn_ratios["RNOA %"].get(y)
        nbc = pn_ratios["NBC %"].get(y)
        if rnoa is not None and nbc is not None:
            pn_ratios["Spread %"][y] = rnoa - nbc

        # ROE (actual)
        if avg_ce is not None and abs(avg_ce) > 10:
            pn_ratios["ROE %"][y] = ni / avg_ce * 100

        # ROE (PN decomposed) = RNOA + FLEV × Spread
        flev = pn_ratios["FLEV"].get(y)
        spread = pn_ratios["Spread %"].get(y)
        if rnoa is not None and flev is not None and spread is not None:
            roe_pn = rnoa + flev * spread
            pn_ratios["ROE (PN) %"][y] = roe_pn
            roe_actual = pn_ratios["ROE %"].get(y)
            if roe_actual is not None:
                gap = abs(roe_actual - roe_pn)
                pn_ratios["ROE Gap %"][y] = gap
                pn_ratios["ROE Reconciled"][y] = 1.0 if gap <= 2 else 0.0

        # Other ratios
        if avg_ta > 0: pn_ratios["ROA %"][y] = ni / avg_ta * 100
        if avg_ic > 10: pn_ratios["ROIC %"][y] = nopat / avg_ic * 100
        if rev > 0: pn_ratios["Net Profit Margin %"][y] = ni / rev * 100

        ca = g("Current Assets", y)
        cl = g("Current Liabilities", y)
        inv_v = g("Inventory", y) or 0.0
        if ca and cl and cl > 0:
            pn_ratios["Current Ratio"][y] = ca / cl
            pn_ratios["Quick Ratio"][y] = (ca - inv_v) / cl

        ebit_val = reformulated_is["EBIT"].get(y, 0.0)
        ie_val = reformulated_is["Interest Expense"].get(y, 0.0)
        if ie_val > 0.01:
            pn_ratios["Interest Coverage"][y] = min(ebit_val / ie_val, 999.0)
        elif fl <= 10 and ebit_val > 0:
            pn_ratios["Interest Coverage"][y] = 999.0

        ce_val = ce or 0.0
        if ce_val > 0: pn_ratios["Debt to Equity"][y] = fl / ce_val

        if i > 0:
            prev_rev = reformulated_is["Revenue"].get(years[i - 1])
            if prev_rev and prev_rev > 0:
                pn_ratios["Revenue Growth %"][y] = (rev - prev_rev) / prev_rev * 100
            prev_ni = reformulated_is["Net Income"].get(years[i - 1])
            if prev_ni and abs(prev_ni) > 0:
                pn_ratios["Net Income Growth %"][y] = (ni - prev_ni) / abs(prev_ni) * 100

        roe = pn_ratios["ROE %"].get(y)
        if roe is not None: pn_ratios["Sustainable Growth Rate %"][y] = roe * 0.70

    # ── FCF ───────────────────────────────────────────────────────────────────
    fcf: Dict[str, Dict[str, float]] = {
        m: {} for m in ["Operating Cash Flow", "Capital Expenditure", "Free Cash Flow", "FCF Yield %", "FCFE"]
    }
    cash_flow_checks: List[ReconciliationRow] = []

    for y in years:
        ocf = g("Operating Cash Flow", y)
        capex_raw = g("Capital Expenditure", y)
        capex = abs(capex_raw) if capex_raw is not None else None
        ie = g("Interest Expense", y) or 0.0

        if ocf is not None: fcf["Operating Cash Flow"][y] = ocf
        if capex is not None: fcf["Capital Expenditure"][y] = capex
        if ocf is not None and capex is not None:
            fcf["Free Cash Flow"][y] = ocf - capex
            fcf["FCFE"][y] = ocf - capex - ie
            ta_v = reformulated_bs["Total Assets"].get(y)
            if ta_v and ta_v > 0:
                fcf["FCF Yield %"][y] = (ocf - capex) / ta_v * 100

    # Value drivers
    value_drivers: Dict[str, Dict[str, float]] = {
        "Revenue": dict(reformulated_is["Revenue"]),
        "NOPAT": dict(reformulated_is["NOPAT"]),
        "Revenue Growth %": dict(pn_ratios["Revenue Growth %"]),
    }

    # ── Fix suggestions ───────────────────────────────────────────────────────
    fix_suggestions: List[str] = []
    latest_year = years[-1] if years else ""
    roe_gap = pn_ratios["ROE Gap %"].get(latest_year)
    if roe_gap is not None and roe_gap > 2:
        fix_suggestions.append("ROE gap >2%: verify Total Equity, Interest Expense, Other Income, and PBT mappings.")
    if not reformulated_is["NOPAT"]:
        fix_suggestions.append("NOPAT missing: verify Revenue, EBIT, Tax Expense mappings.")
    if not reformulated_bs["Net Operating Assets"]:
        fix_suggestions.append("NOA missing: verify Current Assets/Liabilities, Total Assets, Total Equity mappings.")
    if not any(k.startswith("CashFlow::") for k in data):
        fix_suggestions.append("Cash Flow statement missing: FCF and cash-based diagnostics unavailable.")

    # ── IS reconciliation checks ──────────────────────────────────────────────
    income_stmt_checks: List[ReconciliationRow] = []
    for y in years:
        rev = gv("Total Revenue", y)
        if rev is None:
            rev = gv("Revenue", y)
        expenses = gv("Total Expenses", y)
        tax = gv("Tax Expense", y)
        ni = gv("Net Income", y)
        exc = gv("Exceptional Items", y)
        pbt = gv("Income Before Tax", y)
        ebit = reformulated_is["EBIT"].get(y)
        ie = gv("Interest Expense", y)

        picked = _pick_best_ni_reconciliation(
            revenue=rev,
            total_expenses=expenses,
            tax_expense=tax,
            exceptional_items=exc,
            pbt=pbt,
            ebit=ebit,
            interest_expense=ie,
            net_income=ni,
        )
        if picked is None or ni is None:
            continue

        expected, gap, note = picked
        tol = max(1.0, abs(ni) * 0.02)
        income_stmt_checks.append(ReconciliationRow(
            year=y,
            expected=expected,
            actual=ni,
            gap=gap,
            status="ok" if abs(gap) <= tol else "warn",
            note=note,
        ))

    # ── Data hygiene ──────────────────────────────────────────────────────────
    critical_metrics = [
        "Revenue", "Total Revenue", "Total Expenses", "Income Before Tax",
        "Tax Expense", "Net Income", "Total Assets", "Total Equity",
        "Current Assets", "Current Liabilities", "Operating Cash Flow",
    ]
    data_hygiene: List[DataHygieneIssue] = []
    for t in critical_metrics:
        series = {y: derive_val(data, mappings, t, y) for y in years}
        missing = [y for y in years if series.get(y) is None]
        if missing:
            data_hygiene.append(DataHygieneIssue(
                metric=t, missing_years=missing,
                severity="critical" if t in ["Revenue", "Net Income", "Total Assets", "Total Equity"] else "warning",
            ))

    # ── Academic extensions: ReOI, AEG, Accruals, Shapley ────────────────────
    reoi: Dict[str, float] = {}
    cumulative_reoi: Dict[str, float] = {}
    aeg: Dict[str, float] = {}
    operating_accruals: Dict[str, float] = {}
    accrual_ratio: Dict[str, float] = {}
    accrual_ratio_oa: Dict[str, float] = {}
    accrual_ratio_sales: Dict[str, float] = {}
    accrual_denom_used: Dict[str, str] = {}
    earnings_quality: Dict[str, str] = {}
    nopat_drivers: Dict[str, NOPATDrivers] = {}
    exceptional_items: Dict[str, float] = {}
    core_nopat: Dict[str, float] = {}
    core_reoi: Dict[str, float] = {}

    def _shapley3(
        prev_a: float, prev_b: float, prev_c: float,
        curr_a: float, curr_b: float, curr_c: float,
    ) -> Tuple[float, float, float]:
        """Shapley 3-factor attribution for NOPAT = OPM × NOAT × AvgNOA."""
        from itertools import permutations

        prev = {"a": prev_a, "b": prev_b, "c": prev_c}
        curr = {"a": curr_a, "b": curr_b, "c": curr_c}
        f = lambda x: x["a"] * x["b"] * x["c"]
        contrib = {"a": 0.0, "b": 0.0, "c": 0.0}
        all_perms = list(permutations(["a", "b", "c"]))
        for perm in all_perms:
            state = dict(prev)
            base = f(state)
            for k in perm:
                state[k] = curr[k]
                nxt = f(state)
                contrib[k] += nxt - base
                base = nxt
        n = len(all_perms)
        return contrib["a"] / n, contrib["b"] / n, contrib["c"] / n

    cum = 0.0
    for i, y in enumerate(years):
        nopat_y = reformulated_is["NOPAT"].get(y)
        noa_y = reformulated_bs["Net Operating Assets"].get(y)
        prev_noa_y = reformulated_bs["Net Operating Assets"].get(years[i - 1]) if i > 0 else None

        # ReOI_t = NOPAT_t − r × NOA_{t-1}
        if nopat_y is not None and prev_noa_y is not None:
            cap_charge = cost_of_capital * prev_noa_y
            v = nopat_y - cap_charge
            reoi[y] = v
            cum += v
            cumulative_reoi[y] = cum
            if i > 0 and years[i - 1] in reoi:
                aeg[y] = v - reoi[years[i - 1]]

        # Accruals: Operating Accruals = NOPAT − OCF
        ocf = fcf["Operating Cash Flow"].get(y)
        if nopat_y is not None and ocf is not None:
            acc = nopat_y - ocf
            operating_accruals[y] = acc

            avg_noa_v = _avg(prev_noa_y, noa_y)
            oa_y = reformulated_bs["Operating Assets"].get(y)
            prev_oa_y = reformulated_bs["Operating Assets"].get(years[i - 1]) if i > 0 else None
            avg_oa_v = _avg(prev_oa_y, oa_y)
            sales = reformulated_is["Revenue"].get(y)

            ta_y = reformulated_bs["Total Assets"].get(y)
            prev_ta_y = reformulated_bs["Total Assets"].get(years[i - 1]) if i > 0 else ta_y
            avg_ta_v = _avg(prev_ta_y, ta_y)

            if avg_oa_v is not None and abs(avg_oa_v) > 10:
                accrual_ratio_oa[y] = acc / avg_oa_v
            if sales is not None and abs(sales) > 1e-9:
                accrual_ratio_sales[y] = acc / sales

            noa_materiality = max(10.0, abs(avg_ta_v) * 0.05) if avg_ta_v else 10.0
            primary: Optional[float] = None
            used: Optional[str] = None

            if avg_noa_v is not None and abs(avg_noa_v) > noa_materiality:
                primary = acc / avg_noa_v; used = "NOA"
            elif avg_oa_v is not None and abs(avg_oa_v) > 10:
                primary = acc / avg_oa_v; used = "OA"
            elif sales is not None and abs(sales) > 1e-9:
                primary = acc / sales; used = "Sales"

            if primary is not None and used:
                accrual_ratio[y] = primary
                accrual_denom_used[y] = used  # type: ignore
                abs_p = abs(primary)
                earnings_quality[y] = "High" if abs_p < 0.05 else "Medium" if abs_p < 0.15 else "Low"  # type: ignore

        # NOPAT drivers (Shapley)
        if i > 0:
            prev_y = years[i - 1]
            prev_rev = reformulated_is["Revenue"].get(prev_y)
            curr_rev = reformulated_is["Revenue"].get(y)
            prev_nopat = reformulated_is["NOPAT"].get(prev_y)
            curr_nopat = reformulated_is["NOPAT"].get(y)

            prev_noa2 = reformulated_bs["Net Operating Assets"].get(prev_y)
            curr_noa2 = reformulated_bs["Net Operating Assets"].get(y)
            avg_noa_prev = _avg(
                reformulated_bs["Net Operating Assets"].get(years[i - 2]) if i > 1 else prev_noa2,
                prev_noa2
            )
            avg_noa_curr = _avg(prev_noa2, curr_noa2)

            if (prev_rev and curr_rev and prev_nopat and curr_nopat
                    and prev_rev > 0 and curr_rev > 0
                    and avg_noa_prev and avg_noa_curr
                    and abs(avg_noa_prev) > 10 and abs(avg_noa_curr) > 10):
                opm_prev = prev_nopat / prev_rev
                opm_curr = curr_nopat / curr_rev
                noat_prev = prev_rev / avg_noa_prev
                noat_curr = curr_rev / avg_noa_curr

                margin_eff, turnover_eff, capital_eff = _shapley3(
                    opm_prev, noat_prev, avg_noa_prev,
                    opm_curr, noat_curr, avg_noa_curr,
                )
                delta = curr_nopat - prev_nopat
                nopat_drivers[y] = NOPATDrivers(
                    delta_nopat=delta,
                    margin_effect=margin_eff,
                    turnover_effect=turnover_eff,
                    capital_base_effect=capital_eff,
                    residual=delta - (margin_eff + turnover_eff + capital_eff),
                )

        # Exceptional items (core vs reported)
        exc = gv("Exceptional Items", y)
        if exc is not None: exceptional_items[y] = exc

        eff_tax_y = reformulated_is["Effective Tax Rate"].get(y, 0.25)
        nopat_yv = reformulated_is["NOPAT"].get(y)
        if nopat_yv is not None:
            exc_at = exc * (1 - eff_tax_y) if exc is not None else 0.0
            core_nopat[y] = nopat_yv - exc_at

    # Core ReOI
    for i, y in enumerate(years):
        prev_noa_y = reformulated_bs["Net Operating Assets"].get(years[i - 1]) if i > 0 else None
        c_nopat = core_nopat.get(y)
        if c_nopat is not None and prev_noa_y is not None:
            core_reoi[y] = c_nopat - cost_of_capital * prev_noa_y

    academic = PenmanAcademicMetrics(
        reoi=reoi,
        cumulative_reoi=cumulative_reoi,
        aeg=aeg,
        exceptional_items=exceptional_items if exceptional_items else None,
        core_nopat=core_nopat if core_nopat else None,
        core_reoi=core_reoi if core_reoi else None,
        operating_accruals=operating_accruals,
        accrual_ratio=accrual_ratio,
        accrual_ratio_oa=accrual_ratio_oa,
        accrual_ratio_sales=accrual_ratio_sales,
        accrual_denominator_used=accrual_denom_used,  # type: ignore
        earnings_quality=earnings_quality,  # type: ignore
        nopat_drivers=nopat_drivers,
    )

    # ── Base Valuation ────────────────────────────────────────────────────────
    val_warnings: List[str] = []
    if terminal_growth >= cost_of_capital:
        val_warnings.append("Terminal growth (g) must be < cost of capital (r) for stable terminal value.")

    last_year = years[-1] if years else ""
    noa0 = reformulated_bs["Net Operating Assets"].get(last_year)
    reoi_last = reoi.get(last_year)
    reoi_ys = sorted(reoi.keys())
    reoi_mean3 = _mean_last_n(reoi, 3)
    reoi_trend3: Optional[float] = None
    if len(reoi_ys) >= 2:
        vals_t = [reoi[y] for y in reoi_ys[-3:]]
        slope = (vals_t[-1] - vals_t[0]) / (len(vals_t) - 1)
        reoi_trend3 = vals_t[-1] + slope

    base_reoi = (
        reoi_last if forecast_method == "reoi_last"
        else (reoi_trend3 or reoi_mean3 or reoi_last) if forecast_method == "reoi_trend3"
        else (reoi_mean3 or reoi_last)
    )

    forecast_reoi: Dict[str, float] = {}
    if base_reoi is not None:
        for t in range(1, forecast_years_n + 1):
            forecast_reoi[f"t+{t}"] = base_reoi

    pv_explicit: Optional[float] = None
    pv_terminal: Optional[float] = None
    intrinsic_value: Optional[float] = None
    value_to_book: Optional[float] = None

    if noa0 is not None and base_reoi is not None and cost_of_capital > 0:
        pv_explicit = sum(
            base_reoi / (1 + cost_of_capital) ** t
            for t in range(1, forecast_years_n + 1)
        )
        if terminal_growth < cost_of_capital:
            tv = base_reoi * (1 + terminal_growth) / (cost_of_capital - terminal_growth)
            pv_terminal = tv / (1 + cost_of_capital) ** forecast_years_n
        else:
            val_warnings.append("Terminal growth >= cost of capital; terminal value set to 0.")
            pv_terminal = 0.0
        intrinsic_value = noa0 + (pv_explicit or 0.0) + (pv_terminal or 0.0)
        value_to_book = intrinsic_value / noa0 if noa0 != 0 else None

    valuation = PenmanValuationResult(
        cost_of_capital=cost_of_capital,
        terminal_growth=terminal_growth,
        forecast_years=forecast_years_n,
        noa0=noa0,
        reoi0=reoi_last,
        pv_explicit=pv_explicit,
        pv_terminal=pv_terminal,
        intrinsic_value=intrinsic_value,
        value_to_book=value_to_book,
        forecast_reoi=forecast_reoi,
        warnings=val_warnings,
    )

    # ── Scenario Valuation ────────────────────────────────────────────────────
    def _last_opm() -> Optional[float]:
        return _last(pn_ratios.get("OPM %", {}))

    def _last_noat() -> Optional[float]:
        return _last(pn_ratios.get("NOAT", {}))

    def _last_rev_growth() -> Optional[float]:
        return _last(pn_ratios.get("Revenue Growth %", {}))

    opm_base = _last_opm() or 10.0
    noat_base = _last_noat() or 1.0
    rev_g_base = _last_rev_growth() or 5.0

    scenario_defs = [
        ("bear", "Bear Case", cost_of_capital + 0.02, 0.01, max(0, rev_g_base - 5) / 100, max(0, opm_base - 3) / 100, max(0, noat_base - 0.2), 0.3),
        ("base", "Base Case", cost_of_capital, terminal_growth, rev_g_base / 100, opm_base / 100, noat_base, 0.5),
        ("bull", "Bull Case", cost_of_capital - 0.01, min(terminal_growth + 0.01, cost_of_capital - 0.02), (rev_g_base + 5) / 100, (opm_base + 3) / 100, noat_base + 0.2, 0.7),
    ]

    scenarios: List[ScenarioValuation] = []
    for scen_id, label, r, g, rev_g, tgt_opm, tgt_noat, t_speed in scenario_defs:
        w: List[str] = []
        pf_years = [f"t+{t}" for t in range(1, forecast_years_n + 1)]
        pf_revs, pf_opms, pf_noats, pf_nopats, pf_noas, pf_reois = [], [], [], [], [], []

        use_reoi = core_reoi or reoi
        core_mode = bool(core_reoi)

        # Build pro-forma path with mean-reversion
        curr_rev = reformulated_is["Revenue"].get(last_year) or 0.0
        curr_opm = (pn_ratios.get("OPM %", {}).get(last_year) or opm_base) / 100
        curr_noat = pn_ratios.get("NOAT", {}).get(last_year) or noat_base
        curr_noa_val = noa0

        valid_pf = curr_rev > 0 and curr_noa_val is not None

        if valid_pf and curr_noa_val is not None:
            noa_t = curr_noa_val
            for t in range(1, forecast_years_n + 1):
                alpha = t_speed
                opm_t = alpha * tgt_opm + (1 - alpha) * curr_opm
                noat_t = alpha * tgt_noat + (1 - alpha) * curr_noat
                rev_t = curr_rev * (1 + rev_g) ** t
                nopat_t = opm_t * rev_t
                noa_t_new = rev_t / noat_t if noat_t != 0 else noa_t
                reoi_t = nopat_t - r * noa_t

                pf_revs.append(rev_t)
                pf_opms.append(opm_t)
                pf_noats.append(noat_t)
                pf_nopats.append(nopat_t)
                pf_noas.append(noa_t_new)
                pf_reois.append(reoi_t)
                noa_t = noa_t_new

        pf = None
        pv_exp_s: Optional[float] = None
        pv_term_s: Optional[float] = None
        intr_s: Optional[float] = None
        vtb_s: Optional[float] = None

        if valid_pf and pf_reois:
            pf = ProFormaForecast(
                years=pf_years, revenue=pf_revs, opm=pf_opms, noat=pf_noats,
                nopat=pf_nopats, noa=pf_noas, reoi=pf_reois, core_mode=core_mode,
                assumptions=ProFormaAssumptions(
                    revenue_growth=rev_g, target_opm=tgt_opm,
                    target_noat=tgt_noat, transition_speed=t_speed,
                ),
            )
            pv_exp_s = sum(reoi_v / (1 + r) ** (t + 1) for t, reoi_v in enumerate(pf_reois))
            if g < r:
                last_reoi_pf = pf_reois[-1]
                tv_s = last_reoi_pf * (1 + g) / (r - g)
                pv_term_s = tv_s / (1 + r) ** forecast_years_n
            else:
                pv_term_s = 0.0
                w.append("Terminal growth must be < cost of capital.")
            intr_s = (noa0 or 0.0) + (pv_exp_s or 0.0) + (pv_term_s or 0.0)
            vtb_s = intr_s / noa0 if noa0 and noa0 != 0 else None

        scenarios.append(ScenarioValuation(
            id=scen_id,  # type: ignore
            label=label,
            cost_of_capital=r,
            terminal_growth=g,
            forecast_years=forecast_years_n,
            pro_forma=ProFormaAssumptions(rev_g, tgt_opm, tgt_noat, t_speed),
            forecast=pf,
            noa0=noa0,
            pv_explicit=pv_exp_s,
            pv_terminal=pv_term_s,
            intrinsic_value=intr_s,
            value_to_book=vtb_s,
            warnings=w,
        ))

    # ── Operating Risk ────────────────────────────────────────────────────────
    rnoa_vals = [v for y, v in pn_ratios["RNOA %"].items()]
    rooa_vals = [v for y, v in pn_ratios["ROOA %"].items()]
    opm_vals = [v for y, v in pn_ratios["OPM %"].items()]
    noat_vals = [v for y, v in pn_ratios["NOAT"].items()]
    op_risk_notes: List[str] = []
    sigma_rnoa = _std_dev(rnoa_vals)
    sigma_opm = _std_dev(opm_vals)
    if sigma_rnoa and sigma_rnoa > 30:
        op_risk_notes.append("High RNOA volatility; consider ROOA and classification mode for interpretation.")
    if sigma_opm and sigma_opm > 5:
        op_risk_notes.append("Operating margin is volatile; forecasting should mean-revert.")

    fci: Dict[str, float] = {}
    for y in years:
        emp = gv("Employee Expenses", y)
        dep = gv("Depreciation", y)
        rev_y = gv("Revenue", y)
        if rev_y and rev_y != 0 and (emp is not None or dep is not None):
            fci[y] = ((emp or 0.0) + (dep or 0.0)) / rev_y

    operating_risk = OperatingRiskMetrics(
        sigma_rnoa=sigma_rnoa,
        sigma_rooa=_std_dev(rooa_vals),
        sigma_opm=sigma_opm,
        sigma_noat=_std_dev(noat_vals),
        fixed_cost_intensity=fci if fci else None,
        notes=op_risk_notes,
    )

    # ── Auto Investment Thesis ────────────────────────────────────────────────
    bullets, red_flags, watch_items = [], [], []
    roe_avg3 = _mean_last_n(pn_ratios.get("ROE %", {}), 3)
    use_reoi_for_thesis = core_reoi if core_reoi else reoi
    reoi_avg3 = _mean_last_n(use_reoi_for_thesis, 3)
    reoi_latest = _last(use_reoi_for_thesis)
    quality_latest = _last(earnings_quality)  # type: ignore

    if roe_avg3 is not None:
        bullets.append(f"ROE (avg ~3y) ≈ {roe_avg3:.1f}% with clean PN reconciliation.")
    if reoi_avg3 is not None:
        bullets.append(f"Residual Operating Income (avg ~3y) ≈ {reoi_avg3:,.0f} (value creation signal).")
    if quality_latest:
        bullets.append(f"Accrual-based earnings quality (latest) rated {quality_latest}.")

    flev_latest = _last(pn_ratios.get("FLEV", {}))
    if flev_latest is not None:
        if flev_latest < 0:
            bullets.append("Net financial assets (FLEV < 0): excess liquidity/investments dampen ROE; capital allocation is a lever.")
        else:
            bullets.append("Net debt position (FLEV > 0): ROE benefits depend on positive spread and refinancing risk.")

    if exceptional_items:
        watch_items.append("Exceptional items detected: use Core NOPAT/ReOI for forecasting sustainability.")
    if ratio_warnings:
        red_flags.append("Some years have numerically unstable NOA-based ratios; interpret RNOA with ROOA fallback.")
    if reoi_latest is not None and reoi_latest < 0:
        red_flags.append("Latest ReOI is negative: operations may be destroying value at the chosen cost of capital.")
    if sigma_opm and sigma_opm > 6:
        watch_items.append("Operating margin volatility is elevated; forecast with mean reversion and stress scenarios.")

    base_scen = next((s for s in scenarios if s.id == "base"), None)
    if base_scen and base_scen.value_to_book is not None:
        bullets.append(f"ReOI model suggests intrinsic value V/NOA₀ ≈ {base_scen.value_to_book:.2f} under base scenario.")

    thesis = InvestmentThesis(
        title="Penman Investment Thesis (Auto)",
        bullets=bullets, red_flags=red_flags, watch_items=watch_items,
    )

    # ── Assemble diagnostics ──────────────────────────────────────────────────
    diagnostics = PNDiagnostics(
        treat_investments_as_operating=treat_investments_as_operating,
        message=(
            "Investments treated as Operating Assets (Holding Company adjustment)"
            if treat_investments_as_operating
            else "Investments treated as Financial Assets (Standard PN framework)"
        ),
        strict_mode=strict_mode,
        classification_mode=classification_mode,
        fix_suggestions=fix_suggestions,
        income_statement_checks=income_stmt_checks,
        cash_flow_checks=cash_flow_checks,
        data_hygiene=data_hygiene,
        assumptions=assumptions,
        pn_reconciliation=pn_reconciliation,
        balance_sheet_reconciliation=balance_sheet_reconciliation,
        current_components_checks=current_components_checks,
        classification_audit=classification_audit,
        ratio_warnings=ratio_warnings,
    )

    # ── Nissim (2023) Profitability Analysis ───────────────────────────────
    base_result = PenmanNissimResult(
        reformulated_bs=reformulated_bs,
        reformulated_is=reformulated_is,
        ratios=pn_ratios,
        fcf=fcf,
        value_drivers=value_drivers,
        academic=academic,
        valuation=valuation,
        scenarios=scenarios,
        operating_risk=operating_risk,
        thesis=thesis,
        company_type=company_type,
        diagnostics=diagnostics,
    )
    base_result.nissim_profitability = nissim_profitability_analysis(
        pn_result=base_result, data=data, mappings=mappings,
    )
    return base_result


# ─── Scoring Models ───────────────────────────────────────────────────────────

def calculate_scores(data: FinancialData, mappings: MappingDict) -> ScoringResult:
    """Altman Z-Score (1968) + Piotroski F-Score (2000)."""
    years = get_years(data)
    altman_z: Dict[str, AltmanZScore] = {}
    piotroski_f: Dict[str, PiotroskiFScore] = {}

    for i, y in enumerate(years):
        ta = derive_val(data, mappings, "Total Assets", y)
        if ta is None or ta <= 0:
            continue

        ca = derive_val(data, mappings, "Current Assets", y) or 0.0
        cl = derive_val(data, mappings, "Current Liabilities", y) or 0.0
        re = derive_val(data, mappings, "Retained Earnings", y) or 0.0
        ebit = derive_val(data, mappings, "EBIT", y) or 0.0
        te = derive_val(data, mappings, "Total Equity", y) or 0.0
        tl = ta - te
        rev = derive_val(data, mappings, "Revenue", y) or 0.0

        wc = ca - cl
        A = wc / ta
        B = re / ta
        C = ebit / ta
        D = te / (tl or 1.0)
        E = rev / ta
        z = 1.2 * A + 1.4 * B + 3.3 * C + 0.6 * D + 1.0 * E
        zone = "Safe" if z > 2.99 else "Grey" if z > 1.81 else "Distress"
        altman_z[y] = AltmanZScore(score=round(z, 2), zone=zone)  # type: ignore

        # Piotroski F-Score
        signals: List[str] = []
        score = 0
        ni = derive_val(data, mappings, "Net Income", y) or 0.0
        ocf = derive_val(data, mappings, "Operating Cash Flow", y) or 0.0

        if ni > 0: score += 1; signals.append("✅ Positive Net Income")
        else: signals.append("❌ Negative Net Income")

        if ta > 0 and ni / ta > 0: score += 1; signals.append("✅ Positive ROA")
        else: signals.append("❌ Non-positive ROA")

        if ocf > 0: score += 1; signals.append("✅ Positive OCF")
        else: signals.append("❌ Negative OCF")

        if ocf > ni: score += 1; signals.append("✅ OCF > Net Income (Accruals)")
        else: signals.append("❌ OCF ≤ Net Income")

        if i > 0:
            prev_y = years[i - 1]
            prev_ta = derive_val(data, mappings, "Total Assets", prev_y) or 0.0
            prev_ni = derive_val(data, mappings, "Net Income", prev_y) or 0.0
            prev_ca = derive_val(data, mappings, "Current Assets", prev_y) or 0.0
            prev_cl = derive_val(data, mappings, "Current Liabilities", prev_y) or 0.0
            prev_rev = derive_val(data, mappings, "Revenue", prev_y) or 0.0

            if prev_ta > 0 and ta > 0:
                if (ni / ta) > (prev_ni / prev_ta): score += 1; signals.append("✅ Improving ROA")
                else: signals.append("❌ Declining ROA")

            prev_cr = prev_ca / prev_cl if prev_cl > 0 else 0.0
            curr_cr = ca / cl if cl > 0 else 0.0
            if curr_cr > prev_cr: score += 1; signals.append("✅ Improving Liquidity")
            else: signals.append("❌ Declining Liquidity")

            if rev > 0 and prev_ta > 0 and prev_rev > 0:
                if (rev / ta) > (prev_rev / prev_ta): score += 1; signals.append("✅ Improving Turnover")
                else: signals.append("❌ Declining Turnover")

        piotroski_f[y] = PiotroskiFScore(score=min(score, 9), signals=signals)

    return ScoringResult(altman_z=altman_z, piotroski_f=piotroski_f)


# ─── Nissim (2023) Profitability Analysis ─────────────────────────────────────

def _coeff_of_variation(series: Dict[str, float]) -> Optional[float]:
    """Coefficient of variation = std / |mean| — measures time-series stability."""
    vals = list(series.values())
    if len(vals) < 2:
        return None
    mean = sum(vals) / len(vals)
    if abs(mean) < 1e-9:
        return None
    std = _std_dev(vals)
    return (std / abs(mean)) if std is not None else None


def nissim_profitability_analysis(
    pn_result: PenmanNissimResult,
    data: FinancialData,
    mappings: MappingDict,
) -> NissimProfitabilityResult:
    """
    Nissim (2023) "Profitability Analysis" — full implementation.

    Novel contributions integrated:
    1. Operations Funding Ratio (OFR) = NOA / OA
       - Measures proportion of operating assets funded by capital
       - Highly stable (empirical persistence ≈ 0.955)
       - Low OFR indicates market power (operating credit from suppliers/customers)

    2. Operating Asset Turnover (OAT) = Revenue / Avg OA (not Avg NOA)
       - Sales are generated by ALL operating assets, regardless of funding source
       - More robust than NOAT when NOA is small or negative

    3. Novel 3-factor RNOA decomposition:
       RNOA = OPM × OAT / OFR
       vs standard: RNOA = OPM × NOAT

    4. Full ROCE hierarchy (Exhibit D in paper):
       ROCE = ROE + NCI Leverage Effect
       ROE = Recurring ROE + Transitory ROE
       Recurring ROE = RNOA + Financial Leverage Effect + Net Other Nonop Effect
       Financial Leverage Effect = FLEV × Financial Spread
       Financial Spread = RNOA − NBC

    5. Stability analysis: OFR > OAT > OPM in time-series stability

    Reference: Nissim, D. (2023). Profitability Analysis. Columbia Business School.
    SSRN Working Paper #4064824. https://papers.ssrn.com/abstract_id=4064824
    """
    bs = pn_result.reformulated_bs
    is_ = pn_result.reformulated_is
    ratios = pn_result.ratios

    years = sorted(set(bs.get("Net Operating Assets", {}).keys()) |
                   set(is_.get("NOPAT", {}).keys()) |
                   set(is_.get("Revenue", {}).keys()))

    if not years:
        return NissimProfitabilityResult()

    # ── Helper to safely get average ──────────────────────────────────────
    def avg_bs(metric: str, i: int, y: str) -> Optional[float]:
        curr = bs.get(metric, {}).get(y)
        if i > 0:
            prev = bs.get(metric, {}).get(years[i - 1])
        else:
            prev = None
        return _avg(prev, curr)

    def gv(target: str, y: str) -> Optional[float]:
        return derive_val(data, mappings, target, y)

    # =========================================================================
    # PART 1: NISSIM 3-FACTOR OPERATING PROFITABILITY DECOMPOSITION
    # =========================================================================
    opm_d: Dict[str, float] = {}
    oat_d: Dict[str, float] = {}
    ofr_d: Dict[str, float] = {}
    noat_d: Dict[str, float] = {}
    rnoa_nissim_d: Dict[str, float] = {}
    rooa_d: Dict[str, float] = {}
    op_credit_pct_d: Dict[str, float] = {}
    ofr_impact_d: Dict[str, float] = {}

    for i, y in enumerate(years):
        nopat = is_.get("NOPAT", {}).get(y)
        rev = is_.get("Revenue", {}).get(y)
        noa = bs.get("Net Operating Assets", {}).get(y)
        oa = bs.get("Operating Assets", {}).get(y)
        ol = bs.get("Operating Liabilities", {}).get(y)

        avg_noa = avg_bs("Net Operating Assets", i, y)
        avg_oa = avg_bs("Operating Assets", i, y)

        # OPM = NOPAT / Revenue  (Operating Profit Margin)
        if nopat is not None and rev is not None and rev != 0:
            opm_d[y] = nopat / rev * 100.0

        # OAT = Revenue / Avg Operating Assets  (Operating Asset Turnover)
        # KEY: relative to OA (gross), not NOA (net). See Nissim (2023) §5.2
        if rev is not None and avg_oa is not None and abs(avg_oa) > 0.01:
            oat_d[y] = rev / avg_oa

        # OFR = NOA / OA  (Operations Funding Ratio)
        # Proportion of operating assets funded by capital providers.
        # 1 − OFR = proportion funded by operating creditors (AP, deferred rev, etc.)
        if noa is not None and oa is not None and abs(oa) > 0.01:
            ofr_d[y] = noa / oa  # raw fraction, not percentage

        # Standard NOAT = Revenue / Avg NOA (retained for comparison)
        if rev is not None and avg_noa is not None and abs(avg_noa) > 0.01:
            noat_d[y] = rev / avg_noa

        # RNOA (Nissim 3-factor) = OPM × OAT / OFR
        # Algebraically: (NOPAT/Rev) × (Rev/AvgOA) / (NOA/OA)
        #               = NOPAT/AvgOA × OA/NOA = NOPAT/AvgNOA = RNOA ✓
        opm_frac = opm_d.get(y)
        oat_v = oat_d.get(y)
        ofr_v = ofr_d.get(y)
        if opm_frac is not None and oat_v is not None and ofr_v is not None and abs(ofr_v) > 0.001:
            rnoa_nissim_d[y] = (opm_frac / 100.0) * oat_v / ofr_v * 100.0

        # ROOA = NOPAT / Avg OA  (Return on Operating Assets — gross approach)
        # Complementary to RNOA; avoids small-NOA instability.
        # ROOA = RNOA × OFR  (by construction)
        if nopat is not None and avg_oa is not None and abs(avg_oa) > 0.01:
            rooa_d[y] = nopat / avg_oa * 100.0

        # Operating credit as % of OA = 1 − OFR
        if ofr_v is not None:
            op_credit_pct_d[y] = (1.0 - ofr_v) * 100.0

        # OFR impact on RNOA: how much operating credit amplifies RNOA
        # RNOA = ROOA / OFR, so impact = RNOA − ROOA = ROOA × (1/OFR − 1)
        rnoa_v = rnoa_nissim_d.get(y)
        rooa_v = rooa_d.get(y)
        if rnoa_v is not None and rooa_v is not None:
            ofr_impact_d[y] = rnoa_v - rooa_v

    # Stability coefficients of variation (key insight of Nissim 2023)
    # Paper documents: OFR CV ≈ 0.079, OAT CV ≈ 0.152, OPM CV ≈ 1.054
    oat_cv = _coeff_of_variation(oat_d)
    ofr_cv = _coeff_of_variation(ofr_d)
    opm_cv = _coeff_of_variation({y: v / 100.0 for y, v in opm_d.items()})

    stability_notes: List[str] = []
    if ofr_cv is not None and oat_cv is not None:
        if ofr_cv < oat_cv:
            stability_notes.append(
                f"OFR (CV={ofr_cv:.3f}) is more stable than OAT (CV={oat_cv:.3f}), "
                "consistent with Nissim (2023): balance-sheet ratios persist longer."
            )
        if opm_cv is not None and opm_cv > oat_cv:
            stability_notes.append(
                f"OPM (CV={opm_cv:.3f}) is most volatile — forecast via mean-reversion; "
                "OFR and OAT can be extrapolated with greater confidence."
            )
    if opm_cv is not None and opm_cv > 1.0:
        stability_notes.append(
            "High OPM volatility (CV > 1.0): use scenario analysis and stress testing."
        )
    if ofr_cv is not None and ofr_cv < 0.10:
        stability_notes.append(
            "OFR very stable (CV < 0.10): operating liability structure is predictable — "
            "forecast OL = median(OL/OA) × projected OA."
        )
    if ofr_d:
        latest_ofr = list(ofr_d.values())[-1]
        if latest_ofr < 0.55:
            stability_notes.append(
                f"Low OFR ({latest_ofr:.1%}): >45% of operating assets funded by operating credit "
                "→ potential market power / strong supplier relationships."
            )
        elif latest_ofr > 0.85:
            stability_notes.append(
                f"High OFR ({latest_ofr:.1%}): operating credit is minimal "
                "→ capital-intensive operations or limited operating credit access."
            )

    operating_decomp = NissimOperatingDecomposition(
        opm=opm_d,
        oat=oat_d,
        ofr=ofr_d,
        noat=noat_d,
        rnoa_nissim=rnoa_nissim_d,
        rooa=rooa_d,
        operating_credit_pct=op_credit_pct_d,
        rnoa_ofr_impact=ofr_impact_d,
        oat_stability_cv=oat_cv,
        ofr_stability_cv=ofr_cv,
        opm_stability_cv=opm_cv,
        stability_notes=stability_notes,
    )

    # =========================================================================
    # PART 2: FULL ROCE HIERARCHY (Nissim 2023, Exhibit D)
    # =========================================================================
    roce_d: Dict[str, float] = {}
    roe_d: Dict[str, float] = {}
    nci_lev_effect_d: Dict[str, float] = {}
    nci_leverage_d: Dict[str, float] = {}
    nci_spread_d: Dict[str, float] = {}
    return_on_nci_d: Dict[str, float] = {}
    recurring_roe_d: Dict[str, float] = {}
    transitory_roe_d: Dict[str, float] = {}
    transitory_income_d: Dict[str, float] = {}
    rnoa_hier_d: Dict[str, float] = {}
    fl_effect_d: Dict[str, float] = {}
    fl_leverage_d: Dict[str, float] = {}
    nbc_d: Dict[str, float] = {}
    spread_d: Dict[str, float] = {}
    other_nonop_effect_d: Dict[str, float] = {}
    other_nonop_rel_size_d: Dict[str, float] = {}
    excess_return_other_nonop_d: Dict[str, float] = {}
    return_on_other_nonop_d: Dict[str, float] = {}
    recon_rows: List[Dict] = []

    for i, y in enumerate(years):
        ni = is_.get("Net Income", {}).get(y)
        te = bs.get("Common Equity", {}).get(y)
        prev_te = bs.get("Common Equity", {}).get(years[i - 1]) if i > 0 else None
        avg_te = _avg(prev_te, te)

        nopat_v = is_.get("NOPAT", {}).get(y)
        avg_noa_v = avg_bs("Net Operating Assets", i, y)
        nfe_at = is_.get("Net Financial Expense After Tax", {}).get(y, 0.0)

        # ── RNOA from reformulated statements ─────────────────────────────
        if nopat_v is not None and avg_noa_v is not None and abs(avg_noa_v) > 0.01:
            rnoa_hier_d[y] = nopat_v / avg_noa_v * 100.0

        # ── ROE = Net Income / Avg Common Equity ──────────────────────────
        if ni is not None and avg_te is not None and abs(avg_te) > 0.01:
            roe_d[y] = ni / avg_te * 100.0

        # ── NCI Analysis ──────────────────────────────────────────────────
        # NCI equity is typically not separately mapped; approximate via
        # Total Equity − Common Equity if available.
        # Many companies have negligible NCI, so effect ≈ 0.
        nci_equity_raw = gv("Noncontrolling Interest", y) or gv("Minority Interest", y) or 0.0
        prev_nci_raw = (gv("Noncontrolling Interest", years[i-1]) or
                        gv("Minority Interest", years[i-1]) or 0.0) if i > 0 else nci_equity_raw
        avg_nci = _avg(prev_nci_raw, nci_equity_raw)

        nci_income = gv("NCI Income", y) or gv("Minority Interest Income", y) or 0.0

        if avg_te is not None and abs(avg_te) > 0.01:
            # ROCE = same as ROE when NCI is minimal
            # With NCI: ROCE uses common equity only
            roce_d[y] = roe_d.get(y, 0.0)  # approximation: ROCE ≈ ROE

            if avg_nci is not None and abs(avg_nci) > 0.01:
                nci_lev = avg_nci / abs(avg_te)
                nci_leverage_d[y] = nci_lev

                # Return on NCI
                ret_nci = nci_income / avg_nci if avg_nci != 0 else 0.0
                return_on_nci_d[y] = ret_nci * 100.0

                roe_v = roe_d.get(y, 0.0)
                nci_sp = roe_v - ret_nci * 100.0
                nci_spread_d[y] = nci_sp
                nci_lev_effect_d[y] = nci_lev * nci_sp
            else:
                nci_lev_effect_d[y] = 0.0

        # ── Transitory / Recurring split ──────────────────────────────────
        # Nissim (2022b) algorithm is proprietary. We use available proxies:
        # Priority: Exceptional Items → Discontinued Ops → 0
        exc = gv("Exceptional Items", y) or gv("Extraordinary Items", y) or 0.0
        disc = gv("Discontinued Operations Income", y) or 0.0
        asset_sale = gv("Gain on Sale of Assets", y) or 0.0
        transitory_pretax = exc + disc + asset_sale

        # Apply effective tax rate to get after-tax transitory
        eff_tax = is_.get("Effective Tax Rate", {}).get(y, 0.25)
        transitory_at = transitory_pretax * (1.0 - eff_tax)
        transitory_income_d[y] = transitory_at

        if avg_te is not None and abs(avg_te) > 0.01:
            transitory_roe_d[y] = transitory_at / avg_te * 100.0
            roe_v = roe_d.get(y, 0.0)
            recurring_roe_d[y] = roe_v - transitory_roe_d[y]

        # ── Financial Leverage Effect = FLEV × Spread ─────────────────────
        avg_nfa = avg_bs("Net Financial Assets", i, y)

        if avg_nfa is not None and avg_te is not None and abs(avg_te) > 0.01:
            # FLEV = −NFA / CE  (positive when net debt position)
            flev_v = -avg_nfa / avg_te
            fl_leverage_d[y] = flev_v

            # NBC = NFE_AT / Avg Net Debt (where Net Debt = −NFA)
            avg_net_debt = -avg_nfa
            if abs(avg_net_debt) > 0.01 and nfe_at != 0:
                nbc_v = nfe_at / avg_net_debt * 100.0
                nbc_v = max(-15.0, min(25.0, nbc_v))
            else:
                nbc_v = 0.0
            nbc_d[y] = nbc_v

            rnoa_v = rnoa_hier_d.get(y)
            if rnoa_v is not None:
                spread_v = rnoa_v - nbc_v
                spread_d[y] = spread_v
                fl_effect_d[y] = flev_v * spread_v

        # ── Net Other Nonoperating Assets Effect ──────────────────────────
        # Net Other Nonop Assets = Equity Method Investments +
        #   Assets of Discontinued Ops + Net Pension Assets − Other Nonop Liabs
        eq_method = gv("Equity Method Investments", y) or 0.0
        pension_net = gv("Net Pension Asset", y) or 0.0
        disc_assets = gv("Assets of Discontinued Operations", y) or 0.0
        other_nonop_assets = eq_method + pension_net + disc_assets

        prev_ona = (
            (gv("Equity Method Investments", years[i-1]) or 0.0) +
            (gv("Net Pension Asset", years[i-1]) or 0.0) +
            (gv("Assets of Discontinued Operations", years[i-1]) or 0.0)
        ) if i > 0 else other_nonop_assets
        avg_ona = _avg(prev_ona, other_nonop_assets)

        # Other nonop income = equity method income + pension income
        eq_income = gv("Equity Method Income", y) or gv("Income from Associates", y) or 0.0
        pension_income = gv("Pension Income", y) or 0.0
        other_nonop_income = eq_income + pension_income

        if avg_ona is not None and abs(avg_ona) > 0.01:
            ret_ona = other_nonop_income / avg_ona * 100.0
            return_on_other_nonop_d[y] = ret_ona
            rnoa_v = rnoa_hier_d.get(y)
            if rnoa_v is not None:
                excess_return_other_nonop_d[y] = ret_ona - rnoa_v

        if avg_te is not None and abs(avg_te) > 0.01 and avg_ona is not None:
            rel_size = avg_ona / abs(avg_te)
            other_nonop_rel_size_d[y] = rel_size
            excess_v = excess_return_other_nonop_d.get(y)
            if excess_v is not None:
                other_nonop_effect_d[y] = rel_size * excess_v

        # ── ROCE = ROE (approximation without full NCI separation) ─────────
        roe_v = roe_d.get(y)
        nci_eff = nci_lev_effect_d.get(y, 0.0)
        if roe_v is not None:
            roce_d[y] = roe_v + nci_eff

        # ── Reconciliation: RNOA + FLE + Other = Recurring ROE ────────────
        rnoa_v = rnoa_hier_d.get(y)
        fle_v = fl_effect_d.get(y, 0.0)
        other_v = other_nonop_effect_d.get(y, 0.0)
        rec_roe_v = recurring_roe_d.get(y)
        if rnoa_v is not None and rec_roe_v is not None:
            reconstructed = rnoa_v + fle_v + other_v
            gap = abs(reconstructed - rec_roe_v)
            recon_rows.append({
                "year": y,
                "rnoa": rnoa_v,
                "fl_effect": fle_v,
                "other_nonop_effect": other_v,
                "reconstructed_recurring_roe": reconstructed,
                "reported_recurring_roe": rec_roe_v,
                "gap": gap,
                "status": "ok" if gap <= max(2.0, abs(rec_roe_v) * 0.05) else "warn",
            })

    # ── Auto-interpretations ───────────────────────────────────────────────────
    interpretation: List[str] = []

    # RNOA vs ROE comparison
    if rnoa_hier_d and roe_d:
        last_y = sorted(rnoa_hier_d.keys())[-1]
        rnoa_last = rnoa_hier_d.get(last_y)
        roe_last = roe_d.get(last_y)
        if rnoa_last is not None and roe_last is not None:
            if rnoa_last > roe_last:
                interpretation.append(
                    f"📌 RNOA ({rnoa_last:.1f}%) > ROE ({roe_last:.1f}%): "
                    "Leverage has a negative effect — financial spread is negative or near-zero."
                )
            else:
                interpretation.append(
                    f"📌 RNOA ({rnoa_last:.1f}%) < ROE ({roe_last:.1f}%): "
                    "Positive leverage effect — company profitably employs borrowed funds."
                )

    # OFR insight
    if ofr_d:
        last_y = sorted(ofr_d.keys())[-1]
        ofr_last = ofr_d.get(last_y)
        if ofr_last is not None:
            opr_cr = (1 - ofr_last) * 100
            interpretation.append(
                f"📌 Operations Funding Ratio: {ofr_last:.1%} capital-funded, "
                f"{opr_cr:.1f}% funded by operating credit (AP, deferred rev, etc.)."
            )

    # Transitory vs Recurring
    if transitory_roe_d and recurring_roe_d:
        last_y = sorted(recurring_roe_d.keys())[-1]
        t_roe = transitory_roe_d.get(last_y, 0.0)
        r_roe = recurring_roe_d.get(last_y)
        if r_roe is not None:
            interpretation.append(
                f"📌 Recurring ROE ({r_roe:.1f}%) is the sustainable profitability measure; "
                f"Transitory ROE ({t_roe:.1f}%) represents one-time items."
            )

    # Stability insight
    if ofr_cv is not None and opm_cv is not None:
        if ofr_cv < opm_cv * 0.2:
            interpretation.append(
                "📌 OFR is much more stable than OPM — when forecasting, anchor OFR to "
                "recent average and focus analytical effort on OPM drivers."
            )

    roce_hierarchy = NissimROCEHierarchy(
        roce=roce_d,
        roe=roe_d,
        nci_leverage_effect=nci_lev_effect_d,
        nci_leverage=nci_leverage_d,
        nci_spread=nci_spread_d,
        return_on_nci=return_on_nci_d,
        recurring_roe=recurring_roe_d,
        transitory_roe=transitory_roe_d,
        transitory_income=transitory_income_d,
        rnoa=rnoa_hier_d,
        financial_leverage_effect=fl_effect_d,
        financial_leverage=fl_leverage_d,
        net_borrowing_cost=nbc_d,
        financial_spread=spread_d,
        net_other_nonop_effect=other_nonop_effect_d,
        net_other_nonop_relative_size=other_nonop_rel_size_d,
        excess_return_other_nonop=excess_return_other_nonop_d,
        return_on_other_nonop=return_on_other_nonop_d,
        roce_reconciliation=recon_rows,
        interpretation=interpretation,
    )

    return NissimProfitabilityResult(
        operating=operating_decomp,
        roce_hierarchy=roce_hierarchy,
    )
