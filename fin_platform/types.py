"""
fin_platform/types.py
=====================
Python dataclasses mirroring the TypeScript type definitions.
All financial data structures used across the platform.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Literal, Tuple, Any

# ─── Core Data Types ──────────────────────────────────────────────────────────

# FinancialData: {metric_key: {year: value}}
FinancialData = Dict[str, Dict[str, float]]

# MappingDict: {source_metric: target_canonical}
MappingDict = Dict[str, str]

StatementType = Literal["ProfitLoss", "BalanceSheet", "CashFlow", "Financial"]
EarningsQualityTier = Literal["Low", "Medium", "High"]
ScenarioId = Literal["bear", "base", "bull"]
PNClassificationMode = Literal["auto", "operating", "investment"]
ForecastMethod = Literal["reoi_last", "reoi_mean3", "reoi_trend3"]


@dataclass
class MetricMapping:
    source: str
    target: str
    confidence: float
    statement: StatementType


@dataclass
class ValidationReport:
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    corrections: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CompanyCharacteristics:
    is_holding_company: bool
    is_investment_company: bool
    has_debt: bool
    investment_asset_ratio: float
    other_income_ratio: float
    inventory_ratio: float
    characteristics: List[str] = field(default_factory=list)


@dataclass
class TrendData:
    direction: str
    cagr: float
    volatility: float
    yoy_growth: Dict[str, float] = field(default_factory=dict)
    latest_value: float = 0.0
    min_value: float = 0.0
    max_value: float = 0.0


@dataclass
class AnomalyData:
    value: List[Dict] = field(default_factory=list)
    sign_change: List[Dict] = field(default_factory=list)


@dataclass
class DuPontResult:
    three_factor: Dict[str, Dict[str, float]] = field(default_factory=dict)
    five_factor: Dict[str, Dict[str, float]] = field(default_factory=dict)


@dataclass
class AnalysisSummary:
    total_metrics: int
    years_covered: int
    year_range: str
    completeness: float
    statement_breakdown: Dict[str, int] = field(default_factory=dict)


@dataclass
class AnalysisResult:
    summary: AnalysisSummary
    ratios: Dict[str, Dict[str, Dict[str, float]]] = field(default_factory=dict)
    trends: Dict[str, TrendData] = field(default_factory=dict)
    anomalies: Optional[AnomalyData] = None
    working_capital: Dict[str, Dict[str, float]] = field(default_factory=dict)
    dupont: Optional[DuPontResult] = None
    insights: List[str] = field(default_factory=list)
    quality_score: float = 0.0
    company_type: Optional[CompanyCharacteristics] = None


# ─── Penman-Nissim Types ──────────────────────────────────────────────────────

@dataclass
class ReconciliationRow:
    year: str
    expected: Optional[float]
    actual: Optional[float]
    gap: Optional[float]
    status: Literal["ok", "warn"]
    note: Optional[str] = None


@dataclass
class DataHygieneIssue:
    metric: str
    missing_years: List[str]
    severity: Literal["critical", "warning"]


@dataclass
class PNClassificationAuditRow:
    year: str
    mode: PNClassificationMode
    strict: bool
    treat_investments_as_operating: bool
    total_assets: Optional[float] = None
    operating_assets: Optional[float] = None
    financial_assets: Optional[float] = None
    cash: Optional[float] = None
    bank_balances: Optional[float] = None
    short_term_investments: Optional[float] = None
    long_term_investments: Optional[float] = None
    financial_liabilities: Optional[float] = None
    operating_liabilities: Optional[float] = None
    net_operating_assets: Optional[float] = None
    net_financial_assets: Optional[float] = None
    equity: Optional[float] = None
    noa_plus_nfa_minus_equity: Optional[float] = None
    pbt: Optional[float] = None
    tax: Optional[float] = None
    interest_expense: Optional[float] = None
    other_income: Optional[float] = None
    ebit: Optional[float] = None
    operating_income_bt: Optional[float] = None
    effective_tax_rate: Optional[float] = None
    tax_on_operating: Optional[float] = None
    tax_on_financial: Optional[float] = None
    nopat: Optional[float] = None
    net_financial_expense_at: Optional[float] = None
    notes: List[str] = field(default_factory=list)


@dataclass
class PNDiagnostics:
    treat_investments_as_operating: bool
    message: str
    strict_mode: Optional[bool] = None
    classification_mode: Optional[PNClassificationMode] = None
    fix_suggestions: List[str] = field(default_factory=list)
    income_statement_checks: List[ReconciliationRow] = field(default_factory=list)
    cash_flow_checks: List[ReconciliationRow] = field(default_factory=list)
    data_hygiene: List[DataHygieneIssue] = field(default_factory=list)
    assumptions: Dict[str, List[str]] = field(default_factory=dict)
    pn_reconciliation: List[Dict] = field(default_factory=list)
    balance_sheet_reconciliation: List[Dict] = field(default_factory=list)
    current_components_checks: List[Dict] = field(default_factory=list)
    classification_audit: List[PNClassificationAuditRow] = field(default_factory=list)
    ratio_warnings: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class NOPATDrivers:
    delta_nopat: float
    margin_effect: float
    turnover_effect: float
    capital_base_effect: float
    residual: float


@dataclass
class PenmanAcademicMetrics:
    reoi: Dict[str, float] = field(default_factory=dict)
    cumulative_reoi: Dict[str, float] = field(default_factory=dict)
    aeg: Dict[str, float] = field(default_factory=dict)
    exceptional_items: Optional[Dict[str, float]] = None
    core_nopat: Optional[Dict[str, float]] = None
    core_reoi: Optional[Dict[str, float]] = None
    operating_accruals: Dict[str, float] = field(default_factory=dict)
    accrual_ratio: Dict[str, float] = field(default_factory=dict)
    accrual_ratio_oa: Dict[str, float] = field(default_factory=dict)
    accrual_ratio_sales: Dict[str, float] = field(default_factory=dict)
    accrual_denominator_used: Dict[str, EarningsQualityTier] = field(default_factory=dict)
    earnings_quality: Dict[str, EarningsQualityTier] = field(default_factory=dict)
    nopat_drivers: Dict[str, NOPATDrivers] = field(default_factory=dict)


@dataclass
class ProFormaAssumptions:
    revenue_growth: float
    target_opm: float
    target_noat: float
    transition_speed: float


@dataclass
class ProFormaForecast:
    years: List[str]
    revenue: List[float]
    opm: List[float]
    noat: List[float]
    nopat: List[float]
    noa: List[float]
    reoi: List[float]
    core_mode: bool
    assumptions: ProFormaAssumptions


@dataclass
class ScenarioValuation:
    id: ScenarioId
    label: str
    cost_of_capital: float
    terminal_growth: float
    forecast_years: int
    pro_forma: ProFormaAssumptions
    forecast: Optional[ProFormaForecast] = None
    noa0: Optional[float] = None
    pv_explicit: Optional[float] = None
    pv_terminal: Optional[float] = None
    intrinsic_value: Optional[float] = None
    value_to_book: Optional[float] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class OperatingRiskMetrics:
    sigma_rnoa: Optional[float] = None
    sigma_rooa: Optional[float] = None
    sigma_opm: Optional[float] = None
    sigma_noat: Optional[float] = None
    fixed_cost_intensity: Optional[Dict[str, float]] = None
    notes: List[str] = field(default_factory=list)


@dataclass
class InvestmentThesis:
    title: str
    bullets: List[str] = field(default_factory=list)
    red_flags: List[str] = field(default_factory=list)
    watch_items: List[str] = field(default_factory=list)


@dataclass
class PenmanValuationResult:
    cost_of_capital: float
    terminal_growth: float
    forecast_years: int
    noa0: Optional[float] = None
    reoi0: Optional[float] = None
    pv_explicit: Optional[float] = None
    terminal_value: Optional[float] = None
    pv_terminal: Optional[float] = None
    intrinsic_value: Optional[float] = None
    value_to_book: Optional[float] = None
    forecast_reoi: Dict[str, float] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


@dataclass
class PenmanNissimResult:
    reformulated_bs: Dict[str, Dict[str, float]] = field(default_factory=dict)
    reformulated_is: Dict[str, Dict[str, float]] = field(default_factory=dict)
    ratios: Dict[str, Dict[str, float]] = field(default_factory=dict)
    fcf: Dict[str, Dict[str, float]] = field(default_factory=dict)
    value_drivers: Dict[str, Dict[str, float]] = field(default_factory=dict)
    academic: Optional[PenmanAcademicMetrics] = None
    valuation: Optional[PenmanValuationResult] = None
    scenarios: List[ScenarioValuation] = field(default_factory=list)
    operating_risk: Optional[OperatingRiskMetrics] = None
    thesis: Optional[InvestmentThesis] = None
    company_type: Optional[CompanyCharacteristics] = None
    diagnostics: Optional[PNDiagnostics] = None
    nissim_profitability: Optional["NissimProfitabilityResult"] = None


@dataclass
class AltmanZScore:
    score: float
    zone: Literal["Safe", "Grey", "Distress"]


@dataclass
class PiotroskiFScore:
    score: int
    signals: List[str]


@dataclass
class ScoringResult:
    altman_z: Dict[str, AltmanZScore] = field(default_factory=dict)
    piotroski_f: Dict[str, PiotroskiFScore] = field(default_factory=dict)


@dataclass
class NissimOperatingDecomposition:
    """
    Nissim (2023) novel 3-factor RNOA decomposition.
    RNOA = OPM × OAT / OFR

    Unlike the standard (OPM × NOAT), this uses Operating Assets (not Net OA)
    for turnover — making the decomposition valid even when NOA is negative/small.
    The Operations Funding Ratio (OFR) captures the operating credit effect.

    Reference: Nissim, D. (2023) "Profitability Analysis", Columbia Business School.
    Paper: https://papers.ssrn.com/abstract_id=4064824
    """
    # ── 3-Factor Drivers ───────────────────────────────────────────────────
    opm: Dict[str, float] = field(default_factory=dict)
    """Operating Profit Margin = NOPAT / Revenue.  
    Gauges portion of each revenue dollar flowing to capital providers."""

    oat: Dict[str, float] = field(default_factory=dict)
    """Operating Asset Turnover = Revenue / Avg Operating Assets.
    Sales are generated by ALL operating assets, so turnover is measured
    vs gross OA (not net OA). More robust than NOAT when NOA is small."""

    ofr: Dict[str, float] = field(default_factory=dict)
    """Operations Funding Ratio = NOA / OA  (expressed as fraction 0–1).
    Proportion of operating assets funded by capital (not operating credit).
    Low OFR = large operating credit from suppliers/customers → market power.
    Highly stable over time (persistence ≈ 0.95) — easier to forecast."""

    # ── Derived ────────────────────────────────────────────────────────────
    noat: Dict[str, float] = field(default_factory=dict)
    """Standard Net Operating Asset Turnover = Revenue / Avg NOA.
    Retained for comparison; unstable when NOA is small/negative."""

    rnoa_nissim: Dict[str, float] = field(default_factory=dict)
    """RNOA reconstructed from 3-factor: OPM × OAT / OFR.
    Should closely match RNOA from reformulated IS/BS."""

    rooa: Dict[str, float] = field(default_factory=dict)
    """Return On Operating Assets = NOPAT / Avg OA.
    Gross approach — avoids small-NOA instability.
    ROOA = RNOA × OFR (by construction)."""

    # ── Operating Credit Analysis ──────────────────────────────────────────
    operating_credit_pct: Dict[str, float] = field(default_factory=dict)
    """Operating liabilities / Operating assets = 1 - OFR.
    The share of OA funded by operating creditors."""

    rnoa_ofr_impact: Dict[str, float] = field(default_factory=dict)
    """Percentage point impact of operating credit on RNOA
    = RNOA × (1/OFR − 1).  Positive = OL amplifies RNOA."""

    # ── Persistence Metrics ─────────────────────────────────────────────────
    oat_stability_cv: Optional[float] = None
    """Coefficient of variation (std/mean) of OAT — lower = more stable."""

    ofr_stability_cv: Optional[float] = None
    """Coefficient of variation of OFR — typically very low (≈ 0.05–0.15)."""

    opm_stability_cv: Optional[float] = None
    """Coefficient of variation of OPM — highest of the three (≈ 0.5–1.5)."""

    stability_notes: List[str] = field(default_factory=list)


@dataclass
class NissimROCEHierarchy:
    """
    Full ROCE decomposition hierarchy per Nissim (2023), Exhibit D.

    Hierarchy:
        ROCE
         └─ NCI Leverage Effect  (ROCE − ROE)
         └─ ROE
             └─ Transitory ROE
             └─ Recurring ROE
                 └─ RNOA
                 └─ Financial Leverage Effect  (FLEV × Spread)
                 └─ Net Other Nonop Assets Effect
    """
    # ── Level 1 ────────────────────────────────────────────────────────────
    roce: Dict[str, float] = field(default_factory=dict)
    """ROCE = Net income to common equity / Avg common equity."""

    roe: Dict[str, float] = field(default_factory=dict)
    """ROE = Net income after preferred dividend / Avg total equity."""

    nci_leverage_effect: Dict[str, float] = field(default_factory=dict)
    """ROCE − ROE = NCI Leverage × NCI Spread."""

    nci_leverage: Dict[str, float] = field(default_factory=dict)
    """Avg NCI / Avg Common Equity."""

    nci_spread: Dict[str, float] = field(default_factory=dict)
    """ROE − Return on NCI."""

    return_on_nci: Dict[str, float] = field(default_factory=dict)
    """NCI income / Avg NCI equity."""

    # ── Level 2 ────────────────────────────────────────────────────────────
    recurring_roe: Dict[str, float] = field(default_factory=dict)
    """Recurring Income / Avg Equity  (transitory items excluded)."""

    transitory_roe: Dict[str, float] = field(default_factory=dict)
    """Transitory Income / Avg Equity.
    Mean ≈ 0, symmetric distribution.  Proxied via exceptional items."""

    transitory_income: Dict[str, float] = field(default_factory=dict)
    """Estimated transitory income (exceptional items, asset sale gains, etc.)."""

    # ── Level 3 ────────────────────────────────────────────────────────────
    rnoa: Dict[str, float] = field(default_factory=dict)
    """Return on Net Operating Assets = NOPAT / Avg NOA."""

    financial_leverage_effect: Dict[str, float] = field(default_factory=dict)
    """FLEV × Financial Spread = additional return from leverage."""

    financial_leverage: Dict[str, float] = field(default_factory=dict)
    """FLEV = Avg Net Debt / Avg Equity (or −Avg NFA / Avg Equity)."""

    net_borrowing_cost: Dict[str, float] = field(default_factory=dict)
    """NBC = NFE_AT / Avg Net Debt."""

    financial_spread: Dict[str, float] = field(default_factory=dict)
    """RNOA − NBC: excess return earned on borrowed funds."""

    net_other_nonop_effect: Dict[str, float] = field(default_factory=dict)
    """Relative size × Excess return on net other nonoperating assets."""

    net_other_nonop_relative_size: Dict[str, float] = field(default_factory=dict)
    """Avg Net Other Nonop Assets / Avg Total Equity."""

    excess_return_other_nonop: Dict[str, float] = field(default_factory=dict)
    """Return on Net Other Nonop Assets − RNOA."""

    return_on_other_nonop: Dict[str, float] = field(default_factory=dict)
    """Other nonop income / Avg Net Other Nonop Assets."""

    # ── Reconciliation ─────────────────────────────────────────────────────
    roce_reconciliation: List[Dict] = field(default_factory=list)
    """Year-by-year check: RNOA + FLE + OtherNonop = Recurring ROE."""

    interpretation: List[str] = field(default_factory=list)
    """Human-readable insights from the hierarchy."""


@dataclass
class NissimProfitabilityResult:
    """Container for all Nissim (2023) profitability analysis results."""
    operating: Optional[NissimOperatingDecomposition] = None
    roce_hierarchy: Optional[NissimROCEHierarchy] = None
    paper_reference: str = (
        "Nissim, D. (2023). Profitability Analysis. "
        "Columbia Business School. SSRN #4064824."
    )


@dataclass
class PNOptions:
    strict_mode: bool = True
    classification_mode: PNClassificationMode = "auto"
    cost_of_capital: float = 0.10
    terminal_growth: float = 0.03
    forecast_years: int = 5
    forecast_method: ForecastMethod = "reoi_mean3"


@dataclass
class MergeDebugInfo:
    integrity_checks: List[str] = field(default_factory=list)
    bs_reconciliation: List[Dict] = field(default_factory=list)
    bs_components: List[Dict] = field(default_factory=list)
    sheet_names: List[str] = field(default_factory=list)
    file_names: List[str] = field(default_factory=list)


@dataclass
class CompanySession:
    name: str
    data: FinancialData
    mappings: MappingDict
    analysis: Optional[AnalysisResult] = None
    pn_result: Optional[PenmanNissimResult] = None
    scoring: Optional[ScoringResult] = None
