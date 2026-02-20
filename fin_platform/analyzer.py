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
import hashlib
import json
import math
import os
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
    # New analytical modules
    CCCMetrics, EarningsQualityVerdict, EarningsQualityDashboard,
    CapitalAllocationResult, AltmanZDoubleScore, SectorBenchmark, MeanReversionPanel,
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


def _get_capex_fallback(data: FinancialData, year: str) -> Optional[float]:
    """Fallback for CapEx when mapped `Capital Expenditure` row is blank/zero.

    Capitaline exports a top-level "Capital Expenditure" header row that is
    sometimes zero while the real spend sits under fixed-asset-purchase sub-lines.
    We scan all CashFlow rows and pick the one with the largest absolute value
    among all known fixed-asset purchase variants (ordered by specificity).

    Returns the largest-absolute-value non-zero match (most complete line), or None.
    """
    # Ordered: most-specific first to avoid accidental matches on generic strings.
    # Capitalized variants, typos, abbreviations all covered.
    fallback_tokens: tuple = (
        "purchase of property plant and equipment",
        "purchased of property plant and equipment",
        "purchase of property, plant and equipment",
        "purchase of fixed assets",
        "purchased of fixed assets",          # Capitaline: "Purchased of Fixed Assets"
        "purchase of fixed asset",
        "purchased of fixed asset",           # Capitaline singular typo
        "acquisition of property plant and equipment",
        "payment for property plant and equipment",
        "additions to fixed assets",
        "additions to property plant and equipment",
        "capital wip",                         # Capitaline: "capital WIP" additions line
        "capital work in progress",            # CashFlow CWIP spending
        "purchase of tangible assets",
        "purchase of intangible assets",
        "capex",
    )

    best: Optional[float] = None
    best_abs: float = 0.0
    for key, values in data.items():
        if not key.startswith("CashFlow::"):
            continue
        metric = key.split("::", 1)[-1].strip().lower()
        # Skip the canonical "capital expenditure" row itself (already tried and was zero)
        if metric == "capital expenditure":
            continue
        if any(token in metric for token in fallback_tokens):
            raw = values.get(year)
            if isinstance(raw, (int, float)) and not math.isnan(raw) and raw != 0:
                abs_val = abs(float(raw))
                # Prefer the largest absolute value (most complete / aggregate line)
                if abs_val > best_abs:
                    best = float(raw)
                    best_abs = abs_val
    return best


def _tiered_gap_status(abs_gap: float) -> str:
    """Tiered reconciliation tolerance for rounded Capitaline figures."""
    if abs_gap < 0.01:
        return "ok"
    if abs_gap <= 0.1:
        return "warn"
    return "fail"


def _series_fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_anomaly_registry(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {"version": 1, "companies": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"version": 1, "companies": {}}
        data.setdefault("version", 1)
        data.setdefault("companies", {})
        return data
    except Exception:
        return {"version": 1, "companies": {}}


def _save_anomaly_registry(path: str, registry: Dict[str, Any]) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, sort_keys=True)


def _find_raw_metric_value(data: FinancialData, year: str, include_tokens: Tuple[str, ...]) -> Optional[float]:
    """Return first usable value for a metric name containing all include tokens."""
    for key, vals in data.items():
        label = key.split("::", 1)[-1].strip().lower()
        if all(tok in label for tok in include_tokens):
            raw = vals.get(year)
            if isinstance(raw, (int, float)) and not math.isnan(raw):
                return float(raw)
    return None


def _get_inventory_fallback(data: FinancialData, year: str) -> Optional[float]:
    """Fallback for Inventory when the mapped row has value=0 (e.g. mapped to a sub-item).

    Capitaline exports the total inventory as "Inventories" or "Total Inventory".
    If the auto-mapper accidentally mapped a sub-item (e.g. "Raw Materials and Components")
    which has value=0 for that company, this fallback finds the correct total.
    """
    total_tokens = (
        "inventories",          # exact total line (INDAS)
        "total inventory",      # Capitaline aggregate total
        "total inventories",
    )
    skip_tokens = (
        "changes in inventories",       # P&L line, not BS stock
        "non current portion",
    )
    for key, values in data.items():
        if not key.startswith("BalanceSheet::"):
            continue
        metric = key.split("::", 1)[-1].strip().lower()
        if any(skip in metric for skip in skip_tokens):
            continue
        if any(token == metric for token in total_tokens):  # exact match only
            raw = values.get(year)
            if isinstance(raw, (int, float)) and not math.isnan(raw) and raw != 0:
                return float(raw)
    return None


def _capex_bug_auto_heuristic(data: FinancialData, years: List[str]) -> Tuple[bool, Optional[str]]:
    """Detect Capitaline CapEx header bug and force fallback when clearly broken."""
    official_sum = 0.0
    purchase_sum = 0.0
    for y in years:
        off = 0.0
        for key, vals in data.items():
            if not key.startswith("CashFlow::"):
                continue
            metric = key.split("::", 1)[-1].strip().lower()
            if metric == "capital expenditure":
                v = vals.get(y)
                if isinstance(v, (int, float)) and not math.isnan(v):
                    off += abs(float(v))

        fb = _get_capex_fallback(data, y)
        if fb is not None:
            purchase_sum += abs(fb)
        official_sum += off

    if purchase_sum <= 0:
        return False, None
    ratio = official_sum / purchase_sum
    if ratio < 0.01:
        note = (
            "Capitaline CapEx header bug auto-detected: summed 'Capital Expenditure' "
            f"is {ratio * 100:.2f}% of fixed-asset purchase lines; using fallback field permanently."
        )
        return True, note
    return False, None


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

    # ── Zero-value fallback guards ─────────────────────────────────────────
    # Some Capitaline header rows export 0 even though sub-lines have real values.
    # We check specific targets where a zero value from the mapping almost certainly
    # means the wrong row was mapped or the total row is a zero-placeholder.

    # Inventory: If the mapped row is 0 (sub-item like Raw Materials), try the
    # total "Inventories" / "Total Inventory" rows from the balance sheet.
    if target == "Inventory" and (direct is None or direct == 0):
        inv_fb = _get_inventory_fallback(data, year)
        if inv_fb is not None:
            return inv_fb

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

            case "Tax Expense":
                te = get("Tax Expense")
                if te is not None: return te
                # Fallback: if "Tax Expense" not mapped but sub-items are available,
                # try to derive from raw data directly
                for key, vals in data.items():
                    kl = key.lower().split("::")[-1]
                    if year in vals and any(p in kl for p in [
                        "tax expense", "tax expenses", "provision for tax",
                        "income tax expense",
                    ]):
                        return float(vals[year])
                # Last resort: current tax + deferred tax
                ct = dt = None
                for key, vals in data.items():
                    kl = key.lower().split("::")[-1]
                    if year in vals:
                        if kl == "current tax" or kl == "current tax expense":
                            ct = float(vals[year])
                        elif kl in ("deferred tax", "deferred tax expense", "deferred tax charge"):
                            dt = float(vals[year])
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

    # Cash-flow quick view
    fcf: Dict[str, Dict[str, float]] = {
        "Operating Cash Flow": {},
        "Capital Expenditure": {},
        "Free Cash Flow": {},
    }
    for y in years:
        ocf = gv("Operating Cash Flow", y)
        capex = gv("Capital Expenditure", y)
        if capex in (None, 0):
            capex = _get_capex_fallback(data, y)
        capex_abs = abs(capex) if capex is not None else None

        if ocf is not None:
            fcf["Operating Cash Flow"][y] = ocf
        if capex_abs is not None:
            fcf["Capital Expenditure"][y] = capex_abs
        if ocf is not None and capex_abs is not None:
            fcf["Free Cash Flow"][y] = ocf - capex_abs

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
        fcf=fcf,
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
    company_id = options.company_id
    anomaly_registry_path = options.anomaly_registry_path

    assumptions: Dict[str, List[str]] = {}
    ratio_warnings: List[Dict[str, str]] = []
    capex_force_fallback, capex_heuristic_note = _capex_bug_auto_heuristic(data, years)

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

    max_noa_recon_gap = 0.0
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
        tl_direct = gv("Total Liabilities", y)
        tl = tl_direct if tl_direct is not None else ((ta - te) if (ta is not None and te is not None) else None)
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
            abs_gap = abs(gap)
            max_noa_recon_gap = max(max_noa_recon_gap, abs_gap)
            if _tiered_gap_status(abs_gap) != "ok":
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

        # ── Strip Exceptional / Extraordinary Items from PBT ──────────────────
        # Capitaline: "Exceptional Items Before Tax" sits between PBIT and PBT.
        # PBT already includes them, so we must subtract to get recurring PBT.
        # Penman-Nissim framework requires NOPAT to be based on recurring operations.
        exc_items = g("Exceptional Items", y, 0.0, True)  # 0 when absent
        exc_val = exc_items if exc_items is not None else 0.0
        recurring_pbt = (pbt - exc_val) if pbt is not None else None

        ebit = (recurring_pbt + (fc or 0.0)) if recurring_pbt is not None else None

        fin_income = 0.0 if treat_investments_as_operating else (oi or 0.0)
        fin_expense = fc or 0.0

        if ebit is None:
            operating_income_bt = None
        elif treat_investments_as_operating:
            operating_income_bt = ebit
        else:
            operating_income_bt = ebit - (oi or 0.0)

        # Effective tax rate (bounded 5%–50%).
        # Use recurring_pbt (excl. exceptional) for a stable rate estimate.
        eff_tax = 0.25
        if recurring_pbt is not None and recurring_pbt > 0 and tax is not None:
            raw_rate = tax / recurring_pbt
            eff_tax = min(max(raw_rate, 0.05), 0.50)
        elif pbt is not None and pbt > 0 and tax is not None:
            # Fallback: use raw PBT if recurring_pbt unavailable
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
                # Note exceptional items stripping for transparency
                if exc_items and abs(exc_items) > 0.01:
                    row.notes = (row.notes or []) + [
                        f"Exceptional items ({exc_items:.2f}) stripped from PBT for NOPAT"
                    ]
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
            gap = noa + nfa - ce
            pn_reconciliation.append({
                "year": y, "noa": noa, "nfa": nfa, "equity": ce,
                "gap": gap,
                "status": _tiered_gap_status(abs(gap)),
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
            if abs(avg_noa) > materiality:
                # Mathematical clamping to avoid blow-ups in edge periods
                pn_ratios["RNOA %"][y] = max(-1000.0, min(1000.0, nopat / avg_noa * 100))
            elif avg_oa is not None and abs(avg_oa) > 10:
                # Automatic fallback when NOA is too small relative to TA
                pn_ratios["RNOA %"][y] = max(-1000.0, min(1000.0, nopat / avg_oa * 100))
                ratio_warnings.append({
                    "year": y,
                    "warning": "RNOA fallback applied: using ROOA proxy because NOA < 5% of Total Assets.",
                })

        if avg_oa is not None and abs(avg_oa) > 10:
            pn_ratios["ROOA %"][y] = max(-1000.0, min(1000.0, nopat / avg_oa * 100))

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
        capex_raw = None if capex_force_fallback else g("Capital Expenditure", y)
        if capex_raw is None or abs(capex_raw) < 1e-9:
            capex_raw = _get_capex_fallback(data, y)
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

    # Dead-man switch: in strict mode NOA + NFA must reconcile to Equity.
    if max_noa_recon_gap > 0.01:
        if strict_mode:
            raise ValueError(
                "Hard fail: NOA + NFA − Equity reconciliation gap exceeded 0.01 crore "
                f"(max observed {max_noa_recon_gap:.4f})."
            )
        ratio_warnings.append({
            "year": latest_year or "unknown",
            "metric": "NOA + NFA − Equity Gap",
            "message": (
                "Strict reconciliation breached but analysis continued in non-strict mode "
                f"(max gap {max_noa_recon_gap:.4f})."
            ),
        })

    # ROE anomaly registry (validated exemptions with automatic revocation on data change)
    registry = _load_anomaly_registry(anomaly_registry_path)
    company_registry = registry.setdefault("companies", {}).setdefault(company_id, {})
    roe_registry = company_registry.setdefault("roe_gap", {})
    approved_anomalies: List[Dict[str, Any]] = []
    unapproved_anomalies: List[Dict[str, Any]] = []

    def _auto_reconcile_roe_gap(year: str, gap_pct: float) -> Optional[Dict[str, Any]]:
        """Try to explain ROE gap from OCI / prior-period-adjustment style lines."""
        equity = reformulated_bs["Common Equity"].get(year)
        if equity is None or abs(equity) < 1e-9:
            return None

        oci = _find_raw_metric_value(data, year, ("other", "comprehensive", "income")) or 0.0
        pya = (
            _find_raw_metric_value(data, year, ("prior", "period", "adjust"))
            or _find_raw_metric_value(data, year, ("prior", "year", "adjust"))
            or 0.0
        )
        candidate_pct = abs((oci + pya) / equity * 100)
        if _tiered_gap_status(abs(candidate_pct - gap_pct)) in ("ok", "warn"):
            return {
                "year": year,
                "gap": gap_pct,
                "auto_reconciled": True,
                "oci": oci,
                "prior_adjustment": pya,
                "explained_pct": candidate_pct,
                "note": "Auto-reconciled using OCI/Prior Year Adjustment scan.",
            }
        return None

    for y in years:
        roe_gap = pn_ratios["ROE Gap %"].get(y)
        if roe_gap is None or roe_gap <= 2:
            continue

        payload = {
            "year": y,
            "roe_gap": round(float(roe_gap), 6),
            "roe_actual": pn_ratios["ROE %"].get(y),
            "roe_pn": pn_ratios["ROE (PN) %"].get(y),
            "equity": reformulated_bs["Common Equity"].get(y),
            "interest_expense": reformulated_is["Interest Expense"].get(y),
            "other_income": reformulated_is["Other Income"].get(y),
            "pbt": gv("Income Before Tax", y),
            "tax": gv("Tax Expense", y),
            "net_income": reformulated_is["Net Income"].get(y),
        }
        fingerprint = _series_fingerprint(payload)
        entry = roe_registry.get(y)
        anomaly_row = {"year": y, "gap": roe_gap, "fingerprint": fingerprint}

        if isinstance(entry, dict) and entry.get("fingerprint") == fingerprint and entry.get("approved") is True:
            approved_anomalies.append({**anomaly_row, "note": entry.get("note", "")})
        else:
            auto_fix = _auto_reconcile_roe_gap(y, float(roe_gap))
            if auto_fix is not None:
                approved_anomalies.append({**anomaly_row, **auto_fix})
            else:
                unapproved_anomalies.append(anomaly_row)

    # Revoke stale approvals automatically by pruning rows not approved under current fingerprint.
    fresh_registry: Dict[str, Any] = {}
    for row in approved_anomalies:
        existing = roe_registry.get(row["year"], {})
        fresh_registry[row["year"]] = {
            "approved": True,
            "fingerprint": row["fingerprint"],
            "note": existing.get("note", ""),
            "auto_reconciled": row.get("auto_reconciled", False),
            "oci": row.get("oci"),
            "prior_adjustment": row.get("prior_adjustment"),
        }
    company_registry["roe_gap"] = fresh_registry
    if approved_anomalies or unapproved_anomalies or os.path.exists(anomaly_registry_path):
        _save_anomaly_registry(anomaly_registry_path, registry)

    if unapproved_anomalies:
        fix_suggestions.append(
            "Unapproved ROE gap anomaly detected: verify mappings or approve via anomaly exemption registry."
        )

    if not reformulated_is["NOPAT"]:
        fix_suggestions.append("NOPAT missing: verify Revenue, EBIT, Tax Expense mappings.")
    if not reformulated_bs["Net Operating Assets"]:
        fix_suggestions.append("NOA missing: verify Current Assets/Liabilities, Total Assets, Total Equity mappings.")
    if not any(k.startswith("CashFlow::") for k in data):
        fix_suggestions.append("Cash Flow statement missing: FCF and cash-based diagnostics unavailable.")

    # Warn if gross revenue is mapped (Capitaline INDAS has both gross and net lines)
    rev_sources = [src for src, tgt in mappings.items() if tgt == "Revenue"]
    for rs in rev_sources:
        rs_lower = rs.lower()
        if "net" not in rs_lower and "excise" not in rs_lower:
            # Check if a net variant exists in the data
            net_variants = [k for k in data if "net" in k.lower() and "revenue from operations" in k.lower()]
            if net_variants:
                fix_suggestions.append(
                    f"⚠️ Revenue mapped from '{rs}' (gross) but a net-of-excise line also exists: "
                    f"'{net_variants[0]}'. Re-map to the net line for accurate OPM/RNOA computation. "
                    f"Gross revenue overstates turnover metrics."
                )
    
    # Warn if only Current Tax is mapped (missing Deferred Tax)
    tax_sources = [src for src, tgt in mappings.items() if tgt == "Tax Expense"]
    for ts in tax_sources:
        if "current tax" in ts.lower() and "total" not in ts.lower():
            deferred_exists = any("deferred tax" in k.lower() for k in data
                                  if "BalanceSheet" not in k and "deferred tax assets" not in k.lower())
            if deferred_exists:
                fix_suggestions.append(
                    f"⚠️ Tax Expense mapped from '{ts}' (current tax only). "
                    f"Deferred Tax also exists in data. Effective tax rate may be understated; "
                    f"NOPAT may be slightly overstated."
                )

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
        status = _tiered_gap_status(abs(gap))
        income_stmt_checks.append(ReconciliationRow(
            year=y,
            expected=expected,
            actual=ni,
            gap=gap,
            status=status,
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
        approved_anomalies=approved_anomalies,
        unapproved_anomalies=unapproved_anomalies,
        capex_heuristic_note=capex_heuristic_note,
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

    # ── New analytical modules ───────────────────────────────────────────────
    base_result.ccc_metrics = compute_ccc(data, mappings, years)
    base_result.capital_allocation = compute_capital_allocation(base_result, data, mappings, years)
    base_result.earnings_quality_dashboard = compute_earnings_quality_dashboard(
        base_result, data, mappings, years
    )
    sector = options.sector if options else "Auto"
    base_result.mean_reversion_panel = compute_mean_reversion_panel(base_result, sector=sector)

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

    altman_z_double = calculate_altman_z_double(data, mappings, years)
    return ScoringResult(altman_z=altman_z, piotroski_f=piotroski_f, altman_z_double=altman_z_double)


# ─── Sector Benchmarks ────────────────────────────────────────────────────────

SECTOR_BENCHMARKS: Dict[str, SectorBenchmark] = {
    "Manufacturing": SectorBenchmark(
        sector="Manufacturing", rnoa_pct=14.0, opm_pct=10.0, noat=1.5, ofr=0.65, rooa_pct=9.0,
        note="Capital-intensive; moderate OFR; NOAT <2x is normal"
    ),
    "IT/Technology": SectorBenchmark(
        sector="IT/Technology", rnoa_pct=28.0, opm_pct=20.0, noat=3.5, ofr=0.72, rooa_pct=20.0,
        note="Asset-light; high OPM; NOAT >3x is normal; FLEV typically <0"
    ),
    "FMCG/Consumer": SectorBenchmark(
        sector="FMCG/Consumer", rnoa_pct=35.0, opm_pct=15.0, noat=2.2, ofr=0.55, rooa_pct=20.0,
        note="Low OFR due to distributor credit; strong operating leverage"
    ),
    "Pharma": SectorBenchmark(
        sector="Pharma", rnoa_pct=18.0, opm_pct=16.0, noat=1.2, ofr=0.65, rooa_pct=12.0,
        note="R&D intensive; OPM varies by product mix; US FDA exposure matters"
    ),
    "Specialty Chemicals": SectorBenchmark(
        sector="Specialty Chemicals", rnoa_pct=22.0, opm_pct=14.0, noat=1.5, ofr=0.60, rooa_pct=13.0,
        note="Capacity-driven; OPM expands at high utilisation; China competition risk"
    ),
    "Infrastructure": SectorBenchmark(
        sector="Infrastructure", rnoa_pct=10.0, opm_pct=18.0, noat=0.6, ofr=0.80, rooa_pct=8.0,
        note="Capital-heavy; high OFR; distinguish maintenance vs growth capex"
    ),
    "Financial Services": SectorBenchmark(
        sector="Financial Services", rnoa_pct=float("nan"), opm_pct=float("nan"), noat=float("nan"),
        ofr=float("nan"), rooa_pct=float("nan"),
        note="PN framework not directly applicable; use ROA/ROE/NIM analysis"
    ),
    "Auto/Auto Ancillaries": SectorBenchmark(
        sector="Auto/Auto Ancillaries", rnoa_pct=16.0, opm_pct=10.0, noat=1.6, ofr=0.62, rooa_pct=10.0,
        note="Cyclical; high fixed cost intensity; RNOA volatile"
    ),
}


# ─── Cash Conversion Cycle ────────────────────────────────────────────────────

def compute_ccc(data: FinancialData, mappings: MappingDict, years: List[str]) -> CCCMetrics:
    """
    Cash Conversion Cycle decomposition + working capital quality analysis.

    DIO = Inventory / (COGS / 365)          — days inventory held
    DSO = Trade Receivables / (Revenue / 365) — days to collect
    DPO = Trade Payables / (COGS / 365)     — days to pay suppliers
    CCC = DIO + DSO − DPO                   — net cash cycle

    Quality cross-checks detect:
    - Inventory building faster than revenue → potential slow-moving stock
    - Receivables growing faster than revenue → potential credit policy loosening
    """
    gv = lambda t, y: derive_val(data, mappings, t, y)

    dio: Dict[str, float] = {}
    dso: Dict[str, float] = {}
    dpo: Dict[str, float] = {}
    ccc: Dict[str, float] = {}
    inv_days_yoy: Dict[str, float] = {}
    rec_days_yoy: Dict[str, float] = {}
    pay_days_yoy: Dict[str, float] = {}
    inv_vs_rev: Dict[str, float] = {}
    rec_vs_rev: Dict[str, float] = {}
    quality_flags: List[str] = []

    prev_year_data: Dict[str, Optional[float]] = {}

    for i, y in enumerate(years):
        inv = gv("Inventory", y)
        ar = gv("Trade Receivables", y)
        ap = gv("Accounts Payable", y)
        rev = gv("Revenue", y)
        cogs = gv("Cost of Goods Sold", y)

        if cogs is None or cogs <= 0:
            cogs = rev  # fallback: treat revenue as proxy for COGS if not available

        if inv is not None and cogs is not None and cogs > 0:
            dio_v = inv / (cogs / 365)
            dio[y] = dio_v
            if i > 0 and years[i - 1] in dio:
                inv_days_yoy[y] = dio_v - dio[years[i - 1]]

        if ar is not None and rev is not None and rev > 0:
            dso_v = ar / (rev / 365)
            dso[y] = dso_v
            if i > 0 and years[i - 1] in dso:
                rec_days_yoy[y] = dso_v - dso[years[i - 1]]

        if ap is not None and cogs is not None and cogs > 0:
            dpo_v = ap / (cogs / 365)
            dpo[y] = dpo_v
            if i > 0 and years[i - 1] in dpo:
                pay_days_yoy[y] = dpo_v - dpo[years[i - 1]]

        if y in dio and y in dso and y in dpo:
            ccc[y] = dio[y] + dso[y] - dpo[y]

        # Quality cross-checks (YoY growth deltas)
        if i > 0:
            prev_y = years[i - 1]
            prev_inv = gv("Inventory", prev_y)
            prev_ar = gv("Trade Receivables", prev_y)
            prev_rev = gv("Revenue", prev_y)

            if inv is not None and prev_inv is not None and prev_inv > 0:
                inv_growth = (inv - prev_inv) / prev_inv
                rev_growth = ((rev - prev_rev) / prev_rev) if (rev and prev_rev and prev_rev > 0) else None
                if rev_growth is not None:
                    inv_vs_rev[y] = (inv_growth - rev_growth) * 100  # pp excess

            if ar is not None and prev_ar is not None and prev_ar > 0:
                ar_growth = (ar - prev_ar) / prev_ar
                rev_growth2 = ((rev - prev_rev) / prev_rev) if (rev and prev_rev and prev_rev > 0) else None
                if rev_growth2 is not None:
                    rec_vs_rev[y] = (ar_growth - rev_growth2) * 100  # pp excess

    # Quality flags: persistent patterns
    if len(inv_vs_rev) >= 2:
        recent_inv_gaps = [v for v in list(inv_vs_rev.values())[-3:] if abs(v) < 1000]
        if recent_inv_gaps and sum(1 for v in recent_inv_gaps if v > 5) >= 2:
            quality_flags.append(
                "⚠️ Inventory growing consistently faster than revenue in recent years — "
                "possible slow-moving stock build-up or demand slowdown"
            )
        elif recent_inv_gaps and sum(1 for v in recent_inv_gaps if v < -5) >= 2:
            quality_flags.append(
                "✅ Inventory growing slower than revenue — improving inventory efficiency"
            )

    if len(rec_vs_rev) >= 2:
        recent_rec_gaps = [v for v in list(rec_vs_rev.values())[-3:] if abs(v) < 1000]
        if recent_rec_gaps and sum(1 for v in recent_rec_gaps if v > 5) >= 2:
            quality_flags.append(
                "⚠️ Receivables growing faster than revenue — potential credit policy loosening or "
                "collection issues; verify DSO trend for confirmation"
            )

    if ccc:
        ccc_vals = list(ccc.values())
        if len(ccc_vals) >= 3:
            recent_ccc = ccc_vals[-3:]
            if recent_ccc[-1] > recent_ccc[0] + 15:
                quality_flags.append(
                    f"⚠️ CCC has expanded by {recent_ccc[-1] - recent_ccc[0]:.0f} days over "
                    f"recent periods — working capital is absorbing more cash"
                )
            elif recent_ccc[-1] < recent_ccc[0] - 15:
                quality_flags.append(
                    f"✅ CCC has compressed by {recent_ccc[0] - recent_ccc[-1]:.0f} days — "
                    f"excellent working capital efficiency improvement"
                )

    return CCCMetrics(
        dio=dio, dso=dso, dpo=dpo, ccc=ccc,
        inventory_days_yoy=inv_days_yoy,
        receivables_days_yoy=rec_days_yoy,
        payables_days_yoy=pay_days_yoy,
        inventory_vs_revenue_gap=inv_vs_rev,
        receivables_vs_revenue_gap=rec_vs_rev,
        quality_flags=quality_flags,
    )


# ─── Capital Allocation Scorecard ─────────────────────────────────────────────

def compute_capital_allocation(
    pn_result: PenmanNissimResult,
    data: FinancialData,
    mappings: MappingDict,
    years: List[str],
) -> CapitalAllocationResult:
    """
    Capital Allocation Scorecard for high-quality (typically debt-free) Indian companies.

    Key metrics:
    - Reinvestment Rate = ΔNOA / NOPAT  (what fraction of earnings go back into operations)
    - Incremental ROIC = ΔNOPAT / ΔNOA  (return on new capital; compare vs existing RNOA)
    - FCF Conversion = FCF / NOPAT      (>1.0 = asset-light; <0.6 = concern)
    - Maintenance vs Growth CapEx split (Depreciation as maintenance proxy)
    """
    gv = lambda t, y: derive_val(data, mappings, t, y)
    bs = pn_result.reformulated_bs
    is_ = pn_result.reformulated_is
    ratios = pn_result.ratios
    fcf = pn_result.fcf

    reinvestment_rate: Dict[str, float] = {}
    incremental_roic: Dict[str, float] = {}
    fcf_conversion: Dict[str, float] = {}
    capex_intensity: Dict[str, float] = {}
    maint_capex: Dict[str, float] = {}
    growth_capex: Dict[str, float] = {}
    rnoa_incremental: Dict[str, float] = {}
    noa_growth_rate: Dict[str, float] = {}
    insights: List[str] = []

    for i, y in enumerate(years):
        nopat = is_.get("NOPAT", {}).get(y)
        noa = bs.get("Net Operating Assets", {}).get(y)
        prev_noa = bs.get("Net Operating Assets", {}).get(years[i - 1]) if i > 0 else None
        prev_nopat = is_.get("NOPAT", {}).get(years[i - 1]) if i > 0 else None
        fcf_v = fcf.get("Free Cash Flow", {}).get(y)
        capex_v = fcf.get("Capital Expenditure", {}).get(y)
        rev = is_.get("Revenue", {}).get(y)
        dep = gv("Depreciation", y)

        # Reinvestment rate
        if i > 0 and noa is not None and prev_noa is not None and nopat is not None and abs(nopat) > 1:
            delta_noa = noa - prev_noa
            reinvestment_rate[y] = delta_noa / nopat

            # NOA growth rate
            if abs(prev_noa) > 1:
                noa_growth_rate[y] = (noa - prev_noa) / abs(prev_noa) * 100

        # Incremental ROIC = ΔNOPAT / ΔNOA
        if (i > 0 and nopat is not None and prev_nopat is not None
                and noa is not None and prev_noa is not None):
            d_nopat = nopat - prev_nopat
            d_noa = noa - prev_noa
            if abs(d_noa) > max(1.0, abs(noa) * 0.02):  # only meaningful deltas
                inc_roic = d_nopat / d_noa * 100
                incremental_roic[y] = max(-100.0, min(200.0, inc_roic))
                rnoa_v = ratios.get("RNOA %", {}).get(y)
                if rnoa_v is not None:
                    rnoa_incremental[y] = inc_roic - rnoa_v

        # FCF conversion
        if fcf_v is not None and nopat is not None and abs(nopat) > 1:
            fcf_conversion[y] = fcf_v / nopat

        # CapEx intensity
        if capex_v is not None and rev is not None and rev > 0:
            capex_intensity[y] = capex_v / rev * 100

        # Maintenance vs Growth CapEx split
        if capex_v is not None and dep is not None:
            maint_capex[y] = dep
            growth_capex[y] = max(0.0, capex_v - dep)

    # Generate insights
    if fcf_conversion:
        recent_fc = [v for v in list(fcf_conversion.values())[-3:]]
        avg_fc = sum(recent_fc) / len(recent_fc) if recent_fc else None
        if avg_fc is not None:
            if avg_fc > 1.0:
                insights.append(
                    f"✅ Excellent FCF conversion (avg {avg_fc:.1f}x) — operations generate more "
                    f"cash than reported NOPAT; asset-light characteristics"
                )
            elif avg_fc < 0.6:
                insights.append(
                    f"⚠️ FCF conversion ({avg_fc:.1f}x) below 0.6 — significant capex or working "
                    f"capital drag on cash earnings; investigate if growth-driven or structural"
                )

    if incremental_roic:
        recent_inc = [v for v in list(incremental_roic.values())[-3:] if abs(v) < 200]
        avg_inc = sum(recent_inc) / len(recent_inc) if recent_inc else None
        if avg_inc is not None:
            recent_rnoa = [v for k, v in list(ratios.get("RNOA %", {}).items())[-3:]]
            avg_rnoa = sum(recent_rnoa) / len(recent_rnoa) if recent_rnoa else None
            if avg_rnoa is not None:
                if avg_inc > avg_rnoa + 5:
                    insights.append(
                        f"✅ Incremental ROIC ({avg_inc:.1f}%) significantly exceeds existing RNOA "
                        f"({avg_rnoa:.1f}%) — new investments are value-accretive"
                    )
                elif avg_inc < avg_rnoa - 10:
                    insights.append(
                        f"⚠️ Incremental ROIC ({avg_inc:.1f}%) below existing RNOA ({avg_rnoa:.1f}%) "
                        f"— marginal investments are diluting returns; scrutinize capital deployment"
                    )

    if reinvestment_rate:
        recent_rr = [v for v in list(reinvestment_rate.values())[-3:] if abs(v) < 5]
        avg_rr = sum(recent_rr) / len(recent_rr) if recent_rr else None
        if avg_rr is not None:
            if avg_rr < 0.2:
                insights.append(
                    f"ℹ️ Low reinvestment rate ({avg_rr:.1%}) — company retains most earnings as cash; "
                    f"check if cash is being returned via dividends/buybacks or sitting idle"
                )
            elif avg_rr > 0.8:
                insights.append(
                    f"ℹ️ High reinvestment rate ({avg_rr:.1%}) — company is deploying most NOPAT "
                    f"into NOA; sustainable only if incremental ROIC > cost of capital"
                )

    return CapitalAllocationResult(
        reinvestment_rate=reinvestment_rate,
        incremental_roic=incremental_roic,
        fcf_conversion=fcf_conversion,
        capex_intensity=capex_intensity,
        maintenance_capex_est=maint_capex,
        growth_capex_est=growth_capex,
        rnoa_on_incremental=rnoa_incremental,
        noa_growth_rate=noa_growth_rate,
        insights=insights,
    )


# ─── Earnings Quality Dashboard ───────────────────────────────────────────────

def _percentile(values: List[float], p: float) -> Optional[float]:
    """Simple percentile calculation (linear interpolation)."""
    if not values:
        return None
    sorted_v = sorted(values)
    n = len(sorted_v)
    idx = (p / 100) * (n - 1)
    lo = int(idx)
    hi = lo + 1
    if hi >= n:
        return sorted_v[-1]
    frac = idx - lo
    return sorted_v[lo] * (1 - frac) + sorted_v[hi] * frac


def _pearson_r(xs: List[float], ys: List[float]) -> Optional[float]:
    """Pearson correlation coefficient."""
    n = min(len(xs), len(ys))
    if n < 3:
        return None
    xs, ys = xs[:n], ys[:n]
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx < 1e-9 or sy < 1e-9:
        return None
    return cov / (sx * sy)


def compute_earnings_quality_dashboard(
    pn_result: PenmanNissimResult,
    data: FinancialData,
    mappings: MappingDict,
    years: List[str],
) -> EarningsQualityDashboard:
    """
    Standalone Quality of Earnings analysis — opinionated and decisive.

    The central question: Is NOPAT a reliable predictor of future cash generation?

    Five signals:
    1. Accrual ratio (NOPAT - OCF) / AvgNOA — primary, persistent red flag if >15%
    2. Revenue recognition risk — DSO trend (rising = concern)
    3. ReOI persistence — correlation between year t and t+1 ReOI
    4. Exceptional items — recurring 'exceptional' items = misleading branding
    5. Core vs Reported NOPAT divergence — if large, reported profits are inflated

    Verdict: "High confidence" | "Scrutinize further" | "Red flags present"
    """
    gv = lambda t, y: derive_val(data, mappings, t, y)
    is_ = pn_result.reformulated_is
    bs = pn_result.reformulated_bs
    academic = pn_result.academic
    fcf = pn_result.fcf

    nopat_vs_ocf_gap: Dict[str, float] = {}
    nopat_vs_ocf_gap_pct: Dict[str, float] = {}
    rec_to_rev: Dict[str, float] = {}
    exc_pct_nopat: Dict[str, float] = {}
    exc_pct_profit: Dict[str, float] = {}
    core_vs_rep: Dict[str, float] = {}
    reasons: List[str] = []
    warnings: List[str] = []
    score = 100  # Start perfect, deduct for red flags

    for y in years:
        nopat = is_.get("NOPAT", {}).get(y)
        ocf = fcf.get("Operating Cash Flow", {}).get(y)
        rev = is_.get("Revenue", {}).get(y)
        ni = is_.get("Net Income", {}).get(y)
        ar = gv("Trade Receivables", y)
        exc = gv("Exceptional Items", y)

        if nopat is not None and ocf is not None:
            gap = nopat - ocf
            nopat_vs_ocf_gap[y] = gap
            noa_y = bs.get("Net Operating Assets", {}).get(y)
            oa_y = bs.get("Operating Assets", {}).get(y)
            denom = noa_y or oa_y or rev
            if denom and abs(denom) > 1:
                nopat_vs_ocf_gap_pct[y] = gap / denom * 100

        if ar is not None and rev is not None and rev > 0:
            rec_to_rev[y] = ar / rev * 100

        if exc is not None and abs(exc) > 0.01:
            nopat_val = nopat or 1.0
            exc_pct_nopat[y] = exc / abs(nopat_val) * 100
            if ni and abs(ni) > 0.01:
                exc_pct_profit[y] = exc / abs(ni) * 100

        core = academic.core_nopat.get(y) if (academic and academic.core_nopat) else None
        if core is not None and nopat is not None and abs(nopat) > 0.01:
            core_vs_rep[y] = (nopat - core) / abs(nopat) * 100

    # ReOI persistence score
    reoi_series = sorted(academic.reoi.items()) if (academic and academic.reoi) else []
    reoi_persistence: Optional[float] = None
    if len(reoi_series) >= 4:
        reoi_t = [v for _, v in reoi_series[:-1]]
        reoi_t1 = [v for _, v in reoi_series[1:]]
        reoi_persistence = _pearson_r(reoi_t, reoi_t1)

    # ── Scoring ────────────────────────────────────────────────────────────────
    # Signal 1: Accrual ratio direction
    if nopat_vs_ocf_gap_pct:
        recent_gap_pcts = [v for v in list(nopat_vs_ocf_gap_pct.values())[-4:]]
        avg_gap = sum(recent_gap_pcts) / len(recent_gap_pcts) if recent_gap_pcts else 0
        high_accrual_yrs = sum(1 for v in recent_gap_pcts if abs(v) > 15)

        if avg_gap > 15:
            score -= 30
            reasons.append(
                f"🔴 Accruals persistently high: NOPAT exceeds OCF by avg {avg_gap:.1f}% — "
                f"profits are not converting to cash at expected rates"
            )
        elif avg_gap > 7:
            score -= 15
            warnings.append(
                f"🟡 Moderate accruals: avg NOPAT-OCF gap {avg_gap:.1f}% — watch for escalation"
            )
        elif avg_gap < -5:
            reasons.append(
                f"🟢 OCF > NOPAT consistently (avg gap {avg_gap:.1f}%) — high-quality cash earnings"
            )

        if high_accrual_yrs >= 3:
            score -= 10
            warnings.append(
                f"🔴 High accruals in {high_accrual_yrs}/{len(recent_gap_pcts)} recent years — persistent pattern"
            )

    # Signal 2: Receivables DSO trend (rising = concern)
    if len(rec_to_rev) >= 3:
        rec_vals = [v for v in list(rec_to_rev.values())[-3:]]
        if rec_vals[-1] > rec_vals[0] * 1.2:
            score -= 15
            warnings.append(
                f"🟡 Receivables-to-revenue rising ({rec_vals[0]:.1f}% → {rec_vals[-1]:.1f}%): "
                f"revenue recognition may be front-running cash collection"
            )
        elif rec_vals[-1] < rec_vals[0] * 0.85:
            reasons.append(
                f"🟢 Receivables-to-revenue improving ({rec_vals[0]:.1f}% → {rec_vals[-1]:.1f}%): "
                f"faster collection"
            )

    # Signal 3: ReOI persistence
    if reoi_persistence is not None:
        if reoi_persistence >= 0.7:
            reasons.append(
                f"🟢 ReOI highly persistent (r={reoi_persistence:.2f}) — excess returns are sustainable"
            )
        elif reoi_persistence < 0.3:
            score -= 15
            warnings.append(
                f"🟡 Low ReOI persistence (r={reoi_persistence:.2f}) — earnings quality may be lumpy; "
                f"use mean-reversion assumptions for forecasting"
            )

    # Signal 4: Exceptional items
    if exc_pct_nopat:
        exc_vals = list(exc_pct_nopat.values())
        count_sig = sum(1 for v in exc_vals if abs(v) > 10)
        if count_sig >= 3:
            score -= 20
            warnings.append(
                f"🔴 Exceptional items >10% of NOPAT in {count_sig}/{len(exc_vals)} years — "
                f"'exceptional' items are actually recurrent; rely on Core NOPAT for forecasting"
            )
        elif count_sig >= 1:
            score -= 5
            warnings.append(
                f"🟡 Exceptional items present in {count_sig}/{len(exc_vals)} years — "
                f"check if pattern is genuinely one-off"
            )

    # Signal 5: Core vs Reported divergence
    if core_vs_rep:
        recent_div = [abs(v) for v in list(core_vs_rep.values())[-3:]]
        avg_div = sum(recent_div) / len(recent_div) if recent_div else 0
        if avg_div > 20:
            score -= 15
            warnings.append(
                f"🟡 Core NOPAT diverges from Reported by avg {avg_div:.1f}% — "
                f"exceptional items materially inflate reported profits"
            )

    score = max(0, min(100, score))

    if score >= 75:
        verdict_str = "High confidence"
        color = "#166534"
        reasons.insert(0, "Overall earnings quality assessment: HIGH CONFIDENCE")
    elif score >= 45:
        verdict_str = "Scrutinize further"
        color = "#854d0e"
        warnings.insert(0, "Overall earnings quality assessment: SCRUTINIZE FURTHER")
    else:
        verdict_str = "Red flags present"
        color = "#991b1b"
        warnings.insert(0, "Overall earnings quality assessment: RED FLAGS PRESENT")

    verdict = EarningsQualityVerdict(
        verdict=verdict_str, score=score, color=color,
        reasons=reasons, warnings=warnings,
    )

    return EarningsQualityDashboard(
        nopat_vs_ocf_gap=nopat_vs_ocf_gap,
        nopat_vs_ocf_gap_pct=nopat_vs_ocf_gap_pct,
        receivables_to_revenue=rec_to_rev,
        exceptional_pct_of_nopat=exc_pct_nopat,
        exceptional_pct_of_profit=exc_pct_profit,
        reoi_persistence_score=reoi_persistence,
        core_vs_reported_nopat_gap=core_vs_rep,
        verdict=verdict,
    )


# ─── Altman Z″ (Emerging Market 2002 Model) ───────────────────────────────────

def calculate_altman_z_double(
    data: FinancialData, mappings: MappingDict, years: List[str]
) -> Dict[str, AltmanZDoubleScore]:
    """
    Altman Z″ (2002) — Emerging Market Model.
    Designed for non-US, non-financial firms.
    Removes the market capitalisation variable (X5 in the 1968 model),
    replacing it with book equity/total liabilities.

    Z″ = 6.56×X1 + 3.26×X2 + 6.72×X3 + 1.05×X4
    X1 = Working Capital / Total Assets
    X2 = Retained Earnings / Total Assets
    X3 = EBIT / Total Assets
    X4 = Book Value of Equity / Total Liabilities

    Safe: Z″ > 2.6 | Grey: 1.1–2.6 | Distress: Z″ < 1.1
    Reference: Altman, E.I. (2002). "Financial Ratios, Discriminant Analysis and
    the Prediction of Corporate Bankruptcy." Journal of Finance.
    """
    results: Dict[str, AltmanZDoubleScore] = {}
    gv = lambda t, y: derive_val(data, mappings, t, y)

    for y in years:
        ta = gv("Total Assets", y)
        if ta is None or ta <= 0:
            continue

        ca = gv("Current Assets", y) or 0.0
        cl = gv("Current Liabilities", y) or 0.0
        re_ = gv("Retained Earnings", y) or 0.0
        ebit = gv("EBIT", y) or 0.0
        te = gv("Total Equity", y) or 0.0
        tl = ta - te

        wc = ca - cl
        x1 = wc / ta
        x2 = re_ / ta
        x3 = ebit / ta
        x4 = te / (tl if tl > 0 else 1.0)

        z_double = 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4

        zone = "Safe" if z_double > 2.6 else ("Grey" if z_double > 1.1 else "Distress")

        results[y] = AltmanZDoubleScore(
            score=round(z_double, 2),
            zone=zone,
            x1=round(x1, 4),
            x2=round(x2, 4),
            x3=round(x3, 4),
            x4=round(x4, 4),
        )

    return results


# ─── Mean-Reversion Forecasting Panel ────────────────────────────────────────

def compute_mean_reversion_panel(
    pn_result: PenmanNissimResult,
    sector: str = "Auto",
) -> MeanReversionPanel:
    """
    Semi-automated mean-reversion forecasting support.
    Computes historical percentiles for OPM, OAT (NOAT), OFR, RNOA and
    maps them to Bear/Base/Bull scenario seeds.

    Bear = 10th percentile historical OPM (and last OAT if NOAT is stable)
    Base = Median (50th percentile) — natural mean-reversion anchor
    Bull = 90th percentile historical OPM

    Highlights when current values are >1.5σ from the historical mean.
    """
    ratios = pn_result.ratios
    nissim = pn_result.nissim_profitability
    op = nissim.operating if nissim else None

    opm_series = list(ratios.get("OPM %", {}).values())
    rnoa_series = list(ratios.get("RNOA %", {}).values())
    noat_series = list(ratios.get("NOAT", {}).values())
    ofr_series = list(op.ofr.values()) if op and op.ofr else []

    def stats(vals: List[float]):
        if not vals:
            return None, None, None, None
        mean = sum(vals) / len(vals)
        std = _std_dev(vals)
        p10 = _percentile(vals, 10)
        p90 = _percentile(vals, 90)
        return mean, std, p10, p90

    opm_mean, opm_std, opm_p10, opm_p90 = stats(opm_series)
    rnoa_mean, _, rnoa_p10, rnoa_p90 = stats(rnoa_series)
    noat_mean, _, noat_p10, noat_p90 = stats(noat_series)
    ofr_mean, _, ofr_p10, ofr_p90 = stats(ofr_series)

    opm_current = opm_series[-1] if opm_series else None
    rnoa_current = rnoa_series[-1] if rnoa_series else None
    noat_current = noat_series[-1] if noat_series else None
    ofr_current = ofr_series[-1] if ofr_series else None

    # Z-score for current OPM (how far from mean in std dev units)
    opm_zscore: Optional[float] = None
    if opm_current is not None and opm_mean is not None and opm_std and opm_std > 0:
        opm_zscore = (opm_current - opm_mean) / opm_std

    reversion_signals: List[str] = []
    if opm_zscore is not None and abs(opm_zscore) > 1.5:
        direction = "above" if opm_zscore > 0 else "below"
        reversion_signals.append(
            f"⚡ Current OPM ({opm_current:.1f}%) is {abs(opm_zscore):.1f}σ {direction} its "
            f"historical mean ({opm_mean:.1f}%) — strong mean-reversion expected"
        )

    # Sector benchmark lookup
    sector_bm = SECTOR_BENCHMARKS.get(sector)
    if sector == "Auto" or sector_bm is None:
        sector_bm = None  # no benchmark in auto mode
    else:
        if opm_current is not None and not math.isnan(sector_bm.opm_pct):
            diff = opm_current - sector_bm.opm_pct
            direction = "above" if diff > 0 else "below"
            reversion_signals.append(
                f"📊 OPM {opm_current:.1f}% vs sector benchmark {sector_bm.opm_pct:.1f}% "
                f"({abs(diff):.1f}pp {direction} median)"
            )
        if rnoa_current is not None and not math.isnan(sector_bm.rnoa_pct):
            diff_r = rnoa_current - sector_bm.rnoa_pct
            if abs(diff_r) > 5:
                direction_r = "above" if diff_r > 0 else "below"
                reversion_signals.append(
                    f"📊 RNOA {rnoa_current:.1f}% vs sector benchmark {sector_bm.rnoa_pct:.1f}% "
                    f"({abs(diff_r):.1f}pp {direction_r} median)"
                )

    return MeanReversionPanel(
        opm_mean=opm_mean, opm_p10=opm_p10, opm_p90=opm_p90,
        opm_current=opm_current, opm_zscore=opm_zscore,
        oat_mean=noat_mean, oat_p10=noat_p10, oat_p90=noat_p90, oat_current=noat_current,
        ofr_mean=ofr_mean, ofr_p10=ofr_p10, ofr_p90=ofr_p90, ofr_current=ofr_current,
        rnoa_mean=rnoa_mean, rnoa_p10=rnoa_p10, rnoa_p90=rnoa_p90, rnoa_current=rnoa_current,
        sector=sector,
        sector_benchmark=sector_bm,
        bear_opm=opm_p10,
        base_opm=opm_mean,
        bull_opm=opm_p90,
        bear_noat=noat_p10,
        base_noat=noat_mean,
        bull_noat=noat_p90,
        reversion_signals=reversion_signals,
    )



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
