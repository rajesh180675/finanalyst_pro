"""
fin_platform/metric_patterns.py
================================
Capitaline metric pattern definitions + fuzzy auto-mapper.
Ported from TypeScript metricPatterns.ts with Python enhancements.
"""
from __future__ import annotations
from typing import Dict, List, Optional, Tuple
import re

from .types import StatementType, MappingDict

# ─── Pattern Definitions ──────────────────────────────────────────────────────

class PatternDef:
    __slots__ = ("statement", "patterns", "exclude_patterns", "priority")

    def __init__(
        self,
        statement: StatementType,
        patterns: List[str],
        exclude_patterns: Optional[List[str]] = None,
        priority: int = 5,
    ):
        self.statement = statement
        self.patterns = patterns
        self.exclude_patterns = exclude_patterns or []
        self.priority = priority


METRIC_DEFS: Dict[str, PatternDef] = {
    # ── Balance Sheet – Assets ──────────────────────────────────────────────
    "Total Assets": PatternDef("BalanceSheet", ["total assets", "total of assets", "total equity and liabilities", "assets total"], priority=10),
    "Current Assets": PatternDef("BalanceSheet", ["current assets", "total current assets"], ["non-current", "non current"], priority=9),
    "Non-Current Assets": PatternDef("BalanceSheet", ["non-current assets", "non current assets", "total non-current assets", "total reported non-current assets", "total non current and other assets"], priority=9),
    "Cash and Cash Equivalents": PatternDef("BalanceSheet", ["cash and cash equivalents", "cash & cash equivalents", "cash and bank", "cash balance", "cash at bank"], ["bank balances other than"], priority=8),
    "Bank Balances": PatternDef("BalanceSheet", ["bank balances other than cash", "bank balances other than", "other bank balances"], priority=6),
    "Short-term Investments": PatternDef("BalanceSheet", ["current investments", "short term investments", "short-term investments"], ["non-current", "long term", "investments - long"], priority=7),
    "Long-term Investments": PatternDef("BalanceSheet", ["investments - long-term", "investments - long term", "non-current investments", "long term investments", "investments in subsidiaries", "investments in associates"], ["current investments", "short term"], priority=7),
    "Inventory": PatternDef("BalanceSheet", ["inventories", "inventory", "stock in trade", "stock-in-trade"], ["changes in inventories"], priority=7),
    "Trade Receivables": PatternDef("BalanceSheet", ["trade receivables", "sundry debtors", "accounts receivable", "debtors"], priority=7),
    "Other Current Assets": PatternDef("BalanceSheet", ["other current assets"], ["total", "non-current"], priority=5),
    "Property Plant Equipment": PatternDef("BalanceSheet", ["property, plant and equipment", "property plant and equipment", "ppe", "net block"], ["purchase of property"], priority=7),
    "Goodwill": PatternDef("BalanceSheet", ["goodwill"], ["goodwill impairment"], priority=6),
    "Intangible Assets": PatternDef("BalanceSheet", ["intangible assets"], ["under development"], priority=6),
    "Right of Use Assets": PatternDef("BalanceSheet", ["right of use assets", "right-of-use assets", "rou assets"], priority=5),
    "Capital Work in Progress": PatternDef("BalanceSheet", ["capital work in progress", "cwip", "capital work-in-progress"], priority=5),
    "Fixed Assets": PatternDef("BalanceSheet", ["fixed assets", "total fixed assets"], ["purchase of fixed", "sale of fixed", "held for sale"], priority=6),
    "Investment Property": PatternDef("BalanceSheet", ["investment properties", "investment property"], priority=5),
    "Deferred Tax Assets": PatternDef("BalanceSheet", ["deferred tax assets", "deferred tax asset", "deferred tax assets (net)"], ["liabilities"], priority=5),
    "Other Non-Current Assets": PatternDef("BalanceSheet", ["other non-current assets"], ["total"], priority=4),

    # ── Balance Sheet – Liabilities ─────────────────────────────────────────
    "Total Liabilities": PatternDef("BalanceSheet", ["total liabilities", "total non-current liabilities and current liabilities"], priority=10),
    "Current Liabilities": PatternDef("BalanceSheet", ["current liabilities", "total current liabilities"], ["non-current", "non current"], priority=9),
    "Non-Current Liabilities": PatternDef("BalanceSheet", ["non-current liabilities", "non current liabilities", "total non-current liabilities", "total reported non-current liabilities"], priority=9),
    "Accounts Payable": PatternDef("BalanceSheet", ["trade payables", "sundry creditors", "accounts payable", "creditors"], priority=7),
    "Short-term Debt": PatternDef("BalanceSheet", ["short term borrowings", "current borrowings", "short-term borrowings"], ["long term", "non-current"], priority=8),
    "Long-term Debt": PatternDef("BalanceSheet", ["long term borrowings", "non-current borrowings", "long-term borrowings", "term loans", "secured loans", "debentures"], ["short term", "current"], priority=8),
    "Lease Liabilities": PatternDef("BalanceSheet", ["lease liabilities", "lease liability", "finance lease obligations"], priority=5),
    "Other Current Liabilities": PatternDef("BalanceSheet", ["other current liabilities"], ["total", "non-current"], priority=5),
    "Other Non-Current Liabilities": PatternDef("BalanceSheet", ["other non-current liabilities"], ["total"], priority=5),
    "Provisions": PatternDef("BalanceSheet", ["provisions", "long-term provisions", "short-term provisions"], ["provision for tax"], priority=5),
    "Deferred Tax Liabilities": PatternDef("BalanceSheet", ["deferred tax liabilities", "deferred tax liability", "deferred tax liabilities (net)"], ["assets"], priority=5),

    # ── Balance Sheet – Equity ──────────────────────────────────────────────
    "Total Equity": PatternDef("BalanceSheet", ["total equity", "total stockholders' equity", "total stockholders equity", "shareholders funds", "shareholders' funds", "total shareholders funds", "net worth"], ["total equity and liabilities"], priority=10),
    "Share Capital": PatternDef("BalanceSheet", ["share capital", "equity share capital", "paid-up capital", "paid up capital"], ["number of"], priority=8),
    "Retained Earnings": PatternDef("BalanceSheet", ["reserves and surplus", "retained earnings", "other equity", "reserves & surplus"], priority=7),
    "Minority Interest": PatternDef("BalanceSheet", ["minority interest", "non-controlling interest", "non controlling interests"], priority=5),
    "Contingent Liabilities": PatternDef("BalanceSheet", ["contingent liabilities", "contingent liabilities and commitments"], priority=4),

    # ── Profit & Loss – Income ──────────────────────────────────────────────
    "Revenue": PatternDef("ProfitLoss", ["revenue from operations", "revenue from operations(net)", "revenue from operations (net)", "net sales", "sales turnover", "total revenue from operations"], ["total revenue"], priority=10),
    "Total Revenue": PatternDef("ProfitLoss", ["total revenue", "total income"], priority=9),
    "Other Income": PatternDef("ProfitLoss", ["other income", "other operating income", "non-operating income"], ["total income", "operating income"], priority=6),
    "Exceptional Items": PatternDef("ProfitLoss", ["exceptional items", "extraordinary items", "exceptional and extraordinary items"], priority=6),

    # ── Profit & Loss – Expenses ────────────────────────────────────────────
    "Cost of Goods Sold": PatternDef("ProfitLoss", ["cost of goods sold", "cost of materials consumed", "raw material consumed", "purchases of stock-in-trade", "purchases of stock in trade", "cost of revenue"], priority=8),
    "Employee Expenses": PatternDef("ProfitLoss", ["employee benefit expense", "employee expenses", "staff costs", "personnel expenses", "wages and salaries"], priority=7),
    "Depreciation": PatternDef("ProfitLoss", ["depreciation", "amortization", "depreciation and amortisation", "depreciation and amortization", "d&a"], ["accumulated"], priority=7),
    "Interest Expense": PatternDef("ProfitLoss", ["finance costs", "interest expense", "interest charges", "borrowing costs", "financial expenses"], priority=8),
    "Total Expenses": PatternDef("ProfitLoss", ["total expenses", "total expenditure", "total costs and expenses"], priority=9),
    "Other Expenses": PatternDef("ProfitLoss", ["other expenses", "other operating expenses", "miscellaneous expenses"], ["total", "non-operating"], priority=5),
    "Changes in Inventory": PatternDef("ProfitLoss", ["changes in inventories", "change in inventories", "(increase)/decrease in inventories"], priority=5),
    "Manufacturing Expenses": PatternDef("ProfitLoss", ["manufacturing expenses", "factory overhead", "production overhead"], priority=4),
    "Selling Expenses": PatternDef("ProfitLoss", ["selling expenses", "selling and distribution", "marketing expenses"], priority=4),

    # ── Profit & Loss – Profit ──────────────────────────────────────────────
    "Gross Profit": PatternDef("ProfitLoss", ["gross profit", "gross margin"], priority=7),
    "Operating Income": PatternDef("ProfitLoss", ["operating profit", "operating income", "profit from operations", "ebit"], ["before", "interest", "tax", "d&a"], priority=8),
    "Income Before Tax": PatternDef("ProfitLoss", ["profit before tax", "income before tax", "earnings before tax", "pbt", "profit before taxation"], priority=9),
    "Tax Expense": PatternDef("ProfitLoss", ["tax expense", "income tax expense", "provision for tax", "income tax", "current tax", "deferred tax"], ["deferred tax assets", "deferred tax liabilities", "deferred tax (credit)"], priority=8),
    "Net Income": PatternDef("ProfitLoss", ["profit after tax", "net income", "profit for the year", "profit for the period", "net profit", "pat", "profit attributable to shareholders", "profit attributable to equity holders"], ["before tax", "minority"], priority=10),
    "Minority Earnings": PatternDef("ProfitLoss", ["profit attributable to minority", "profit attributable to non-controlling", "minority interest in profit"], priority=4),
    "EPS Basic": PatternDef("ProfitLoss", ["basic eps", "earnings per share (basic)", "basic earnings per share"], priority=5),
    "EPS Diluted": PatternDef("ProfitLoss", ["diluted eps", "earnings per share (diluted)", "diluted earnings per share"], priority=5),
    "Dividend": PatternDef("ProfitLoss", ["dividend paid", "dividend per share", "dividends"], ["dividend income", "dividend received"], priority=5),

    # ── Cash Flow Statement ──────────────────────────────────────────────────
    "Operating Cash Flow": PatternDef("CashFlow", ["net cash from operating activities", "cash flow from operating activities", "cash generated from operations", "cash inflow from operating activities", "net cash generated from operations"], priority=10),
    "Capital Expenditure": PatternDef("CashFlow", ["purchase of property plant and equipment", "capital expenditure", "capex", "purchase of fixed assets", "acquisition of property plant and equipment", "purchase of tangible assets", "payment for property plant and equipment"], priority=9),
    "Investing Cash Flow": PatternDef("CashFlow", ["net cash from investing activities", "cash flow from investing activities", "net cash used in investing activities"], priority=8),
    "Financing Cash Flow": PatternDef("CashFlow", ["net cash from financing activities", "cash flow from financing activities", "net cash used in financing activities"], priority=8),
    "Free Cash Flow": PatternDef("CashFlow", ["free cash flow", "fcf"], priority=6),
    "Net Change in Cash": PatternDef("CashFlow", ["net increase in cash", "net decrease in cash", "net inc/(dec) in cash", "net change in cash and cash equivalents", "net increase/(decrease) in cash and cash equivalents"], priority=7),
    "Cash Beginning": PatternDef("CashFlow", ["cash at beginning", "cash and cash equivalents at beginning", "opening cash", "cash at the beginning of the year", "cash and cash equivalents at beginning of the year"], priority=6),
    "Cash Ending": PatternDef("CashFlow", ["cash at end", "cash and cash equivalents at end", "closing cash", "cash at the end of the year", "cash and cash equivalents at end of the year", "cash and cash equivalents at end of the period"], priority=6),
    "Dividends Paid": PatternDef("CashFlow", ["dividends paid", "dividend paid to shareholders", "dividend paid (equity)"], priority=5),
    "Debt Repayment": PatternDef("CashFlow", ["repayment of borrowings", "repayment of long term borrowings", "repayment of term loans"], priority=5),
    "Proceeds from Borrowing": PatternDef("CashFlow", ["proceeds from borrowings", "proceeds from long term borrowings", "loans raised"], priority=5),
    "Share Buyback": PatternDef("CashFlow", ["buyback of shares", "repurchase of shares", "treasury stock purchase"], priority=5),

    # ── Financial / Derived ──────────────────────────────────────────────────
    "Market Capitalisation": PatternDef("Financial", ["market capitalisation", "market cap", "market capitalization"], priority=6),
    "Book Value Per Share": PatternDef("Financial", ["book value per share", "bvps", "net asset value per share"], priority=5),
    "Face Value": PatternDef("Financial", ["face value", "par value", "nominal value"], priority=4),
    "Number of Shares": PatternDef("Financial", ["number of shares", "shares outstanding", "equity shares outstanding", "no. of shares"], priority=5),
}

# ─── Fuzzy Match Helpers ──────────────────────────────────────────────────────

STOP_WORDS = frozenset({
    "total", "reported", "unit", "curr", "current", "non",
    "non-current", "noncurrent", "other", "and", "for", "of", "the",
})


def _tokenize(s: str) -> frozenset:
    tokens = re.split(r'\s+', s)
    return frozenset(
        re.sub(r'[^a-z0-9]', '', w)
        for w in tokens
        if len(w) > 2 and w not in STOP_WORDS
    )


def _fuzzy_match(a: str, b: str) -> float:
    """Jaccard similarity with word-count bonus and length penalty."""
    a_words = _tokenize(a)
    b_words = _tokenize(b)
    if not a_words or not b_words:
        return 0.0
    intersection = a_words & b_words
    union = a_words | b_words
    jaccard = len(intersection) / len(union) if union else 0.0
    word_bonus = 0.1 if len(intersection) >= 2 else 0.0
    len_penalty = min(1.0, max(0.6, len(b_words) / len(a_words)))
    return min((jaccard + word_bonus) * len_penalty, 1.0)


# ─── Core Matching ────────────────────────────────────────────────────────────

class MatchResult:
    __slots__ = ("target", "confidence", "statement")

    def __init__(self, target: str, confidence: float, statement: StatementType):
        self.target = target
        self.confidence = confidence
        self.statement = statement


def match_metric(source: str, source_stmt: Optional[str] = None) -> List[MatchResult]:
    """
    Return all candidate target matches for a source metric name.
    Applies statement gating, exclude-pattern filtering, and multi-level scoring.
    """
    clean = source.split("::")[-1].strip().lower()
    results: List[MatchResult] = []

    for target, defn in METRIC_DEFS.items():
        # Statement gating
        if source_stmt and source_stmt not in ("Financial",) and defn.statement != source_stmt:
            continue

        # Exclude patterns
        if any(ep.lower() in clean for ep in defn.exclude_patterns):
            continue

        best_score = 0.0
        for pattern in defn.patterns:
            pat = pattern.lower()
            if clean == pat:
                score = 0.98
            elif pat in clean:
                score = 0.85 + (len(pat) / max(len(clean), 1)) * 0.10
            elif clean in pat and len(clean) >= 4:
                score = 0.75 + (len(clean) / max(len(pat), 1)) * 0.10
            else:
                sim = _fuzzy_match(clean, pat)
                score = sim * 0.80 if sim > 0.6 else 0.0
            best_score = max(best_score, score)

        if best_score > 0.55:
            results.append(MatchResult(target, min(best_score, 0.98), defn.statement))

    # Sort by confidence desc, then priority desc
    results.sort(key=lambda r: (r.confidence, METRIC_DEFS[r.target].priority), reverse=True)
    return results


def auto_map_metrics(source_metrics: List[str]) -> Tuple[MappingDict, List[str]]:
    """
    Greedy confidence-based auto-mapper.
    Returns (mappings dict, list of unmapped sources).
    """
    mappings: MappingDict = {}
    unmapped: List[str] = []
    used_targets: set = set()
    used_sources: set = set()

    # Detect statement prefix from key (e.g. "ProfitLoss::Revenue from Operations")
    def _stmt(s: str) -> Optional[str]:
        if "::" in s:
            return s.split("::")[0]
        return None

    # Score all pairs
    scored: List[Tuple[str, str, float, int]] = []
    for source in source_metrics:
        stmt = _stmt(source)
        for m in match_metric(source, stmt):
            scored.append((source, m.target, m.confidence, METRIC_DEFS[m.target].priority))

    # Sort by confidence desc, then priority desc
    scored.sort(key=lambda x: (x[2], x[3]), reverse=True)

    for source, target, conf, _ in scored:
        if source in used_sources or target in used_targets:
            continue
        if conf >= 0.60:
            mappings[source] = target
            used_sources.add(source)
            used_targets.add(target)

    unmapped = [s for s in source_metrics if s not in used_sources]
    return mappings, unmapped


def get_all_targets() -> List[str]:
    return list(METRIC_DEFS.keys())


def get_targets_by_statement() -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {}
    for target, defn in METRIC_DEFS.items():
        result.setdefault(defn.statement, []).append(target)
    return result


def get_statement_for_target(target: str) -> Optional[StatementType]:
    return METRIC_DEFS[target].statement if target in METRIC_DEFS else None


CRITICAL_TARGETS = [
    "Revenue", "Net Income", "Total Assets", "Total Equity",
    "Current Assets", "Current Liabilities", "Operating Cash Flow",
    "Interest Expense", "Income Before Tax", "Share Capital", "Retained Earnings",
]


def get_pattern_coverage(mappings: MappingDict) -> Dict:
    all_targets = list(METRIC_DEFS.keys())
    mapped_targets = set(mappings.values())
    unmapped = [t for t in all_targets if t not in mapped_targets]
    critical_missing = [t for t in CRITICAL_TARGETS if t not in mapped_targets]

    by_stmt: Dict[str, Dict] = {}
    for target, defn in METRIC_DEFS.items():
        s = defn.statement
        if s not in by_stmt:
            by_stmt[s] = {"total": 0, "mapped": 0}
        by_stmt[s]["total"] += 1
        if target in mapped_targets:
            by_stmt[s]["mapped"] += 1

    return {
        "total_targets": len(all_targets),
        "mapped_targets": len(mapped_targets),
        "unmapped_targets": unmapped,
        "coverage": (len(mapped_targets) / len(all_targets) * 100) if all_targets else 0,
        "critical_missing": critical_missing,
        "by_statement": by_stmt,
    }


def get_detailed_matches(source_metrics: List[str]) -> List[Dict]:
    """Return full match details per source metric for the Patterns tab."""
    results = []
    for source in source_metrics:
        stmt = source.split("::")[0] if "::" in source else None
        all_matches_raw = match_metric(source, stmt)
        best = all_matches_raw[0] if all_matches_raw else None
        results.append({
            "source": source,
            "target": best.target if best else None,
            "confidence": best.confidence if best else 0.0,
            "statement": best.statement if best else None,
            "all_matches": [
                {"target": m.target, "confidence": m.confidence, "statement": m.statement}
                for m in all_matches_raw[:5]
            ],
        })
    return results


def get_patterns_for_target(target: str) -> List[str]:
    return METRIC_DEFS[target].patterns if target in METRIC_DEFS else []
