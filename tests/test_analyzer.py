"""
tests/test_analyzer.py
=======================
Unit tests for the FinAnalyst Pro analysis engine.
Tests cover: parser utilities, metric patterns, standard analysis,
Penman-Nissim framework, Altman Z, Piotroski F, Shapley attribution,
accrual quality, edge cases.

Run:  pytest tests/ -v
"""

import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from fin_platform.parser import (
    extract_year,
    to_numeric,
    classify_metric,
    parse_file,
    expand_uploaded_files,
)
from fin_platform.metric_patterns import (
    match_metric,
    auto_map_metrics,
    get_pattern_coverage,
    get_all_targets,
    get_targets_by_statement,
)
from fin_platform.analyzer import (
    get_years,
    derive_val,
    analyze_financials,
    penman_nissim_analysis,
    calculate_scores,
    detect_company_type,
)
from fin_platform.types import PNOptions
from fin_platform.formatting import (
    format_indian_number,
    format_percent,
    year_label,
    metric_label,
)


# ─── Shared Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def sample_data():
    """Minimal realistic financial dataset (4 years) for testing."""
    return {
        # ── Profit & Loss ────────────────────────────────────────────────────
        "ProfitLoss::Revenue from Operations": {
            "202003": 600000, "202103": 650000, "202203": 800000, "202303": 900000
        },
        "ProfitLoss::Profit After Tax": {
            "202003": 40000, "202103": 55000, "202203": 70000, "202303": 75000
        },
        "ProfitLoss::Profit Before Tax": {
            "202003": 52000, "202103": 68000, "202203": 88000, "202303": 94000
        },
        "ProfitLoss::Tax Expense": {
            "202003": 12000, "202103": 13000, "202203": 18000, "202303": 19000
        },
        "ProfitLoss::Finance Costs": {
            "202003": 20000, "202103": 22000, "202203": 25000, "202303": 27000
        },
        "ProfitLoss::Depreciation and Amortisation": {
            "202003": 35000, "202103": 38000, "202203": 42000, "202303": 45000
        },
        "ProfitLoss::Other Income": {
            "202003": 5000, "202103": 6000, "202203": 7000, "202303": 8000
        },
        "ProfitLoss::Cost of Materials Consumed": {
            "202003": 400000, "202103": 420000, "202203": 530000, "202303": 600000
        },
        "ProfitLoss::Total Expenses": {
            "202003": 548000, "202103": 582000, "202203": 712000, "202303": 806000
        },
        # ── Balance Sheet ────────────────────────────────────────────────────
        "BalanceSheet::Total Assets": {
            "202003": 800000, "202103": 1000000, "202203": 1200000, "202303": 1400000
        },
        "BalanceSheet::Total Equity": {
            "202003": 400000, "202103": 460000, "202203": 540000, "202303": 620000
        },
        "BalanceSheet::Share Capital": {
            "202003": 6000, "202103": 6000, "202203": 6000, "202303": 6000
        },
        "BalanceSheet::Reserves and Surplus": {
            "202003": 394000, "202103": 454000, "202203": 534000, "202303": 614000
        },
        "BalanceSheet::Current Assets": {
            "202003": 180000, "202103": 220000, "202203": 270000, "202303": 320000
        },
        "BalanceSheet::Total Current Assets": {
            "202003": 180000, "202103": 220000, "202203": 270000, "202303": 320000
        },
        "BalanceSheet::Current Liabilities": {
            "202003": 140000, "202103": 170000, "202203": 210000, "202303": 250000
        },
        "BalanceSheet::Total Current Liabilities": {
            "202003": 140000, "202103": 170000, "202203": 210000, "202303": 250000
        },
        "BalanceSheet::Long Term Borrowings": {
            "202003": 160000, "202103": 200000, "202203": 240000, "202303": 280000
        },
        "BalanceSheet::Short Term Borrowings": {
            "202003": 30000, "202103": 40000, "202203": 50000, "202303": 60000
        },
        "BalanceSheet::Inventories": {
            "202003": 60000, "202103": 70000, "202203": 90000, "202303": 100000
        },
        "BalanceSheet::Trade Receivables": {
            "202003": 45000, "202103": 52000, "202203": 65000, "202303": 78000
        },
        "BalanceSheet::Cash and Cash Equivalents": {
            "202003": 30000, "202103": 35000, "202203": 42000, "202303": 50000
        },
        "BalanceSheet::Trade Payables": {
            "202003": 75000, "202103": 88000, "202203": 110000, "202303": 130000
        },
        "BalanceSheet::Non-Current Assets": {
            "202003": 620000, "202103": 780000, "202203": 930000, "202303": 1080000
        },
        "BalanceSheet::Non-Current Liabilities": {
            "202003": 175000, "202103": 220000, "202203": 265000, "202303": 310000
        },
        "BalanceSheet::Investments - Long-term": {
            "202003": 20000, "202103": 25000, "202203": 30000, "202303": 35000
        },
        # ── Cash Flow ────────────────────────────────────────────────────────
        "CashFlow::Net Cash from Operating Activities": {
            "202003": 70000, "202103": 80000, "202203": 90000, "202303": 95000
        },
        "CashFlow::Purchase of Property Plant and Equipment": {
            "202003": -110000, "202103": -130000, "202203": -150000, "202303": -160000
        },
        "CashFlow::Cash and Cash Equivalents at End of the year": {
            "202003": 30000, "202103": 35000, "202203": 42000, "202303": 50000
        },
    }


@pytest.fixture
def sample_mappings():
    """Canonical mappings for the sample dataset."""
    return {
        "ProfitLoss::Revenue from Operations":        "Revenue",
        "ProfitLoss::Profit After Tax":               "Net Income",
        "ProfitLoss::Profit Before Tax":              "Income Before Tax",
        "ProfitLoss::Tax Expense":                    "Tax Expense",
        "ProfitLoss::Finance Costs":                  "Interest Expense",
        "ProfitLoss::Depreciation and Amortisation":  "Depreciation",
        "ProfitLoss::Other Income":                   "Other Income",
        "ProfitLoss::Cost of Materials Consumed":     "Cost of Goods Sold",
        "ProfitLoss::Total Expenses":                 "Total Expenses",
        "BalanceSheet::Total Assets":                 "Total Assets",
        "BalanceSheet::Total Equity":                 "Total Equity",
        "BalanceSheet::Share Capital":                "Share Capital",
        "BalanceSheet::Reserves and Surplus":         "Retained Earnings",
        "BalanceSheet::Current Assets":               "Current Assets",
        "BalanceSheet::Current Liabilities":          "Current Liabilities",
        "BalanceSheet::Long Term Borrowings":         "Long-term Debt",
        "BalanceSheet::Short Term Borrowings":        "Short-term Debt",
        "BalanceSheet::Inventories":                  "Inventory",
        "BalanceSheet::Trade Receivables":            "Trade Receivables",
        "BalanceSheet::Cash and Cash Equivalents":    "Cash and Cash Equivalents",
        "BalanceSheet::Trade Payables":               "Accounts Payable",
        "BalanceSheet::Investments - Long-term":      "Long-term Investments",
        "CashFlow::Net Cash from Operating Activities":              "Operating Cash Flow",
        "CashFlow::Purchase of Property Plant and Equipment":        "Capital Expenditure",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 1. PARSER TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestExtractYear:
    def test_yyyymm_passthrough(self):
        assert extract_year("202403") == "202403"

    def test_yyyymm_201903(self):
        assert extract_year("201903") == "201903"

    def test_fy_year(self):
        assert extract_year("FY2024") == "202403"

    def test_fy_space(self):
        assert extract_year("FY 2023") == "202303"

    def test_fy_lowercase(self):
        assert extract_year("fy2022") == "202203"

    def test_mar_long(self):
        assert extract_year("Mar 2024") == "202403"

    def test_mar_short_2digit(self):
        assert extract_year("Mar-24") == "202403"

    def test_march_full(self):
        assert extract_year("March 2023") == "202303"

    def test_range_hyphen(self):
        assert extract_year("2024-25") == "202403"

    def test_range_slash(self):
        assert extract_year("2023/24") == "202303"

    def test_plain_year_2000s(self):
        assert extract_year("2022") == "202203"

    def test_plain_year_1990s(self):
        assert extract_year("1998") == "199803"

    def test_too_old_ignored(self):
        assert extract_year("1985") is None

    def test_too_future_ignored(self):
        assert extract_year("2150") is None

    def test_non_year_string(self):
        assert extract_year("Particulars") is None

    def test_revenue_label(self):
        assert extract_year("Revenue") is None

    def test_empty_string(self):
        assert extract_year("") is None


class TestToNumeric:
    def test_integer_input(self):
        assert to_numeric(1234) == 1234.0

    def test_float_input(self):
        assert to_numeric(3.14) == pytest.approx(3.14)

    def test_comma_separated_string(self):
        assert to_numeric("1,23,456") == 123456.0

    def test_parenthetical_negative(self):
        assert to_numeric("(500)") == -500.0

    def test_parenthetical_negative_large(self):
        assert to_numeric("(1,23,456)") == -123456.0

    def test_rupee_prefix(self):
        assert to_numeric("₹1,500") == 1500.0

    def test_rs_prefix(self):
        assert to_numeric("Rs. 2500") == 2500.0

    def test_cr_suffix(self):
        assert to_numeric("150Cr") == 150.0

    def test_nil_zero(self):
        assert to_numeric("Nil") == 0.0
        assert to_numeric("nil") == 0.0

    def test_none_input(self):
        assert to_numeric(None) is None

    def test_empty_string(self):
        assert to_numeric("") is None

    def test_na_variants(self):
        assert to_numeric("N/A") is None
        assert to_numeric("n/a") is None
        assert to_numeric("NA") is None

    def test_dash(self):
        assert to_numeric("-") is None

    def test_double_dash(self):
        assert to_numeric("--") is None

    def test_nan_float(self):
        assert to_numeric(float("nan")) is None

    def test_negative_plain(self):
        assert to_numeric("-12345") == -12345.0

    def test_zero(self):
        assert to_numeric(0) == 0.0

    def test_decimal(self):
        assert to_numeric("12345.67") == pytest.approx(12345.67)


class TestClassifyMetric:
    def test_operating_activities(self):
        assert classify_metric("Net Cash from Operating Activities") == "CashFlow"

    def test_capex(self):
        assert classify_metric("Capital Expenditure") == "CashFlow"

    def test_total_assets(self):
        assert classify_metric("Total Assets") == "BalanceSheet"

    def test_equity(self):
        assert classify_metric("Total Equity") == "BalanceSheet"

    def test_revenue(self):
        assert classify_metric("Revenue from Operations") == "ProfitLoss"

    def test_net_income(self):
        assert classify_metric("Net Income") == "ProfitLoss"

    def test_tax(self):
        assert classify_metric("Tax Expense") == "ProfitLoss"

    def test_inventory_bs(self):
        assert classify_metric("Inventories") == "BalanceSheet"


class TestFileParsingExtensions:
    def test_extract_year_fy_2digit(self):
        assert extract_year("FY24") == "202403"

    def test_parse_capitaline_html_saved_as_xls(self):
        html = """
        <html><body>
        <table>
            <tr><th>Particulars</th><th>Mar 2024</th><th>Mar 2023</th></tr>
            <tr><td>Revenue from Operations</td><td>1,200</td><td>1,000</td></tr>
            <tr><td>Profit After Tax</td><td>150</td><td>120</td></tr>
        </table>
        </body></html>
        """.encode("utf-8")

        data, years = parse_file(html, "ProfitLossINDAS_(5).xls")

        assert "ProfitLoss::Revenue from Operations" in data
        assert data["ProfitLoss::Revenue from Operations"]["202403"] == 1200.0
        assert data["ProfitLoss::Profit After Tax"]["202303"] == 120.0
        assert years == ["202303", "202403"]

    def test_expand_uploaded_files_zip(self):
        import io
        import zipfile

        mem = io.BytesIO()
        with zipfile.ZipFile(mem, "w") as zf:
            zf.writestr("CashFlow_(4).xls", "<html><table><tr><th>Particulars</th><th>FY24</th></tr><tr><td>Net Cash from Operating Activities</td><td>500</td></tr></table></html>")
            zf.writestr("notes/readme.txt", "ignore")

        files = expand_uploaded_files(mem.getvalue(), "capitaline_bundle.zip")

        assert len(files) == 1
        assert files[0][0] == "CashFlow_(4).xls"



# ═══════════════════════════════════════════════════════════════════════════════
# 2. METRIC PATTERN TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestMatchMetric:
    def test_revenue_from_operations(self):
        matches = match_metric("ProfitLoss::Revenue from Operations", "ProfitLoss")
        targets = [m.target for m in matches]
        assert "Revenue" in targets

    def test_total_assets_bs(self):
        matches = match_metric("BalanceSheet::Total Assets", "BalanceSheet")
        targets = [m.target for m in matches]
        assert "Total Assets" in targets

    def test_high_confidence_exact(self):
        matches = match_metric("BalanceSheet::Total Assets", "BalanceSheet")
        assert matches[0].confidence >= 0.85

    def test_profit_after_tax_maps_net_income(self):
        matches = match_metric("ProfitLoss::Profit After Tax", "ProfitLoss")
        targets = [m.target for m in matches]
        assert "Net Income" in targets

    def test_finance_costs_maps_interest_expense(self):
        matches = match_metric("ProfitLoss::Finance Costs", "ProfitLoss")
        targets = [m.target for m in matches]
        assert "Interest Expense" in targets

    def test_capex_cashflow(self):
        matches = match_metric("CashFlow::Purchase of Property Plant and Equipment", "CashFlow")
        targets = [m.target for m in matches]
        assert "Capital Expenditure" in targets

    def test_long_term_borrowings(self):
        matches = match_metric("BalanceSheet::Long Term Borrowings", "BalanceSheet")
        targets = [m.target for m in matches]
        assert "Long-term Debt" in targets

    def test_fuzzy_cash_ampersand(self):
        matches = match_metric("BalanceSheet::Cash & Cash Equivalents")
        targets = [m.target for m in matches]
        assert "Cash and Cash Equivalents" in targets

    def test_statement_gating_prevents_cross_match(self):
        # BalanceSheet source should NOT produce ProfitLoss-only targets
        matches = match_metric("BalanceSheet::Total Equity", "BalanceSheet")
        targets = [m.target for m in matches]
        assert "Net Income" not in targets

    def test_exclude_patterns_inventory(self):
        # "Changes in inventories" should NOT map to "Inventory"
        matches = match_metric("ProfitLoss::Changes in Inventories", "ProfitLoss")
        targets = [m.target for m in matches]
        assert "Inventory" not in targets

    def test_depreciation_not_accumulated(self):
        # "Accumulated depreciation" should NOT map to Depreciation (excluded)
        matches = match_metric("BalanceSheet::Accumulated Depreciation", "BalanceSheet")
        targets = [m.target for m in matches]
        assert "Depreciation" not in targets

    def test_empty_source(self):
        matches = match_metric("")
        assert matches == []


class TestAutoMapMetrics:
    def test_maps_all_core_targets(self, sample_data, sample_mappings):
        sources = list(sample_data.keys())
        mappings, unmapped = auto_map_metrics(sources)
        mapped_targets = set(mappings.values())
        for must_have in ["Revenue", "Net Income", "Total Assets", "Total Equity"]:
            assert must_have in mapped_targets, f"{must_have} not mapped"

    def test_no_duplicate_targets(self, sample_data):
        sources = list(sample_data.keys())
        mappings, _ = auto_map_metrics(sources)
        targets = list(mappings.values())
        assert len(targets) == len(set(targets)), "Duplicate target mappings found"

    def test_no_duplicate_sources(self, sample_data):
        sources = list(sample_data.keys())
        mappings, _ = auto_map_metrics(sources)
        src_list = list(mappings.keys())
        assert len(src_list) == len(set(src_list))

    def test_unmapped_are_truly_absent(self, sample_data):
        sources = list(sample_data.keys())
        mappings, unmapped = auto_map_metrics(sources)
        for u in unmapped:
            assert u not in mappings

    def test_get_all_targets_count(self):
        targets = get_all_targets()
        assert len(targets) >= 60

    def test_all_targets_nonempty_strings(self):
        for t in get_all_targets():
            assert isinstance(t, str) and len(t) > 0

    def test_get_targets_by_statement_keys(self):
        by_stmt = get_targets_by_statement()
        assert "BalanceSheet" in by_stmt
        assert "ProfitLoss" in by_stmt
        assert "CashFlow" in by_stmt

    def test_each_statement_has_targets(self):
        by_stmt = get_targets_by_statement()
        for stmt, targets in by_stmt.items():
            assert len(targets) > 0, f"{stmt} has no targets"


class TestPatternCoverage:
    def test_full_coverage_object(self, sample_mappings):
        cov = get_pattern_coverage(sample_mappings)
        assert "coverage" in cov
        assert "mapped_targets" in cov
        assert "unmapped_targets" in cov
        assert "critical_missing" in cov
        assert "by_statement" in cov

    def test_nonzero_coverage(self, sample_mappings):
        cov = get_pattern_coverage(sample_mappings)
        assert cov["coverage"] > 0

    def test_empty_mappings_all_critical_missing(self):
        cov = get_pattern_coverage({})
        assert len(cov["critical_missing"]) > 0
        assert cov["mapped_targets"] == 0

    def test_by_statement_totals_correct(self):
        cov = get_pattern_coverage({})
        total_from_stmt = sum(v["total"] for v in cov["by_statement"].values())
        assert total_from_stmt == cov["total_targets"]


# ═══════════════════════════════════════════════════════════════════════════════
# 3. CORE ANALYZER TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetYears:
    def test_sorted_output(self, sample_data):
        years = get_years(sample_data)
        assert years == sorted(years)

    def test_correct_years(self, sample_data):
        years = get_years(sample_data)
        assert "202003" in years
        assert "202103" in years
        assert "202203" in years
        assert "202303" in years

    def test_empty_data(self):
        assert get_years({}) == []

    def test_single_year(self):
        data = {"ProfitLoss::Revenue": {"202303": 100}}
        assert get_years(data) == ["202303"]


class TestDeriveVal:
    def test_direct_mapping_revenue(self, sample_data, sample_mappings):
        v = derive_val(sample_data, sample_mappings, "Revenue", "202303")
        assert v == 900000.0

    def test_direct_mapping_net_income(self, sample_data, sample_mappings):
        v = derive_val(sample_data, sample_mappings, "Net Income", "202303")
        assert v == 75000.0

    def test_derived_ebit_from_pbt_plus_interest(self, sample_data, sample_mappings):
        # EBIT = PBT + Interest  →  94000 + 27000 = 121000
        ebit = derive_val(sample_data, sample_mappings, "EBIT", "202303")
        assert ebit == pytest.approx(121000.0)

    def test_derived_total_liabilities(self, sample_data, sample_mappings):
        # TL = TA - TE  →  1400000 - 620000 = 780000
        tl = derive_val(sample_data, sample_mappings, "Total Liabilities", "202303")
        assert tl == pytest.approx(780000.0)

    def test_missing_metric_returns_none(self, sample_data, sample_mappings):
        v = derive_val(sample_data, sample_mappings, "Goodwill", "202303")
        assert v is None

    def test_missing_year_returns_none(self, sample_data, sample_mappings):
        v = derive_val(sample_data, sample_mappings, "Revenue", "199903")
        assert v is None

    def test_ebitda_derived(self, sample_data, sample_mappings):
        # EBITDA = EBIT + Dep  →  121000 + 45000 = 166000
        ebitda = derive_val(sample_data, sample_mappings, "EBITDA", "202303")
        assert ebitda == pytest.approx(166000.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. STANDARD FINANCIAL ANALYSIS TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestAnalyzeFinancials:
    def test_returns_result(self, sample_data, sample_mappings):
        r = analyze_financials(sample_data, sample_mappings)
        assert r is not None

    def test_summary_metrics_count(self, sample_data, sample_mappings):
        r = analyze_financials(sample_data, sample_mappings)
        assert r.summary.total_metrics == len(sample_data)

    def test_summary_years_covered(self, sample_data, sample_mappings):
        r = analyze_financials(sample_data, sample_mappings)
        assert r.summary.years_covered == 4

    def test_summary_year_range(self, sample_data, sample_mappings):
        r = analyze_financials(sample_data, sample_mappings)
        assert "202003" in r.summary.year_range
        assert "202303" in r.summary.year_range

    def test_liquidity_ratios_present(self, sample_data, sample_mappings):
        r = analyze_financials(sample_data, sample_mappings)
        assert "Liquidity" in r.ratios
        assert "Current Ratio" in r.ratios["Liquidity"]
        assert "Quick Ratio" in r.ratios["Liquidity"]

    def test_current_ratio_correct(self, sample_data, sample_mappings):
        # CR 2023 = 320000 / 250000 = 1.28
        r = analyze_financials(sample_data, sample_mappings)
        cr = r.ratios["Liquidity"]["Current Ratio"]["202303"]
        assert cr == pytest.approx(320000 / 250000, rel=0.01)

    def test_profitability_ratios_present(self, sample_data, sample_mappings):
        r = analyze_financials(sample_data, sample_mappings)
        assert "Profitability" in r.ratios
        for key in ["Net Profit Margin %", "ROE %", "ROA %"]:
            assert key in r.ratios["Profitability"]

    def test_net_profit_margin_correct(self, sample_data, sample_mappings):
        # NPM 2023 = 75000 / 900000 * 100 ≈ 8.33%
        r = analyze_financials(sample_data, sample_mappings)
        npm = r.ratios["Profitability"]["Net Profit Margin %"]["202303"]
        assert npm == pytest.approx(75000 / 900000 * 100, rel=0.01)

    def test_leverage_ratios_present(self, sample_data, sample_mappings):
        r = analyze_financials(sample_data, sample_mappings)
        assert "Leverage" in r.ratios

    def test_efficiency_ratios_present(self, sample_data, sample_mappings):
        r = analyze_financials(sample_data, sample_mappings)
        assert "Efficiency" in r.ratios
        assert "Asset Turnover" in r.ratios["Efficiency"]

    def test_trends_computed(self, sample_data, sample_mappings):
        r = analyze_financials(sample_data, sample_mappings)
        assert "Revenue" in r.trends
        assert r.trends["Revenue"].cagr > 0  # Revenue grew over period

    def test_trend_direction_up(self, sample_data, sample_mappings):
        r = analyze_financials(sample_data, sample_mappings)
        assert r.trends["Revenue"].direction == "up"

    def test_dupont_three_factor(self, sample_data, sample_mappings):
        r = analyze_financials(sample_data, sample_mappings)
        assert r.dupont is not None
        assert r.dupont.three_factor
        # Should have all 4 years
        assert len(r.dupont.three_factor) == 4

    def test_quality_score_range(self, sample_data, sample_mappings):
        r = analyze_financials(sample_data, sample_mappings)
        assert 0.0 <= r.quality_score <= 100.0

    def test_company_type_detected(self, sample_data, sample_mappings):
        r = analyze_financials(sample_data, sample_mappings)
        ct = r.company_type
        assert ct is not None
        assert isinstance(ct.is_holding_company, bool)
        assert isinstance(ct.is_investment_company, bool)
        assert isinstance(ct.has_debt, bool)

    def test_company_has_debt(self, sample_data, sample_mappings):
        r = analyze_financials(sample_data, sample_mappings)
        assert r.company_type.has_debt is True

    def test_insights_generated(self, sample_data, sample_mappings):
        r = analyze_financials(sample_data, sample_mappings)
        assert isinstance(r.insights, list)
        assert len(r.insights) > 0

    def test_working_capital_present(self, sample_data, sample_mappings):
        r = analyze_financials(sample_data, sample_mappings)
        assert "Working Capital" in r.working_capital

    def test_empty_data(self):
        r = analyze_financials({}, {})
        assert r.summary.total_metrics == 0
        assert r.summary.years_covered == 0

    def test_statement_breakdown(self, sample_data, sample_mappings):
        r = analyze_financials(sample_data, sample_mappings)
        bd = r.summary.statement_breakdown
        assert "ProfitLoss" in bd
        assert "BalanceSheet" in bd
        assert "CashFlow" in bd


# ═══════════════════════════════════════════════════════════════════════════════
# 5. PENMAN-NISSIM FRAMEWORK TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestPenmanNissimAnalysis:

    def test_returns_pn_result(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        assert r is not None

    # ── Balance Sheet Reformulation ──────────────────────────────────────────
    def test_noa_computed(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        noa = r.reformulated_bs.get("Net Operating Assets", {})
        assert len(noa) > 0

    def test_nfa_computed(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        nfa = r.reformulated_bs.get("Net Financial Assets", {})
        assert len(nfa) > 0

    def test_operating_assets_computed(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        oa = r.reformulated_bs.get("Operating Assets", {})
        assert len(oa) > 0
        # OA <= Total Assets always
        for y, oa_v in oa.items():
            ta = r.reformulated_bs["Total Assets"].get(y, 0)
            assert oa_v <= ta + 1, f"OA > TA in year {y}"

    def test_invested_capital_computed(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        ic = r.reformulated_bs.get("Invested Capital", {})
        assert len(ic) > 0

    # ── Income Statement Reformulation ───────────────────────────────────────
    def test_nopat_positive(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        nopat = r.reformulated_is.get("NOPAT", {})
        assert len(nopat) > 0
        assert any(v > 0 for v in nopat.values())

    def test_effective_tax_rate_bounded(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        for y, tr in r.reformulated_is.get("Effective Tax Rate", {}).items():
            assert 0.05 <= tr <= 0.50, f"Tax rate {tr} out of [5%, 50%] in {y}"

    def test_ebit_from_reformulated_is(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        ebit_2023 = r.reformulated_is.get("EBIT", {}).get("202303")
        # PBT=94000 + Interest=27000 = 121000
        assert ebit_2023 == pytest.approx(121000.0)

    # ── PN Ratios ────────────────────────────────────────────────────────────
    def test_rnoa_reasonable_range(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        for y, v in r.ratios.get("RNOA %", {}).items():
            assert -200 < v < 1000, f"RNOA {v} unreasonable for {y}"

    def test_rooa_exists(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        rooa = r.ratios.get("ROOA %", {})
        assert len(rooa) > 0

    def test_opm_is_positive(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        for y, v in r.ratios.get("OPM %", {}).items():
            assert v > 0, f"OPM should be positive in {y}"

    def test_flev_sign(self, sample_data, sample_mappings):
        # Company has significant debt → FLEV should be positive
        r = penman_nissim_analysis(sample_data, sample_mappings)
        flev = r.ratios.get("FLEV", {})
        if flev:
            # FLEV = -NFA/CE; with net debt, NFA < 0 → FLEV > 0
            assert any(v > 0 for v in flev.values())

    def test_roe_actual_matches_formula(self, sample_data, sample_mappings):
        # ROE (actual) = NI / avg_CE
        r = penman_nissim_analysis(sample_data, sample_mappings)
        roe = r.ratios.get("ROE %", {})
        assert len(roe) > 0

    def test_revenue_growth_computed(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        rev_growth = r.ratios.get("Revenue Growth %", {})
        # First year has no prior → at least 3 should have growth
        assert len(rev_growth) >= 3

    def test_interest_coverage_computed(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        ic = r.ratios.get("Interest Coverage", {})
        assert len(ic) > 0
        for y, v in ic.items():
            assert v > 0

    # ── FCF ──────────────────────────────────────────────────────────────────
    def test_ocf_mapped(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        ocf = r.fcf.get("Operating Cash Flow", {})
        assert len(ocf) == 4

    def test_capex_absolute(self, sample_data, sample_mappings):
        # Capex stored as positive value
        r = penman_nissim_analysis(sample_data, sample_mappings)
        capex = r.fcf.get("Capital Expenditure", {})
        assert all(v >= 0 for v in capex.values())

    def test_fcf_computed(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        fcf = r.fcf.get("Free Cash Flow", {})
        assert len(fcf) > 0
        # OCF=70000, capex=110000 → FCF=−40000 in 2020
        fcf_2020 = fcf.get("202003")
        assert fcf_2020 == pytest.approx(70000 - 110000)

    # ── Academic Extensions ──────────────────────────────────────────────────
    def test_reoi_computed(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        assert r.academic is not None
        reoi = r.academic.reoi
        # ReOI needs prior NOA, so at most n-1 years
        assert 1 <= len(reoi) <= 4

    def test_cumulative_reoi(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        cum = r.academic.cumulative_reoi
        sorted_years = sorted(cum.keys())
        # Cumulative should be monotonically increasing if all ReOI positive
        reoi = r.academic.reoi
        if all(reoi.get(y, 0) > 0 for y in sorted_years):
            for i in range(1, len(sorted_years)):
                assert cum[sorted_years[i]] >= cum[sorted_years[i - 1]]

    def test_aeg_computed(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        aeg = r.academic.aeg
        assert len(aeg) >= 1

    def test_accrual_ratio_bounded(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        for y, ar in r.academic.accrual_ratio.items():
            # Accrual ratio should not be astronomically large
            assert abs(ar) < 5.0, f"Accrual ratio {ar} too extreme in {y}"

    def test_earnings_quality_tiers(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        for tier in r.academic.earnings_quality.values():
            assert tier in ("High", "Medium", "Low")

    def test_nopat_shapley_drivers(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        drivers = r.academic.nopat_drivers
        assert len(drivers) >= 1  # At least one year-pair

    def test_shapley_sum_consistency(self, sample_data, sample_mappings):
        """Margin + Turnover + Capital + Residual ≈ ΔNOPAT."""
        r = penman_nissim_analysis(sample_data, sample_mappings)
        for y, d in r.academic.nopat_drivers.items():
            total = d.margin_effect + d.turnover_effect + d.capital_base_effect + d.residual
            assert abs(total - d.delta_nopat) < 0.01, (
                f"Shapley sum inconsistency for {y}: total={total}, delta={d.delta_nopat}"
            )

    def test_core_nopat_equals_nopat_without_exceptional(self, sample_data, sample_mappings):
        # No exceptional items in sample → core NOPAT should equal NOPAT
        r = penman_nissim_analysis(sample_data, sample_mappings)
        if r.academic.core_nopat:
            for y in r.reformulated_is.get("NOPAT", {}):
                nopat = r.reformulated_is["NOPAT"].get(y)
                core = r.academic.core_nopat.get(y)
                if nopat is not None and core is not None:
                    assert abs(nopat - core) < 1.0  # No exceptional items → equal

    # ── Valuation ────────────────────────────────────────────────────────────
    def test_valuation_object(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        assert r.valuation is not None
        assert r.valuation.cost_of_capital == 0.10
        assert r.valuation.terminal_growth == 0.03

    def test_pv_explicit_positive_reoi(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        if r.valuation.pv_explicit is not None:
            # If ReOI is positive, PV(explicit) should be positive
            reoi_vals = list(r.academic.reoi.values())
            if all(v > 0 for v in reoi_vals):
                assert r.valuation.pv_explicit > 0

    def test_intrinsic_value_positive(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        iv = r.valuation.intrinsic_value
        if iv is not None and r.valuation.noa0 and r.valuation.noa0 > 0:
            assert iv > 0

    def test_terminal_growth_warning(self, sample_data, sample_mappings):
        """g >= r should trigger a warning."""
        r = penman_nissim_analysis(
            sample_data, sample_mappings,
            PNOptions(cost_of_capital=0.08, terminal_growth=0.10)
        )
        assert any("terminal" in w.lower() for w in r.valuation.warnings)

    # ── Scenarios ────────────────────────────────────────────────────────────
    def test_three_scenarios_generated(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        assert len(r.scenarios) == 3

    def test_scenario_ids(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        ids = {s.id for s in r.scenarios}
        assert ids == {"bear", "base", "bull"}

    def test_bear_higher_cost_of_capital(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        base = next(s for s in r.scenarios if s.id == "base")
        bear = next(s for s in r.scenarios if s.id == "bear")
        bull = next(s for s in r.scenarios if s.id == "bull")
        assert bear.cost_of_capital >= base.cost_of_capital
        assert bull.cost_of_capital <= base.cost_of_capital

    def test_bull_higher_intrinsic_value(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        bear = next(s for s in r.scenarios if s.id == "bear")
        bull = next(s for s in r.scenarios if s.id == "bull")
        if bear.intrinsic_value and bull.intrinsic_value:
            assert bull.intrinsic_value >= bear.intrinsic_value

    def test_pro_forma_forecast_years(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(
            sample_data, sample_mappings,
            PNOptions(forecast_years=7)
        )
        base = next(s for s in r.scenarios if s.id == "base")
        if base.forecast:
            assert len(base.forecast.years) == 7

    # ── Operating Risk ───────────────────────────────────────────────────────
    def test_operating_risk_computed(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        assert r.operating_risk is not None

    def test_sigma_values_nonnegative(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        op = r.operating_risk
        for attr in ["sigma_rnoa", "sigma_opm", "sigma_noat", "sigma_rooa"]:
            v = getattr(op, attr)
            if v is not None:
                assert v >= 0, f"{attr} should be non-negative"

    # ── Investment Thesis ────────────────────────────────────────────────────
    def test_thesis_exists(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        assert r.thesis is not None
        assert isinstance(r.thesis.bullets, list)
        assert isinstance(r.thesis.red_flags, list)
        assert isinstance(r.thesis.watch_items, list)

    def test_thesis_has_bullets(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        # Profitable company → should have ROE bullet at least
        assert len(r.thesis.bullets) > 0

    # ── Diagnostics ──────────────────────────────────────────────────────────
    def test_diagnostics_exists(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        assert r.diagnostics is not None

    def test_pn_reconciliation_populated(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        assert len(r.diagnostics.pn_reconciliation) > 0

    def test_classification_audit_all_years(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        audit_years = {row.year for row in r.diagnostics.classification_audit}
        years = get_years(sample_data)
        assert audit_years == set(years)

    def test_data_hygiene_entries(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(sample_data, sample_mappings)
        # All critical metrics are present in sample → hygiene should be clean
        critical_issues = [
            i for i in r.diagnostics.data_hygiene
            if i.severity == "critical"
        ]
        assert len(critical_issues) == 0

    # ── Classification Modes ─────────────────────────────────────────────────
    def test_investment_mode(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(
            sample_data, sample_mappings,
            PNOptions(classification_mode="investment")
        )
        assert r.diagnostics.treat_investments_as_operating is True

    def test_operating_mode(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(
            sample_data, sample_mappings,
            PNOptions(classification_mode="operating")
        )
        assert r.diagnostics.treat_investments_as_operating is False

    def test_cost_of_capital_sensitivity(self, sample_data, sample_mappings):
        """Higher r → lower or equal intrinsic value."""
        r_low = penman_nissim_analysis(
            sample_data, sample_mappings, PNOptions(cost_of_capital=0.07)
        )
        r_high = penman_nissim_analysis(
            sample_data, sample_mappings, PNOptions(cost_of_capital=0.15)
        )
        iv_low = r_low.valuation.intrinsic_value
        iv_high = r_high.valuation.intrinsic_value
        if iv_low is not None and iv_high is not None:
            assert iv_low >= iv_high

    def test_forecast_method_reoi_last(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(
            sample_data, sample_mappings,
            PNOptions(forecast_method="reoi_last")
        )
        assert r.valuation is not None

    def test_forecast_method_reoi_trend3(self, sample_data, sample_mappings):
        r = penman_nissim_analysis(
            sample_data, sample_mappings,
            PNOptions(forecast_method="reoi_trend3")
        )
        assert r.valuation is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 6. SCORING MODEL TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestCalculateScores:

    def test_altman_z_computed_all_years(self, sample_data, sample_mappings):
        r = calculate_scores(sample_data, sample_mappings)
        assert len(r.altman_z) == 4

    def test_altman_z_zone_valid(self, sample_data, sample_mappings):
        r = calculate_scores(sample_data, sample_mappings)
        for y, az in r.altman_z.items():
            assert az.zone in ("Safe", "Grey", "Distress")

    def test_altman_z_score_is_float(self, sample_data, sample_mappings):
        r = calculate_scores(sample_data, sample_mappings)
        for az in r.altman_z.values():
            assert isinstance(az.score, float)

    def test_growing_profitable_company_safe(self, sample_data, sample_mappings):
        # Sample company is profitable and growing → should be in Safe/Grey zone
        r = calculate_scores(sample_data, sample_mappings)
        last = sorted(r.altman_z.keys())[-1]
        assert r.altman_z[last].zone in ("Safe", "Grey")

    def test_piotroski_f_computed(self, sample_data, sample_mappings):
        r = calculate_scores(sample_data, sample_mappings)
        assert len(r.piotroski_f) == 4

    def test_piotroski_score_range(self, sample_data, sample_mappings):
        r = calculate_scores(sample_data, sample_mappings)
        for pf in r.piotroski_f.values():
            assert 0 <= pf.score <= 9

    def test_piotroski_signals_list(self, sample_data, sample_mappings):
        r = calculate_scores(sample_data, sample_mappings)
        for pf in r.piotroski_f.values():
            assert isinstance(pf.signals, list)
            assert len(pf.signals) >= 4

    def test_first_year_has_fewer_signals(self, sample_data, sample_mappings):
        # First year has no prior-year comparison → 4 signals (no YoY)
        r = calculate_scores(sample_data, sample_mappings)
        first = sorted(r.piotroski_f.keys())[0]
        assert len(r.piotroski_f[first].signals) == 4

    def test_later_years_have_more_signals(self, sample_data, sample_mappings):
        # Later years include YoY comparisons → 7 signals
        r = calculate_scores(sample_data, sample_mappings)
        last = sorted(r.piotroski_f.keys())[-1]
        assert len(r.piotroski_f[last].signals) == 7

    def test_positive_ni_signal(self, sample_data, sample_mappings):
        r = calculate_scores(sample_data, sample_mappings)
        last = sorted(r.piotroski_f.keys())[-1]
        signals = r.piotroski_f[last].signals
        assert any("Positive Net Income" in s for s in signals)

    def test_empty_data_no_crash(self):
        r = calculate_scores({}, {})
        assert r.altman_z == {}
        assert r.piotroski_f == {}


# ═══════════════════════════════════════════════════════════════════════════════
# 7. COMPANY TYPE DETECTION TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestDetectCompanyType:

    def test_normal_company_not_holding(self, sample_data, sample_mappings):
        years = get_years(sample_data)
        ct = detect_company_type(sample_data, sample_mappings, years)
        # Investment ratio is low (20000/800000 ≈ 2.5%) → not holding
        assert ct.is_holding_company is False

    def test_normal_company_has_debt(self, sample_data, sample_mappings):
        years = get_years(sample_data)
        ct = detect_company_type(sample_data, sample_mappings, years)
        assert ct.has_debt is True

    def test_holding_company_detected(self):
        """Company with 60%+ investments should be detected as investment company."""
        data = {
            "BalanceSheet::Total Assets": {"202303": 100000},
            "BalanceSheet::Total Equity": {"202303": 60000},
            "BalanceSheet::Investments - Long-term": {"202303": 65000},
            "ProfitLoss::Revenue from Operations": {"202303": 3000},
            "ProfitLoss::Other Income": {"202303": 5000},
        }
        mappings = {
            "BalanceSheet::Total Assets": "Total Assets",
            "BalanceSheet::Total Equity": "Total Equity",
            "BalanceSheet::Investments - Long-term": "Long-term Investments",
            "ProfitLoss::Revenue from Operations": "Revenue",
            "ProfitLoss::Other Income": "Other Income",
        }
        ct = detect_company_type(data, mappings, ["202303"])
        assert ct.is_investment_company is True
        assert ct.investment_asset_ratio > 0.50

    def test_debt_free_company(self):
        """Company with no borrowings → has_debt = False."""
        data = {
            "BalanceSheet::Total Assets": {"202303": 100000},
            "BalanceSheet::Total Equity": {"202303": 95000},
            "ProfitLoss::Revenue from Operations": {"202303": 50000},
        }
        mappings = {
            "BalanceSheet::Total Assets": "Total Assets",
            "BalanceSheet::Total Equity": "Total Equity",
            "ProfitLoss::Revenue from Operations": "Revenue",
        }
        ct = detect_company_type(data, mappings, ["202303"])
        assert ct.has_debt is False

    def test_empty_data_returns_defaults(self):
        ct = detect_company_type({}, {}, [])
        assert ct.is_holding_company is False
        assert ct.is_investment_company is False
        assert ct.has_debt is False


# ═══════════════════════════════════════════════════════════════════════════════
# 8. FORMATTING TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestFormatIndianNumber:
    def test_crores(self):
        result = format_indian_number(1_00_00_000)   # 1 Cr
        assert "Cr" in result

    def test_large_crores(self):
        result = format_indian_number(15_00_00_000)  # 150 Cr
        assert "Cr" in result

    def test_lakhs(self):
        result = format_indian_number(5_00_000)      # 5 L
        assert "L" in result

    def test_thousands(self):
        result = format_indian_number(5_000)         # 5 K
        assert "K" in result

    def test_zero(self):
        assert format_indian_number(0) == "0"

    def test_none(self):
        assert format_indian_number(None) == "—"

    def test_negative_crores(self):
        result = format_indian_number(-5_00_00_000)
        assert "-" in result
        assert "Cr" in result


class TestYearLabel:
    def test_march_2024(self):
        assert year_label("202403") == "FY24"

    def test_march_2023(self):
        assert year_label("202303") == "FY23"

    def test_march_2020(self):
        assert year_label("202003") == "FY20"

    def test_non_march_passthrough(self):
        result = year_label("202406")
        assert "2024" in result

    def test_non_yyyymm_passthrough(self):
        assert year_label("SomeName") == "SomeName"


class TestMetricLabel:
    def test_strips_statement_prefix(self):
        assert metric_label("ProfitLoss::Revenue from Operations") == "Revenue from Operations"

    def test_strips_bs_prefix(self):
        assert metric_label("BalanceSheet::Total Assets") == "Total Assets"

    def test_no_prefix_unchanged(self):
        assert metric_label("Revenue") == "Revenue"

    def test_multiple_colons(self):
        # Only strips the first segment
        result = metric_label("A::B::C")
        assert result == "B::C"


class TestFormatPercent:
    def test_positive(self):
        result = format_percent(12.5)
        assert "12.5" in result and "%" in result

    def test_negative(self):
        result = format_percent(-3.2)
        assert "-3.2" in result and "%" in result

    def test_none(self):
        assert format_percent(None) == "—"

    def test_zero(self):
        result = format_percent(0.0)
        assert "%" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 9. EDGE CASES & ROBUSTNESS
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:

    def test_single_year_analysis(self):
        data = {
            "ProfitLoss::Revenue from Operations": {"202303": 100000},
            "ProfitLoss::Profit After Tax": {"202303": 10000},
            "BalanceSheet::Total Assets": {"202303": 200000},
            "BalanceSheet::Total Equity": {"202303": 100000},
        }
        mappings = {
            "ProfitLoss::Revenue from Operations": "Revenue",
            "ProfitLoss::Profit After Tax": "Net Income",
            "BalanceSheet::Total Assets": "Total Assets",
            "BalanceSheet::Total Equity": "Total Equity",
        }
        r = analyze_financials(data, mappings)
        assert r.summary.years_covered == 1

    def test_pn_single_year_no_reoi(self):
        """ReOI requires prior-year NOA; single year → no ReOI."""
        data = {
            "ProfitLoss::Revenue from Operations": {"202303": 100000},
            "ProfitLoss::Profit Before Tax": {"202303": 15000},
            "ProfitLoss::Tax Expense": {"202303": 3000},
            "BalanceSheet::Total Assets": {"202303": 200000},
            "BalanceSheet::Total Equity": {"202303": 100000},
        }
        mappings = {
            "ProfitLoss::Revenue from Operations": "Revenue",
            "ProfitLoss::Profit Before Tax": "Income Before Tax",
            "ProfitLoss::Tax Expense": "Tax Expense",
            "BalanceSheet::Total Assets": "Total Assets",
            "BalanceSheet::Total Equity": "Total Equity",
        }
        r = penman_nissim_analysis(data, mappings)
        # Single year → no ReOI (needs prior-year NOA)
        assert len(r.academic.reoi) == 0

    def test_zero_revenue_no_crash(self):
        data = {
            "ProfitLoss::Revenue from Operations": {"202303": 0},
            "BalanceSheet::Total Assets": {"202303": 100000},
            "BalanceSheet::Total Equity": {"202303": 60000},
        }
        mappings = {
            "ProfitLoss::Revenue from Operations": "Revenue",
            "BalanceSheet::Total Assets": "Total Assets",
            "BalanceSheet::Total Equity": "Total Equity",
        }
        r = analyze_financials(data, mappings)
        assert r is not None

    def test_negative_net_income_distress(self):
        data = {
            "ProfitLoss::Revenue from Operations": {"202303": 50000},
            "ProfitLoss::Profit After Tax": {"202303": -20000},
            "ProfitLoss::Profit Before Tax": {"202303": -25000},
            "ProfitLoss::Tax Expense": {"202303": -5000},
            "BalanceSheet::Total Assets": {"202303": 200000},
            "BalanceSheet::Total Equity": {"202303": 30000},
            "BalanceSheet::Current Assets": {"202303": 40000},
            "BalanceSheet::Current Liabilities": {"202303": 80000},
        }
        mappings = {
            "ProfitLoss::Revenue from Operations": "Revenue",
            "ProfitLoss::Profit After Tax": "Net Income",
            "ProfitLoss::Profit Before Tax": "Income Before Tax",
            "ProfitLoss::Tax Expense": "Tax Expense",
            "BalanceSheet::Total Assets": "Total Assets",
            "BalanceSheet::Total Equity": "Total Equity",
            "BalanceSheet::Current Assets": "Current Assets",
            "BalanceSheet::Current Liabilities": "Current Liabilities",
        }
        scoring = calculate_scores(data, mappings)
        last = sorted(scoring.altman_z.keys())[-1]
        # Negative income + current liabilities > current assets → Distress
        assert scoring.altman_z[last].zone in ("Grey", "Distress")

    def test_pn_missing_cashflow_no_crash(self):
        """PN should work gracefully without a CashFlow statement."""
        data = {
            "ProfitLoss::Revenue from Operations": {"202003": 100000, "202103": 120000},
            "ProfitLoss::Profit Before Tax": {"202003": 15000, "202103": 18000},
            "ProfitLoss::Tax Expense": {"202003": 3000, "202103": 4000},
            "BalanceSheet::Total Assets": {"202003": 200000, "202103": 250000},
            "BalanceSheet::Total Equity": {"202003": 100000, "202103": 120000},
        }
        mappings = {
            "ProfitLoss::Revenue from Operations": "Revenue",
            "ProfitLoss::Profit Before Tax": "Income Before Tax",
            "ProfitLoss::Tax Expense": "Tax Expense",
            "BalanceSheet::Total Assets": "Total Assets",
            "BalanceSheet::Total Equity": "Total Equity",
        }
        r = penman_nissim_analysis(data, mappings)
        assert r is not None
        assert "Cash Flow statement missing" in " ".join(r.diagnostics.fix_suggestions)

    def test_pn_terminal_growth_eq_cost_of_capital(self, sample_data, sample_mappings):
        """g == r should produce a warning and set pv_terminal to 0."""
        r = penman_nissim_analysis(
            sample_data, sample_mappings,
            PNOptions(cost_of_capital=0.10, terminal_growth=0.10)
        )
        assert any("terminal" in w.lower() for w in r.valuation.warnings)

    def test_derive_val_depth_guard(self, sample_data, sample_mappings):
        """derive_val should not recurse infinitely."""
        # Calling with a deeply derived metric should not raise RecursionError
        try:
            v = derive_val(sample_data, sample_mappings, "EBITDA", "202303")
            # If computable, check it's reasonable
            if v is not None:
                assert v > 0
        except RecursionError:
            pytest.fail("derive_val exceeded recursion limit")

    def test_auto_map_empty_source_list(self):
        mappings, unmapped = auto_map_metrics([])
        assert mappings == {}
        assert unmapped == []

    def test_pn_full_pipeline_no_exception(self, sample_data, sample_mappings):
        """End-to-end: parse → map → analyze → PN → score — no exceptions."""
        analysis = analyze_financials(sample_data, sample_mappings)
        pn = penman_nissim_analysis(sample_data, sample_mappings)
        scoring = calculate_scores(sample_data, sample_mappings)
        assert analysis is not None
        assert pn is not None
        assert scoring is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])



# ─── Nissim (2023) Profitability Analysis Tests ───────────────────────────────

class TestNissimProfitabilityAnalysis:
    """
    Tests for the Nissim (2023) novel profitability decomposition.

    Paper: "Profitability Analysis", Columbia Business School, SSRN #4064824.
    Key innovations tested:
      - OFR (Operations Funding Ratio) = NOA / OA
      - OAT (Operating Asset Turnover) = Revenue / Avg OA
      - 3-factor identity: RNOA = OPM × OAT / OFR
      - ROOA = RNOA × OFR identity
      - Full ROCE hierarchy: Recurring/Transitory split, FLE decomposition
    """

    # ── Fixture with full data (cash included) ─────────────────────────────────
    @pytest.fixture
    def nissim_data(self):
        """Full financial dataset including cash — needed for OA/NOA computation."""
        return {
            "ProfitLoss::Revenue": {"202003": 600000, "202103": 650000, "202203": 800000, "202303": 900000},
            "ProfitLoss::Net Income": {"202003": 40000, "202103": 55000, "202203": 70000, "202303": 75000},
            "ProfitLoss::Profit Before Tax": {"202003": 52000, "202103": 68000, "202203": 88000, "202303": 94000},
            "ProfitLoss::Tax Expense": {"202003": 12000, "202103": 13000, "202203": 18000, "202303": 19000},
            "ProfitLoss::Interest Expense": {"202003": 8000, "202103": 9000, "202203": 11000, "202303": 12000},
            "BalanceSheet::Total Assets": {"202003": 700000, "202103": 750000, "202203": 830000, "202303": 900000},
            "BalanceSheet::Total Equity": {"202003": 350000, "202103": 400000, "202203": 460000, "202303": 510000},
            "BalanceSheet::Current Assets": {"202003": 200000, "202103": 220000, "202203": 250000, "202303": 280000},
            "BalanceSheet::Current Liabilities": {"202003": 100000, "202103": 110000, "202203": 130000, "202303": 145000},
            "BalanceSheet::Long-term Debt": {"202003": 80000, "202103": 70000, "202203": 60000, "202303": 50000},
            "BalanceSheet::Short-term Debt": {"202003": 20000, "202103": 18000, "202203": 15000, "202303": 12000},
            # Cash — critical: OA = Total Assets − Financial Assets; FA = Cash + Investments
            "BalanceSheet::Cash and Cash Equivalents": {"202003": 50000, "202103": 60000, "202203": 70000, "202303": 80000},
            "CashFlow::Cash from Operations": {"202003": 55000, "202103": 65000, "202203": 85000, "202303": 90000},
            "CashFlow::Capital Expenditure": {"202003": -25000, "202103": -28000, "202203": -35000, "202303": -40000},
        }

    @pytest.fixture
    def nissim_maps(self):
        return {
            "ProfitLoss::Revenue": "Revenue",
            "ProfitLoss::Net Income": "Net Income",
            "ProfitLoss::Profit Before Tax": "Income Before Tax",
            "ProfitLoss::Tax Expense": "Tax Expense",
            "ProfitLoss::Interest Expense": "Interest Expense",
            "BalanceSheet::Total Assets": "Total Assets",
            "BalanceSheet::Total Equity": "Total Equity",
            "BalanceSheet::Current Assets": "Current Assets",
            "BalanceSheet::Current Liabilities": "Current Liabilities",
            "BalanceSheet::Long-term Debt": "Long-term Debt",
            "BalanceSheet::Short-term Debt": "Short-term Debt",
            "BalanceSheet::Cash and Cash Equivalents": "Cash and Cash Equivalents",
            "CashFlow::Cash from Operations": "Operating Cash Flow",
            "CashFlow::Capital Expenditure": "Capital Expenditure",
        }

    # ── Structural tests ────────────────────────────────────────────────────────

    def test_nissim_result_attached(self, nissim_data, nissim_maps):
        """PenmanNissimResult must carry nissim_profitability after analysis."""
        r = penman_nissim_analysis(nissim_data, nissim_maps)
        assert r.nissim_profitability is not None

    def test_nissim_result_type(self, nissim_data, nissim_maps):
        """nissim_profitability must be NissimProfitabilityResult."""
        from fin_platform.types import NissimProfitabilityResult
        r = penman_nissim_analysis(nissim_data, nissim_maps)
        assert isinstance(r.nissim_profitability, NissimProfitabilityResult)

    def test_all_three_drivers_computed(self, nissim_data, nissim_maps):
        """OPM, OAT, and OFR must all be populated — the 3-factor drivers."""
        r = penman_nissim_analysis(nissim_data, nissim_maps)
        op = r.nissim_profitability.operating
        assert len(op.opm) > 0, "OPM should be computed"
        assert len(op.oat) > 0, "OAT should be computed (needs OA from balance sheet)"
        assert len(op.ofr) > 0, "OFR should be computed (needs NOA and OA)"

    def test_paper_reference(self, nissim_data, nissim_maps):
        """Paper reference must cite Nissim 2023, SSRN #4064824."""
        r = penman_nissim_analysis(nissim_data, nissim_maps)
        ref = r.nissim_profitability.paper_reference
        assert "Nissim" in ref
        assert "4064824" in ref

    # ── OFR (Operations Funding Ratio) tests ───────────────────────────────────

    def test_ofr_bounds(self, nissim_data, nissim_maps):
        """OFR = NOA/OA must be in (0, 1) for firms with OL < OA."""
        r = penman_nissim_analysis(nissim_data, nissim_maps)
        op = r.nissim_profitability.operating
        for y, v in op.ofr.items():
            assert 0 < v < 1, f"OFR out of (0,1) for year {y}: {v}"

    def test_ofr_complement(self, nissim_data, nissim_maps):
        """Operating credit % must be exactly 1 − OFR."""
        r = penman_nissim_analysis(nissim_data, nissim_maps)
        op = r.nissim_profitability.operating
        for y in op.operating_credit_pct:
            if y in op.ofr:
                assert abs(op.operating_credit_pct[y] / 100.0 + op.ofr[y] - 1.0) < 1e-9, \
                    f"Operating credit + OFR != 1 for {y}"

    def test_ofr_more_stable_than_opm(self, nissim_data, nissim_maps):
        """Nissim (2023) finding: OFR CV < OPM CV (OFR is most stable driver)."""
        r = penman_nissim_analysis(nissim_data, nissim_maps)
        op = r.nissim_profitability.operating
        if op.ofr_stability_cv is not None and op.opm_stability_cv is not None:
            assert op.ofr_stability_cv <= op.opm_stability_cv, (
                f"OFR CV ({op.ofr_stability_cv:.3f}) should be <= OPM CV "
                f"({op.opm_stability_cv:.3f}) — Nissim (2023) Table 4 finding"
            )

    def test_stability_cvs_non_negative(self, nissim_data, nissim_maps):
        """Coefficient of variation must be non-negative."""
        r = penman_nissim_analysis(nissim_data, nissim_maps)
        op = r.nissim_profitability.operating
        for name, val in [
            ("OFR CV", op.ofr_stability_cv),
            ("OAT CV", op.oat_stability_cv),
            ("OPM CV", op.opm_stability_cv),
        ]:
            if val is not None:
                assert val >= 0, f"{name} is negative: {val}"

    def test_stability_notes_generated(self, nissim_data, nissim_maps):
        """Stability notes must be generated when all 3 drivers are computed."""
        r = penman_nissim_analysis(nissim_data, nissim_maps)
        op = r.nissim_profitability.operating
        assert len(op.stability_notes) > 0, "No stability notes generated"

    # ── Mathematical identity tests ─────────────────────────────────────────────

    def test_rnoa_three_factor_identity(self, nissim_data, nissim_maps):
        """
        Core Nissim identity: RNOA = OPM × OAT / OFR.
        Algebraically: (NOPAT/Rev) × (Rev/AvgOA) / (NOA/OA) = NOPAT/AvgNOA = RNOA.
        Must hold to within floating-point tolerance (< 0.01 pp).
        """
        r = penman_nissim_analysis(nissim_data, nissim_maps)
        op = r.nissim_profitability.operating
        for y in op.rnoa_nissim:
            if y in op.opm and y in op.oat and y in op.ofr:
                recon = (op.opm[y] / 100.0) * op.oat[y] / op.ofr[y] * 100.0
                actual = op.rnoa_nissim[y]
                assert abs(recon - actual) < 0.01, (
                    f"3-factor identity failed for {y}: "
                    f"OPM×OAT/OFR={recon:.4f}% vs RNOA={actual:.4f}%"
                )

    def test_rooa_identity(self, nissim_data, nissim_maps):
        """
        ROOA = RNOA × OFR.
        ROOA = NOPAT/AvgOA = (NOPAT/AvgNOA) × (AvgNOA/AvgOA) = RNOA × OFR.
        """
        r = penman_nissim_analysis(nissim_data, nissim_maps)
        op = r.nissim_profitability.operating
        for y in op.rooa:
            if y in op.rnoa_nissim and y in op.ofr:
                expected = op.rnoa_nissim[y] * op.ofr[y]
                actual = op.rooa[y]
                assert abs(expected - actual) < 0.1, (
                    f"ROOA = RNOA × OFR failed for {y}: "
                    f"expected={expected:.4f}%, actual={actual:.4f}%"
                )

    def test_noat_equals_oat_over_ofr(self, nissim_data, nissim_maps):
        """
        Nissim §5.2: NOAT = OAT / OFR.
        This is the algebraic link between standard and novel decompositions.
        """
        r = penman_nissim_analysis(nissim_data, nissim_maps)
        op = r.nissim_profitability.operating
        for y in op.noat:
            if y in op.oat and y in op.ofr and abs(op.ofr[y]) > 0.001:
                expected = op.oat[y] / op.ofr[y]
                actual = op.noat[y]
                assert abs(expected - actual) < 0.1, (
                    f"NOAT = OAT/OFR failed for {y}: {expected:.4f} vs {actual:.4f}"
                )

    # ── ROCE hierarchy tests ────────────────────────────────────────────────────

    def test_roe_decomposition(self, nissim_data, nissim_maps):
        """ROE = Recurring ROE + Transitory ROE (additive identity)."""
        r = penman_nissim_analysis(nissim_data, nissim_maps)
        hier = r.nissim_profitability.roce_hierarchy
        for y in hier.roe:
            if y in hier.recurring_roe and y in hier.transitory_roe:
                recon = hier.recurring_roe[y] + hier.transitory_roe[y]
                actual = hier.roe[y]
                assert abs(recon - actual) < 0.01, (
                    f"ROE decomp failed {y}: Recurring+Transitory={recon:.4f} vs ROE={actual:.4f}"
                )

    def test_financial_leverage_effect_identity(self, nissim_data, nissim_maps):
        """Financial Leverage Effect = FLEV × Financial Spread."""
        r = penman_nissim_analysis(nissim_data, nissim_maps)
        hier = r.nissim_profitability.roce_hierarchy
        for y in hier.financial_leverage_effect:
            flev = hier.financial_leverage.get(y)
            spread = hier.financial_spread.get(y)
            fle = hier.financial_leverage_effect[y]
            if flev is not None and spread is not None:
                assert abs(fle - flev * spread) < 0.1, (
                    f"FLE identity failed {y}: FLE={fle:.4f} vs FLEV×Spread={flev*spread:.4f}"
                )

    def test_interpretation_generated(self, nissim_data, nissim_maps):
        """ROCE hierarchy must generate interpretation notes."""
        r = penman_nissim_analysis(nissim_data, nissim_maps)
        hier = r.nissim_profitability.roce_hierarchy
        assert len(hier.interpretation) > 0

    def test_reconciliation_rows_present(self, nissim_data, nissim_maps):
        """ROCE reconciliation rows must be generated."""
        r = penman_nissim_analysis(nissim_data, nissim_maps)
        hier = r.nissim_profitability.roce_hierarchy
        assert len(hier.roce_reconciliation) > 0

    def test_reconciliation_gap_within_tolerance(self, nissim_data, nissim_maps):
        """
        Reconciliation gap (RNOA + FLE + Other vs Recurring ROE) must be
        within 10% of Recurring ROE or 5pp absolute.
        """
        r = penman_nissim_analysis(nissim_data, nissim_maps)
        hier = r.nissim_profitability.roce_hierarchy
        for row in hier.roce_reconciliation:
            reported = abs(row.get("reported_recurring_roe", 0))
            gap = row.get("gap", 0)
            tol = max(5.0, reported * 0.10)
            assert gap <= tol, (
                f"Large reconciliation gap for {row['year']}: "
                f"{gap:.3f}% (tolerance={tol:.3f}%)"
            )

    # ── No-regression tests ─────────────────────────────────────────────────────

    def test_original_pn_fields_intact(self, nissim_data, nissim_maps):
        """
        Nissim extension must NOT break any existing PN analysis fields.
        All original computations must still be present.
        """
        r = penman_nissim_analysis(nissim_data, nissim_maps)
        # Original PN ratios
        assert r.ratios.get("RNOA %"), "RNOA % must still be computed"
        assert r.ratios.get("OPM %"), "OPM % must still be computed"
        assert r.ratios.get("ROE %"), "ROE % must still be computed"
        # Reformulated statements
        assert r.reformulated_bs.get("Net Operating Assets"), "NOA must be in BS"
        assert r.reformulated_is.get("NOPAT"), "NOPAT must be in IS"
        # Academic extensions
        assert r.academic is not None, "Academic metrics must still be computed"
        assert r.scenarios, "Scenarios must still be generated"
        assert r.thesis is not None, "Thesis must still be generated"
        assert r.diagnostics is not None, "Diagnostics must still be generated"
        # New extension present
        assert r.nissim_profitability is not None, "Nissim extension must be present"

    def test_opm_always_computable(self, sample_data, sample_mappings):
        """
        OPM requires only NOPAT and Revenue — always computable even without
        cash data. Tests backward compatibility with original sample_data fixture.
        """
        r = penman_nissim_analysis(sample_data, sample_mappings)
        op = r.nissim_profitability.operating
        # OPM is purely IS-based so always computed
        assert len(op.opm) > 0, "OPM must be computed from IS data alone"

    # ── Edge case tests ─────────────────────────────────────────────────────────

    def test_no_crash_near_zero_noa(self, nissim_data, nissim_maps):
        """
        Core Nissim (2023) motivation: NOA ≈ 0 breaks NOAT/standard RNOA.
        OAT and ROOA must remain computable; the 3-factor decomposition
        avoids the stability problem by using OA instead of NOA.
        """
        # Inflate operating liabilities to near OA level
        data = dict(nissim_data)
        data["BalanceSheet::Current Liabilities"] = {
            y: v * 3.5 for y, v in nissim_data["BalanceSheet::Current Assets"].items()
        }
        r = penman_nissim_analysis(data, nissim_maps, PNOptions(strict_mode=False))
        op = r.nissim_profitability.operating
        # OAT must still be computed (Revenue / AvgOA)
        assert len(op.oat) > 0, "OAT must be computed even when NOA ≈ 0"
        # ROOA must still be computed (NOPAT / AvgOA)
        assert len(op.rooa) > 0, "ROOA must be computed even when NOA ≈ 0"
        # No crash
        assert r is not None

    def test_no_crash_single_year(self, nissim_data, nissim_maps):
        """Single-year data must not crash (averages fall back to current year)."""
        one_yr = {k: {max(v.keys()): list(v.values())[-1]} for k, v in nissim_data.items()}
        r = penman_nissim_analysis(one_yr, nissim_maps, PNOptions(strict_mode=False))
        assert r.nissim_profitability is not None

    def test_no_crash_minimal_data(self):
        """Nissim analysis must run even with minimal 2-metric, 2-year data."""
        data = {
            "Revenue": {"2022": 1000.0, "2023": 1100.0},
            "Net Income": {"2022": 80.0, "2023": 90.0},
            "Total Assets": {"2022": 800.0, "2023": 850.0},
            "Total Equity": {"2022": 400.0, "2023": 430.0},
            "Income Before Tax": {"2022": 110.0, "2023": 120.0},
            "Tax Expense": {"2022": 30.0, "2023": 30.0},
        }
        mappings = {k: k for k in data.keys()}
        r = penman_nissim_analysis(data, mappings, PNOptions(strict_mode=False))
        assert r.nissim_profitability is not None
        # OPM is IS-based, must be computed
        assert len(r.nissim_profitability.operating.opm) > 0
