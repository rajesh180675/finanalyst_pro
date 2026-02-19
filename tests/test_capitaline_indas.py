import pytest

from fin_platform.capitaline_indas import (
    CapitalineIndASConfig,
    recast_period,
    residual_earnings,
    residual_operating_income,
)


def _sample_data():
    return {
        "BalanceSheet::Total Assets": {"202303": 1400.0, "202403": 1600.0},
        "BalanceSheet::Total Equity": {"202303": 620.0, "202403": 700.0},
        "BalanceSheet::Minority Interest": {"202303": 20.0, "202403": 30.0},
        "BalanceSheet::Total Stockholders' Equity": {"202303": 600.0, "202403": 670.0},
        "BalanceSheet::Cash and Cash Equivalents": {"202303": 50.0, "202403": 60.0},
        "BalanceSheet::Current Investments": {"202303": 35.0, "202403": 40.0},
        "BalanceSheet::Investments - Long-term": {"202303": 25.0, "202403": 30.0},
        "BalanceSheet::Others Financial Assets - Short-term": {"202303": 5.0, "202403": 8.0},
        "BalanceSheet::Long Term Borrowings": {"202303": 280.0, "202403": 300.0},
        "BalanceSheet::Short Term Borrowings": {"202303": 60.0, "202403": 80.0},
        "BalanceSheet::Others Financial Liabilities - Short-term": {"202303": 38.0, "202403": 50.0},
        "ProfitLoss::Revenue From Operations(Net)": {"202303": 900.0, "202403": 980.0},
        "ProfitLoss::Total Comprehensive Income for the Year": {"202303": 100.0, "202403": 120.0},
        "ProfitLoss::Non-Controlling Interests": {"202303": 5.0, "202403": 6.0},
        "ProfitLoss::Preference Dividend": {"202303": 0.0, "202403": 0.0},
        "ProfitLoss::Finance Cost": {"202303": 27.0, "202403": 28.0},
        "ProfitLoss::Tax Expense": {"202303": 19.0, "202403": 22.0},
        "ProfitLoss::Profit Before Tax": {"202303": 94.0, "202403": 103.0},
        "ProfitLoss::Other Income": {"202303": 8.0, "202403": 12.0},
        "ProfitLoss::Exceptional Items Before Tax": {"202303": 2.0, "202403": 0.0},
        "CashFlow::Interest Received": {"202303": 3.0, "202403": 4.0},
        "CashFlow::Dividend Received": {"202303": 2.0, "202403": 2.0},
        "CashFlow::P/L on Sales of Invest": {"202303": -2.0, "202403": -3.0},
    }


def test_recast_classifies_other_financial_liabilities_as_fo():
    out = recast_period(_sample_data(), "202403", "202303", CapitalineIndASConfig())
    assert out["FO"] == pytest.approx(430.0)
    assert out["NFO"] > 0
    assert out["ratios"]["ROCE"] is not None


def test_finance_income_fallback_uses_cashflow_signals():
    out = recast_period(_sample_data(), "202403", None, CapitalineIndASConfig())
    assert out["FinanceIncome"] == pytest.approx(6.0)
    assert out["FinanceIncomeConfidence"] == "medium"


def test_residual_valuation_functions_run():
    v_re = residual_earnings([110.0, 120.0, 130.0], cse_opening=700.0, cost_of_equity=0.12, continuing="CV2")
    v_reoi = residual_operating_income([150.0, 160.0, 170.0], noa_opening=900.0, wacc=0.1, continuing="CV02")
    assert v_re > 0
    assert v_reoi > 0
