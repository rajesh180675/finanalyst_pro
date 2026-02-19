"""Capitaline Ind AS detailed mapping + PN recast engine.

Deterministic adapter for Capitaline detailed-format exports with
operating/financing recast aligned to Penman-Nissim.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Any, Iterable, List

from .types import FinancialData


@dataclass
class CapitalineIndASConfig:
    risk_free_1y: float = 0.07
    tax_rate_fallback: float = 0.25
    oci_treated_as_unusual: bool = True
    hybrid_perpetual_as_debt: bool = True
    investment_in_subsidiaries_as_operating: bool = True
    financial_institution_mode: bool = False
    noa_epsilon_ratio_of_ta: float = 0.01
    separation_confidence_threshold: int = 70


BS_ALIASES: Dict[str, List[str]] = {
    "ta": ["Total Assets"],
    "total_equity": ["Total Equity"],
    "total_stockholders": ["Total Stockholders’ Equity", "Total Stockholders' Equity"],
    "mi_bs": ["Minority Interest"],
    # FA
    "cash": ["Cash and Cash Equivalents"],
    "bank_balances": ["Bank Balances Other Than Cash and Cash Equivalents"],
    "current_investments": ["Current Investments"],
    "long_term_investments": ["Investments - Long-term"],
    "other_fa_st": ["Others Financial Assets - Short-term"],
    "other_fa_lt": ["Others Financial Assets - Long-term"],
    "interest_receivable": ["Interest Receivable"],
    "dividend_receivable": ["Dividend Receivable"],
    "derivative_recv": ["Derivative Receivables / Forward Contract Receivable"],
    "restricted_cash": ["Restricted Cash"],
    # FO
    "lt_borrow": ["Long Term Borrowings"],
    "st_borrow": ["Short Term Borrowings"],
    "lease_liab": ["Lease Liabilities"],
    "other_fl_lt": ["Others Financial Liabilities - Long-term"],
    "other_fl_st": ["Others Financial Liabilities - Short-term"],
    "hybrid_perp": ["Hybrid Perpetual Securities"],
    # DTL/OL adjustments
    "dtl": ["Deferred Tax Liabilities (Net)", "Deferred Tax Liability"],
}

PL_ALIASES: Dict[str, List[str]] = {
    "sales": ["Revenue From Operations(Net)", "Revenue From Operations", "Total Revenue"],
    "tci_group": ["Total Comprehensive Income for the Year"],
    "tci_nci": ["Non-Controlling Interests"],
    "pref_div": ["Preference Dividend"],
    "pbt": ["Profit Before Tax", "Income Before Tax"],
    "tax": ["Tax Expense"],
    "finance_cost": ["Finance Cost", "Finance Costs"],
    "finance_income": ["Interest Income", "Finance Income", "Interest Received (P&L)"],
    "other_income": ["Other Income"],
    "exc": ["Exceptional Items Before Tax"],
    "extra": ["Extraordinary Items Before Tax"],
    "disc": ["Discontinued Operations"],
    "oci_not_reclass": ["Other Comprehensive Income That Will Not Be Reclassified to Profit Or Loss"],
    "oci_reclass": ["Other Comprehensive Income That Will Be Reclassified to Profit Or Loss"],
    "oci_unspecified": ["Other Comprehensive Income"],
    "other_items": ["Share of profit/loss of associates", "Equity accounted income"],
}

CF_ALIASES: Dict[str, List[str]] = {
    "interest_received": ["Interest Received"],
    "dividend_received": ["Dividend Received"],
    "pl_sale_invest": ["P/L on Sales of Invest"],
    "cfo": ["Net Cash from Operating Activities"],
    "capex": ["Purchased of Fixed Assets", "Purchase of Property Plant and Equipment"],
    "dividend_paid": ["Dividend Paid"],
    "equity_issued": ["Proceeds from Issue of shares (incl share premium)"],
}


def _clean(s: str) -> str:
    return " ".join(s.lower().strip().split())


def _metric_value(data: FinancialData, statement: str, aliases: Iterable[str], year: str) -> float:
    alias_set = {_clean(a) for a in aliases}
    for key, values in data.items():
        if "::" not in key:
            continue
        st, metric = key.split("::", 1)
        if st != statement:
            continue
        if _clean(metric) in alias_set:
            v = values.get(year)
            if isinstance(v, (int, float)):
                return float(v)
    return 0.0


def _safe_div(a: float, b: float) -> Optional[float]:
    return (a / b) if b != 0 else None


def _avg(curr: float, prev: float) -> float:
    return (curr + prev) / 2.0


def _effective_tax_rate(pbt: float, tax: float, fallback: float) -> float:
    if pbt == 0:
        return fallback
    rate = tax / pbt
    if 0 <= rate <= 0.5:
        return rate
    return fallback


def _compute_core_values(data: FinancialData, year: str, cfg: CapitalineIndASConfig) -> Dict[str, Any]:
    ta = _metric_value(data, "BalanceSheet", BS_ALIASES["ta"], year)
    total_equity = _metric_value(data, "BalanceSheet", BS_ALIASES["total_equity"], year)
    total_stockholders = _metric_value(data, "BalanceSheet", BS_ALIASES["total_stockholders"], year)
    mi_bs = _metric_value(data, "BalanceSheet", BS_ALIASES["mi_bs"], year)
    cse = total_stockholders if total_stockholders else total_equity - mi_bs

    if cfg.financial_institution_mode:
        fa = 0.0
        fo = 0.0
    else:
        fa = sum(
            _metric_value(data, "BalanceSheet", BS_ALIASES[k], year)
            for k in [
                "cash", "bank_balances", "current_investments", "long_term_investments",
                "other_fa_st", "other_fa_lt", "interest_receivable", "dividend_receivable",
                "derivative_recv", "restricted_cash",
            ]
        )
        fo_components = ["lt_borrow", "st_borrow", "lease_liab", "other_fl_lt", "other_fl_st"]
        if cfg.hybrid_perpetual_as_debt:
            fo_components.append("hybrid_perp")
        fo = sum(_metric_value(data, "BalanceSheet", BS_ALIASES[k], year) for k in fo_components)

    oa = ta - fa
    total_liabilities = ta - total_equity
    ol = total_liabilities - fo
    noa = oa - ol
    nfo = fo - fa

    sales = _metric_value(data, "ProfitLoss", PL_ALIASES["sales"], year)
    tci_group = _metric_value(data, "ProfitLoss", PL_ALIASES["tci_group"], year)
    tci_nci = _metric_value(data, "ProfitLoss", PL_ALIASES["tci_nci"], year)
    pref_div = _metric_value(data, "ProfitLoss", PL_ALIASES["pref_div"], year)
    cni = (tci_group - tci_nci) - pref_div

    pbt = _metric_value(data, "ProfitLoss", PL_ALIASES["pbt"], year)
    tax = _metric_value(data, "ProfitLoss", PL_ALIASES["tax"], year)
    tax_rate = _effective_tax_rate(pbt, tax, cfg.tax_rate_fallback)

    finance_cost = _metric_value(data, "ProfitLoss", PL_ALIASES["finance_cost"], year)
    finance_income = _metric_value(data, "ProfitLoss", PL_ALIASES["finance_income"], year)
    confidence = "high"
    if finance_income == 0:
        ir = _metric_value(data, "CashFlow", CF_ALIASES["interest_received"], year)
        dr = _metric_value(data, "CashFlow", CF_ALIASES["dividend_received"], year)
        finance_income = ir + dr
        if finance_income:
            confidence = "medium"
    if finance_income == 0:
        other_income = _metric_value(data, "ProfitLoss", PL_ALIASES["other_income"], year)
        fa_ratio = min(0.9, max(0.2, (fa / ta) if ta else 0.2))
        finance_income = other_income * fa_ratio
        confidence = "low"

    pl_sale_invest = _metric_value(data, "CashFlow", CF_ALIASES["pl_sale_invest"], year)
    ufe = (-pl_sale_invest) * (1 - tax_rate) if pl_sale_invest else 0.0
    core_nfe = (finance_cost - finance_income) * (1 - tax_rate) + pref_div
    nfe = core_nfe + ufe

    mii = tci_nci
    oi = cni + nfe + mii

    exc = _metric_value(data, "ProfitLoss", PL_ALIASES["exc"], year)
    extra = _metric_value(data, "ProfitLoss", PL_ALIASES["extra"], year)
    disc = _metric_value(data, "ProfitLoss", PL_ALIASES["disc"], year)
    uoi = (exc + extra + disc) * (1 - tax_rate)
    if cfg.oci_treated_as_unusual:
        uoi += _metric_value(data, "ProfitLoss", PL_ALIASES["oci_not_reclass"], year)
        uoi += _metric_value(data, "ProfitLoss", PL_ALIASES["oci_reclass"], year)
        uoi += _metric_value(data, "ProfitLoss", PL_ALIASES["oci_unspecified"], year)
    core_oi = oi - uoi

    other_items = _metric_value(data, "ProfitLoss", PL_ALIASES["other_items"], year)
    oi_from_sales = oi - other_items

    dtl = max(0.0, _metric_value(data, "BalanceSheet", BS_ALIASES["dtl"], year))
    ol_ex_dtl = max(0.0, ol - dtl)
    io = cfg.risk_free_1y * ol_ex_dtl

    identity_gap = (cse + mi_bs) - (noa - nfo)

    return {
        "year": year,
        "TA": ta,
        "CSE": cse,
        "MI": mi_bs,
        "FA": fa,
        "FO": fo,
        "OA": oa,
        "OL": ol,
        "NOA": noa,
        "NFO": nfo,
        "Sales": sales,
        "CNI": cni,
        "FinanceCost": finance_cost,
        "FinanceIncome": finance_income,
        "FinanceIncomeConfidence": confidence,
        "NFE": nfe,
        "OI": oi,
        "OtherItems": other_items,
        "OI_from_sales": oi_from_sales,
        "UOI": uoi,
        "CoreOI": core_oi,
        "UFE": ufe,
        "CoreNFE": core_nfe,
        "tax_rate": tax_rate,
        "identity_gap": identity_gap,
        "DTL": dtl,
        "io": io,
    }


def recast_period(
    data: FinancialData,
    year: str,
    prev_year: Optional[str],
    config: Optional[CapitalineIndASConfig] = None,
) -> Dict[str, Any]:
    cfg = config or CapitalineIndASConfig()
    out = _compute_core_values(data, year, cfg)

    if prev_year:
        prev = _compute_core_values(data, prev_year, cfg)
        avg_cse = _avg(out["CSE"], prev["CSE"])
        avg_noa = _avg(out["NOA"], prev["NOA"])
        avg_nfo = _avg(out["NFO"], prev["NFO"])
        avg_oa = _avg(out["OA"], prev["OA"])

        epsilon = cfg.noa_epsilon_ratio_of_ta * out["TA"] if out["TA"] else 0.0
        near_zero_noa = abs(avg_noa) < epsilon

        roce = _safe_div(out["CNI"], avg_cse)
        rnoa = None if near_zero_noa else _safe_div(out["OI"], avg_noa)
        nbc = None if near_zero_noa else _safe_div(out["NFE"], avg_nfo)
        spread = (rnoa - nbc) if (rnoa is not None and nbc is not None) else None
        flev = _safe_div(out["NFO"], out["CSE"])
        pm = _safe_div(out["OI"], out["Sales"])
        ato = None if near_zero_noa else _safe_div(out["Sales"], avg_noa)
        sales_pm = _safe_div(out["OI_from_sales"], out["Sales"])
        other_items_ratio = _safe_div(out["OtherItems"], avg_noa) if not near_zero_noa else None

        roa_operating = _safe_div(out["OI"] + out["io"], avg_oa)
        ollev = _safe_div(out["OL"], out["NOA"]) if out["NOA"] != 0 else None
        iol = _safe_div(out["io"], out["OL"])
        olspread = (roa_operating - iol) if (roa_operating is not None and iol is not None) else None

        d_noa = out["NOA"] - prev["NOA"]
        fcf_accounting = out["OI"] - d_noa

        out["ratios"] = {
            "ROCE": roce,
            "RNOA": rnoa,
            "NBC": nbc,
            "SPREAD": spread,
            "FLEV": flev,
            "PM": pm,
            "ATO": ato,
            "SalesPM": sales_pm,
            "OtherItemsRatio": other_items_ratio,
            "ROOA": roa_operating,
            "OLLEV": ollev,
            "OLSPREAD": olspread,
            "FCF_accounting": fcf_accounting,
            "suppressed_noa_ratio": near_zero_noa,
        }

        out["dividends_diagnostic"] = {
            "lhs": None,
            "rhs": None,
            "gap": None,
        }

    return out


def compute_capitaline_indas(data: FinancialData, config: Optional[CapitalineIndASConfig] = None) -> Dict[str, Any]:
    cfg = config or CapitalineIndASConfig()
    years = sorted({y for vals in data.values() for y in vals.keys()})
    periods: Dict[str, Dict[str, Any]] = {}

    for idx, year in enumerate(years):
        prev_year = years[idx - 1] if idx > 0 else None
        periods[year] = recast_period(data, year, prev_year, cfg)

    latest = periods[years[-1]] if years else {}

    score = 100
    penalties: List[str] = []
    if years:
        if latest.get("FinanceIncomeConfidence") == "medium":
            score -= 10
            penalties.append("Finance income inferred from cash flow proxies")
        elif latest.get("FinanceIncomeConfidence") == "low":
            score -= 25
            penalties.append("Finance income inferred from heuristic allocation")

        if abs(latest.get("identity_gap", 0.0)) > max(1.0, abs(latest.get("CSE", 0.0)) * 0.02):
            score -= 25
            penalties.append("Balance sheet identity gap exceeds tolerance")

        if latest.get("FO", 0.0) == 0:
            score -= 20
            penalties.append("No financial obligations detected")

        if latest.get("FA", 0.0) == 0:
            score -= 10
            penalties.append("No financial assets detected")

    score = max(0, min(100, score))
    return {
        "years": years,
        "periods": periods,
        "separation_confidence_score": score,
        "separation_confidence_label": "high" if score >= cfg.separation_confidence_threshold else "low",
        "diagnostics": penalties,
    }


def residual_earnings(
    cni_forecast: list[float],
    cse_opening: float,
    cost_of_equity: float,
    continuing: str = "CV1",
    g: float = 0.0,
) -> float:
    rho_e = 1.0 + cost_of_equity
    value = cse_opening
    res = []
    for cni in cni_forecast:
        res.append(cni - (rho_e - 1.0) * cse_opening)
    for i, re in enumerate(res, start=1):
        value += re / (rho_e ** i)
    if res:
        re_next = res[-1] * (1.0 + g)
        if continuing == "CV2":
            value += (re_next / (rho_e - 1.0)) / (rho_e ** len(res))
        elif continuing == "CV3":
            value += (re_next / (rho_e - g)) / (rho_e ** len(res))
    return value


def residual_operating_income(
    oi_forecast: list[float],
    noa_opening: float,
    wacc: float,
    continuing: str = "CV01",
    g: float = 0.0,
) -> float:
    rho_w = 1.0 + wacc
    value = noa_opening
    reoi = []
    for oi in oi_forecast:
        reoi.append(oi - (rho_w - 1.0) * noa_opening)
    for i, ri in enumerate(reoi, start=1):
        value += ri / (rho_w ** i)
    if reoi:
        ri_next = reoi[-1] * (1.0 + g)
        if continuing == "CV02":
            value += (ri_next / (rho_w - 1.0)) / (rho_w ** len(reoi))
        elif continuing == "CV03":
            value += (ri_next / (rho_w - g)) / (rho_w ** len(reoi))
    return value
