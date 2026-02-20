# CAPITALINE DATA MAPPING AUDIT REPORT

## P&N Financial Framework — v9 Analysis

- **15 Fiscal Years**
- **933 Raw Metrics**
- **69 Mappings**
- **Generated:** February 20, 2026

## 1. Executive Summary

- **933** raw metrics
- **69 / 79** targets mapped
- **87.3%** coverage
- **15 years clean**
- **P&N reconciliation:** 0.00 gap across all years

This report documents the complete audit of Capitaline raw financial data mapped to standardised P&N framework targets for the company under analysis. The debug package (v9) covers 15 fiscal years from FY2011 to FY2025, drawing on 933 distinct Capitaline metrics across the Balance Sheet, Profit & Loss, Cash Flow, and Financial statements.

The mapping layer translates 69 Capitaline source metrics to normalised target fields. All 69 active mappings have been individually verified against raw data values. The P&N reformulated statements reconcile to zero gap across all 15 years — confirming no double-counting or classification errors in the balance sheet or income statement.

Three data anomalies were identified and validated as economically explainable rather than errors: a bonus share issue in FY2025 that shifted capital between Share Capital and Other Equity; a material exceptional item in FY2025 explaining the FY25 ROE decomposition gap; and a consistently empty Capital Expenditure header in the Cash Flow statement for which a fallback mapping to `Purchased of Fixed Assets` is already in place.

Ten targets remain unmapped (87.3% coverage). Five are arithmetically derivable from existing mappings, one can be directly mapped to an available Capitaline metric, and four require an external data source (Market Capitalisation, Face Value, Number of Shares, and Share Buyback).

### Coverage by Statement

| Statement | Total Targets | Mapped | Unmapped | Coverage |
|---|---:|---:|---:|---:|
| Balance Sheet | 41 | 40 | 1 | 97.6% |
| Profit & Loss | 22 | 19 | 3 | 86.4% |
| Cash Flow | 12 | 10 | 2 | 83.3% |
| Financial | 4 | 0 | 4 | 0.0% |
| **Total** | **79** | **69** | **10** | **87.3%** |

## 2. Full Mapping Registry

All 69 active mappings are listed below, grouped by source statement. Each entry reflects the Capitaline field name as it appears in `raw_data.json` mapped to the normalised target field used in the P&N framework.

### 2.1 Balance Sheet (40 mappings)

| Capitaline Source Metric | Target Field |
|---|---|
| Bank Balances Other Than Cash and Cash Equivalents | Bank Balances |
| Capital Work in Progress | Capital Work in Progress |
| Cash and Cash Equivalents | Cash and Cash Equivalents |
| Contingent Liabilities and Commitments | Contingent Liabilities |
| Current Investments | Short-term Investments |
| Current Tax Liabilities - Short-term | Current Tax Liabilities |
| Deferred Tax Assets (Net) | Deferred Tax Assets |
| Deferred Tax Liability | Deferred Tax Liabilities |
| Fixed Assets | Fixed Assets |
| Fixed Assets Held For Sale | Assets Held for Sale |
| Goodwill | Goodwill |
| Intangible Assets | Intangible Assets |
| Inventories | Inventory |
| Investment Properties | Investment Property |
| Investments - Long-term | Long-term Investments |
| Lease Liabilities | Lease Liabilities |
| Liabilities Directly Associated with Assets Classified as Held for Sale | Liabilities Held for Sale |
| Loans - Short-term | Short-term Loans |
| Long Term Borrowings | Long-term Debt |
| Long-term Provisions | Provisions |
| Minority Interest | Minority Interest |
| Other Current Assets | Other Current Assets |
| Other Current Liabilities | Other Current Liabilities |
| Other Equity | Retained Earnings |
| Other Non-Current Liabilities | Other Non-Current Liabilities |
| Other Non-current Assets | Other Non-Current Assets |
| Others Financial Assets - Short-term | Other Short-term Financial Assets |
| Others Financial Liabilities - Short-term | Other Short-term Liabilities |
| Property, Plant and Equipment | Property Plant Equipment |
| Right-of-Use Assets | Right of Use Assets |
| Share Capital | Share Capital |
| Short Term Borrowings | Short-term Debt |
| Total Assets | Total Assets |
| Total Current Assets | Current Assets |
| Total Current Liabilities | Current Liabilities |
| Total Equity | Total Equity |
| Total Reported Non-current Assets | Non-Current Assets |
| Total Reported Non-current Liabilities | Non-Current Liabilities |
| Trade Payables | Accounts Payable |
| Trade Receivables | Trade Receivables |

### 2.2 Profit & Loss (19 mappings)

| Capitaline Source Metric | Target Field |
|---|---|
| Changes in Inventories of FG, WIP and Stock-in-Trade | Changes in Inventory |
| Cost of Material Consumed | Cost of Goods Sold |
| Depreciation and Amortization | Depreciation |
| Earning Per Share - Basic | EPS Basic |
| Earning Per Share - Diluted | EPS Diluted |
| Employee Benefits / Salaries & other Staff Cost | Employee Expenses |
| Exceptional Items Before Tax | Exceptional Items |
| Finance Cost | Interest Expense |
| Non-Controlling Interests | Minority Earnings |
| Other Expenses | Other Expenses |
| Other Income | Other Income |
| Profit After Tax | Net Income |
| Profit Before Tax | Income Before Tax |
| Revenue From Operations(Net) | Revenue |
| Selling and Administration Expenses | Selling Expenses |
| Tax Expenses | Tax Expense |
| Total Dividend Per Share | Dividend |
| Total Expenses | Total Expenses |
| Total Revenue | Total Revenue |

### 2.3 Cash Flow (10 mappings)

| Capitaline Source Metric | Target Field |
|---|---|
| Capital Expenditure | Capital Expenditure |
| Cash and Cash Equivalents at Beginning of the year | Cash Beginning |
| Cash and Cash Equivalents at End of the year | Cash Ending |
| Change in Borrowing | Proceeds from Borrowing |
| Dividend Paid | Dividends Paid |
| Net Cash Used in Financing Activities | Financing Cash Flow |
| Net Cash Used in Investing Activities | Investing Cash Flow |
| Net Cash from Operating Activities | Operating Cash Flow |
| Net Inc/(Dec) in Cash and Cash Equivalent | Net Change in Cash |
| On Redemption of Debenture | Debt Repayment |

## 3. Unmapped Targets

Ten of the 79 normalised targets are currently unmapped.

| Target Field | Resolution Type | Recommended Action / Source |
|---|---|---|
| Total Liabilities | Derivable | Total Assets − Total Equity |
| Gross Profit | Derivable | Revenue − COGS |
| Operating Income | Derivable | Gross Profit − Operating Expenses |
| Free Cash Flow | Derivable | Operating Cash Flow − Capital Expenditure |
| Book Value Per Share | Derivable | Total Equity ÷ Number of Shares |
| Manufacturing Expenses | Mappable | Total Manufacturing / Direct Expenses |
| Share Buyback | Not Found | No equivalent in Capitaline raw data |
| Market Capitalisation | External | Financial statement; requires separate data source |
| Face Value | External | Financial statement; requires separate data source |
| Number of Shares | External | Financial statement; requires separate data source |

### Resolution Key

- **Derivable:** Can be calculated from existing mapped fields. No new data source required.
- **Mappable:** A suitable Capitaline metric exists in `raw_data.json`; a new mapping entry is needed.
- **External:** Requires a separate data source (e.g. NSE/BSE feed, financial statement metadata).
- **Not Found:** No equivalent found anywhere in the 933-metric Capitaline dataset.

## 4. Data Anomalies & Findings

Four noteworthy findings were identified during the audit. All are economically explainable and reflect characteristics of the underlying company rather than mapping errors.

### 4.1 Bonus Issue — FY2025 Share Capital Jump

Share Capital increased from ₹15.4 Cr (FY2024) to ₹169.9 Cr (FY2025), a rise of ₹154.4 Cr. Over the same period, Other Equity fell from ₹1,237.0 Cr to ₹1,152.8 Cr — a decline of ₹84.2 Cr. Total Equity rose by a modest ₹70.3 Cr, consistent with normal retained earnings growth.

|  | FY2023 (₹ Cr) | FY2024 (₹ Cr) | FY2025 (₹ Cr) |
|---|---:|---:|---:|
| Share Capital | 15.4 | 15.4 | 169.9 |
| Other Equity | 1164.3 | 1237.0 | 1152.8 |
| Total Equity | 1179.7 | 1252.4 | 1322.7 |

**Assessment:** Mapping is correct. The jump is a presentational reclassification within equity.

### 4.2 Exceptional Items — FY2025

FY2025 contains a ₹100.5 Cr exceptional item (pre-tax), creating divergence between recurring and reported earnings.

| P&L Line | FY2023 | FY2024 | FY2025 |
|---|---:|---:|---:|
| Profit Before Exceptional Items and Tax | 428.9 | 394.7 | 269.1 |
| Exceptional Items Before Tax | 0.0 | 0.0 | 100.5 |
| Profit Before Tax | 428.9 | 394.7 | 369.6 |

**Assessment:** The ROE diagnostics “fix suggestion” is a false alarm. No mapping change required.

### 4.3 Capital Expenditure Header — Always Zero

`Capital Expenditure` shows ₹0.0 across all 15 years, while actual investment is recorded under `Purchased of Fixed Assets`.

| Cash Flow Field | FY2023 | FY2024 | FY2025 |
|---|---:|---:|---:|
| Capital Expenditure (header) | 0.0 | 0.0 | 0.0 |
| Purchased of Fixed Assets | -403.9 | -94.3 | -41.0 |

**Assessment:** Fallback mapping is already implemented and working correctly.

### 4.4 Debt-Free Balance Sheet

`Long Term Borrowings`, `Short Term Borrowings`, and `Finance Cost` are effectively zero across all 15 years.

**Assessment:** Mapping is correct. Negative FLEV reflects net financial assets, not borrowing stress.

## 5. P&N Framework Validation

The Penman–Nissim identity (`NOA + NFA = Common Equity`) reconciles to zero across all 15 years.

### 5.1 P&N Reconciliation — All 15 Years

| Year | NOA | NFA | NOA + NFA | Common Equity | Gap |
|---|---:|---:|---:|---:|---:|
| FY2011 | 86.2 | 178.2 | 264.4 | 264.4 | 0.00 |
| FY2012 | 55.4 | 234.8 | 290.2 | 290.2 | 0.00 |
| FY2013 | 65.4 | 238.7 | 304.1 | 304.1 | 0.00 |
| FY2014 | 108.4 | 219.8 | 328.2 | 328.2 | 0.00 |
| FY2015 | 141.7 | 205.0 | 346.7 | 346.7 | 0.00 |
| FY2016 | 196.4 | 174.1 | 370.4 | 370.4 | 0.00 |
| FY2017 | 345.4 | 193.5 | 539.0 | 539.0 | 0.00 |
| FY2018 | 128.4 | 453.7 | 582.1 | 582.1 | 0.00 |
| FY2019 | 51.9 | 612.2 | 664.0 | 664.0 | 0.00 |
| FY2020 | -3.4 | 790.4 | 787.1 | 787.1 | 0.00 |
| FY2021 | 32.5 | 908.0 | 940.4 | 940.4 | 0.00 |
| FY2022 | 88.2 | 986.1 | 1074.3 | 1074.3 | 0.00 |
| FY2023 | 582.6 | 597.1 | 1179.7 | 1179.7 | 0.00 |
| FY2024 | 770.1 | 482.3 | 1252.4 | 1252.4 | 0.00 |
| FY2025 | 773.2 | 549.5 | 1322.7 | 1322.7 | 0.00 |

## 6. Recommendations

### 6.1 High Priority — Add Derivable Mappings

- Total Liabilities = Total Assets − Total Equity
- Gross Profit = Revenue From Operations(Net) − Cost of Material Consumed
- Operating Income = Gross Profit − (Employee Expenses + Selling Expenses + Other Expenses + Depreciation)
- Free Cash Flow = Net Cash from Operating Activities − |Purchased of Fixed Assets|
- Book Value Per Share = Total Equity ÷ Number of Shares (once sourced)

### 6.2 Medium Priority — Direct Mapping Addition

Map `Manufacturing Expenses` to `Total Manufacturing / Direct Expenses`.

### 6.3 Low Priority — External Data Source

Integrate external provider(s) for:

- Market Capitalisation
- Face Value
- Number of Shares
- Share Buyback

### 6.4 Analytical Guidance

- FY2020–FY2022: Prefer ROOA over RNOA/NOAT (denominator instability).
- FY2025: Compare recurring (`EBIT`, `NOPAT`) vs reported (`Net Income`) carefully due to exceptional item.
- Investment classification sensitivity can be tested via `treat_investments_as_operating`.

## 7. Appendix — Raw Metric Counts

| Statement | Metric Count |
|---|---:|
| Balance Sheet | 498 |
| Profit & Loss | 362 |
| Cash Flow | 73 |
