"""Capitaline Ind AS detailed mapping + PN recast engine.

This module implements a deterministic adapter for Capitaline detailed-format
exports, with operating vs financing recast aligned to Penman-Nissim.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Any

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


def _clean(s: str) -> str:
    return " ".join(s.lower().strip().split())


def _metric_value(data: FinancialData, statement: str, aliases: list[str], year: str) -> float:
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
    return (a / b) if b not in (0.0, -0.0) else None


def _avg(curr: float, prev: float) -> float:
    return (curr + prev) / 2.0


def recast_period(data: FinancialData, year: str, prev_year: Optional[str], config: Optional[CapitalineIndASConfig] = None) -> Dict[str, Any]:
    cfg = config or CapitalineIndASConfig()

    ta = _metric_value(data, "BalanceSheet", ["Total Assets"], year)
    total_equity = _metric_value(data, "BalanceSheet", ["Total Equity"], year)
    total_stockholders = _metric_value(data, "BalanceSheet", ["Total Stockholders’ Equity", "Total Stockholders' Equity"], year)
    mi_bs = _metric_value(data, "BalanceSheet", ["Minority Interest"], year)
    cse = total_stockholders if total_stockholders else total_equity - mi_bs

    # Financial assets
    fa = 0.0
    fa += _metric_value(data, "BalanceSheet", ["Cash and Cash Equivalents"], year)
    fa += _metric_value(data, "BalanceSheet", ["Bank Balances Other Than Cash and Cash Equivalents"], year)
    fa += _metric_value(data, "BalanceSheet", ["Current Investments"], year)
    fa += _metric_value(data, "BalanceSheet", ["Investments - Long-term"], year)
    fa += _metric_value(data, "BalanceSheet", ["Others Financial Assets - Short-term"], year)
    fa += _metric_value(data, "BalanceSheet", ["Others Financial Assets - Long-term"], year)

    # Financial obligations
    fo = 0.0
    fo += _metric_value(data, "BalanceSheet", ["Long Term Borrowings"], year)
    fo += _metric_value(data, "BalanceSheet", ["Short Term Borrowings"], year)
    fo += _metric_value(data, "BalanceSheet", ["Lease Liabilities"], year)
    fo += _metric_value(data, "BalanceSheet", ["Others Financial Liabilities - Long-term"], year)
    fo += _metric_value(data, "BalanceSheet", ["Others Financial Liabilities - Short-term"], year)
    if cfg.hybrid_perpetual_as_debt:
        fo += _metric_value(data, "BalanceSheet", ["Hybrid Perpetual Securities"], year)

    oa = ta - fa
    total_liabilities = ta - total_equity
    ol = total_liabilities - fo
    noa = oa - ol
    nfo = fo - fa

    # Income recast
    sales = _metric_value(data, "ProfitLoss", ["Revenue From Operations(Net)", "Revenue From Operations", "Total Revenue"], year)
    tci_group = _metric_value(data, "ProfitLoss", ["Total Comprehensive Income for the Year"], year)
    tci_nci = _metric_value(data, "ProfitLoss", ["Non-Controlling Interests"], year)
    pref_div = _metric_value(data, "ProfitLoss", ["Preference Dividend"], year)
    cni = (tci_group - tci_nci) - pref_div

    pbt = _metric_value(data, "ProfitLoss", ["Profit Before Tax", "Income Before Tax"], year)
    tax = _metric_value(data, "ProfitLoss", ["Tax Expense"], year)
    tax_rate = cfg.tax_rate_fallback
    if pbt:
        rate = tax / pbt
        if 0 <= rate <= 0.5:
            tax_rate = rate

    finance_cost = _metric_value(data, "ProfitLoss", ["Finance Cost", "Finance Costs"], year)
    finance_income = _metric_value(data, "ProfitLoss", ["Interest Income", "Finance Income", "Interest Received"], year)
    confidence = "high"
    if finance_income == 0:
        ir = _metric_value(data, "CashFlow", ["Interest Received"], year)
        dr = _metric_value(data, "CashFlow", ["Dividend Received"], year)
        finance_income = ir + dr
        if finance_income:
            confidence = "medium"
    if finance_income == 0:
        other_income = _metric_value(data, "ProfitLoss", ["Other Income"], year)
        fa_ratio = min(0.9, max(0.2, (fa / ta) if ta else 0.2))
        finance_income = other_income * fa_ratio
        confidence = "low"

    pl_sale_invest = _metric_value(data, "CashFlow", ["P/L on Sales of Invest"], year)
    ufe = (-pl_sale_invest) * (1 - tax_rate) if pl_sale_invest else 0.0

    core_nfe = (finance_cost - finance_income) * (1 - tax_rate) + pref_div
    nfe = core_nfe + ufe
    mii = tci_nci
    oi = cni + nfe + mii

    exc = _metric_value(data, "ProfitLoss", ["Exceptional Items Before Tax"], year)
    extra = _metric_value(data, "ProfitLoss", ["Extraordinary Items Before Tax"], year)
    disc = _metric_value(data, "ProfitLoss", ["Discontinued Operations"], year)
    uoi = (exc + extra + disc) * (1 - tax_rate)
    if cfg.oci_treated_as_unusual:
        oci_not = _metric_value(data, "ProfitLoss", ["Other Comprehensive Income That Will Not Be Reclassified to Profit Or Loss"], year)
        oci_rec = _metric_value(data, "ProfitLoss", ["Other Comprehensive Income That Will Be Reclassified to Profit Or Loss"], year)
        oci_uns = _metric_value(data, "ProfitLoss", ["Other Comprehensive Income"], year)
        uoi += (oci_not + oci_rec + oci_uns)
    core_oi = oi - uoi

    out: Dict[str, Any] = {
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
        "UOI": uoi,
        "CoreOI": core_oi,
        "UFE": ufe,
        "CoreNFE": core_nfe,
        "tax_rate": tax_rate,
        "identity_gap": (cse + mi_bs) - (noa - nfo),
    }

    if prev_year:
        prev = recast_period(data, prev_year, None, cfg)
        avg_cse = _avg(cse, prev["CSE"])
        avg_noa = _avg(noa, prev["NOA"])
        avg_nfo = _avg(nfo, prev["NFO"])

        epsilon = cfg.noa_epsilon_ratio_of_ta * ta if ta else 0.0
        near_zero_noa = abs(avg_noa) < epsilon

        roce = _safe_div(cni, avg_cse)
        rnoa = None if near_zero_noa else _safe_div(oi, avg_noa)
        nbc = None if near_zero_noa else _safe_div(nfe, avg_nfo)
        spread = (rnoa - nbc) if (rnoa is not None and nbc is not None) else None
        flev = _safe_div(nfo, cse)
        pm = _safe_div(oi, sales)
        ato = None if near_zero_noa else _safe_div(sales, avg_noa)

        d_noa = noa - prev["NOA"]
        fcf_accounting = oi - d_noa

        out["ratios"] = {
            "ROCE": roce,
            "RNOA": rnoa,
            "NBC": nbc,
            "SPREAD": spread,
            "FLEV": flev,
            "PM": pm,
            "ATO": ato,
            "FCF_accounting": fcf_accounting,
            "suppressed_noa_ratio": near_zero_noa,
        }

    return out


def residual_earnings(cni_forecast: list[float], cse_opening: float, cost_of_equity: float, continuing: str = "CV1", g: float = 0.0) -> float:
    rho_e = 1.0 + cost_of_equity
    value = cse_opening
    cse_prev = cse_opening
    res = []
    for cni in cni_forecast:
        re = cni - (rho_e - 1.0) * cse_prev
        res.append(re)
        cse_prev = cse_prev + cni
    for i, re in enumerate(res, start=1):
        value += re / (rho_e ** i)
    if res:
        re_next = res[-1] * (1.0 + g)
        if continuing == "CV2":
            cv = re_next / (rho_e - 1.0)
            value += cv / (rho_e ** len(res))
        elif continuing == "CV3":
            cv = re_next / (rho_e - g)
            value += cv / (rho_e ** len(res))
    return value


def residual_operating_income(oi_forecast: list[float], noa_opening: float, wacc: float, continuing: str = "CV01", g: float = 0.0) -> float:
    rho_w = 1.0 + wacc
    value = noa_opening
    noa_prev = noa_opening
    reoi = []
    for oi in oi_forecast:
        ri = oi - (rho_w - 1.0) * noa_prev
        reoi.append(ri)
        noa_prev = noa_prev + oi
    for i, ri in enumerate(reoi, start=1):
        value += ri / (rho_w ** i)
    if reoi:
        ri_next = reoi[-1] * (1.0 + g)
        if continuing == "CV02":
            cv = ri_next / (rho_w - 1.0)
            value += cv / (rho_w ** len(reoi))
        elif continuing == "CV03":
            cv = ri_next / (rho_w - g)
            value += cv / (rho_w ** len(reoi))
    return value
