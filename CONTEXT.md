# FinAnalyst Pro — Context Document
## Session History and Architecture

---

## v9.2 — Session 6: Critical Mapping Bug Fixes (Feb 2026)

### Root-Cause Analysis: 3 Critical Bugs Found and Fixed

A systematic audit of all 933 Capitaline metric rows against actual CSV values revealed 3 critical bugs where the auto-mapper was returning **zero values** for important financial metrics, silently corrupting every ratio that depended on them.

---

### Bug 1: INVENTORY — Wrong Row Mapped (All Values = 0)

**Symptom:** `Inventory` was mapped to `BalanceSheet::Raw Materials and Components` = 0.00 for ALL years.

**Root Cause:** Capitaline exports total inventory (`Inventories` = ₹454.99 Cr in FY24) AND granular sub-items (`Raw Materials and Components` = 0). Both scored 0.980 in `match_metric`. The greedy mapper, processing CSV rows sequentially, locked onto the sub-item first.

**Impact:** Every inventory-based ratio was broken: Current Ratio, Quick Ratio, Inventory Turnover, Days Inventory Outstanding, and the entire Cash Conversion Cycle.

**Fix (3-layer defense):**
1. `metric_patterns.py` — Inventory exclude patterns now explicitly block sub-item labels (`raw materials`, `finished goods`, `work in progress`, etc.)
2. `auto_map_metrics` tiebreaker (TB-6) — `"inventories"` and `"total inventory"` receive +0.003 bonus to win over any sub-item
3. `analyzer.py` — `_get_inventory_fallback()` added: even if the wrong row is mapped and has value=0, derive_val checks `BalanceSheet::Inventories` / `BalanceSheet::Total Inventory` for a non-zero fallback (belt-and-suspenders for future datasets)

---

### Bug 2: INCOME BEFORE TAX — Double-Stripping of Exceptional Items

**Symptom:** `Income Before Tax` was mapped to `ProfitLoss::Profit Before Exceptional Items and Tax` (PBIT) instead of `ProfitLoss::Profit Before Tax` (PBT).

**Root Cause:** Capitaline exports:
- **"Profit Before Exceptional Items and Tax"** (PBIT) — operating profit BEFORE exceptional items
- **"Profit Before Tax"** (PBT) — total PBT AFTER exceptional items

Both scored 0.980. PBIT appeared first in the CSV, locking the slot.

**Impact (FY25 example with ₹100.49 Cr exceptional gain):**
- Correct: PBT = 369.61, Exceptional = 100.49 → Recurring PBT = 369.61 − 100.49 = **269.12** ✓
- Wrong: PBIT = 269.12, Exceptional = 100.49 → Recurring PBT = 269.12 − 100.49 = **168.63** ✗

The PN framework's `recurring_pbt = pbt - exceptional_items` was double-subtracting exceptional items, making NOPAT, RNOA, OPM, and the investment thesis all wrong in any year with exceptional items.

**Fix:**
- `auto_map_metrics` tiebreaker (TB-7) — `"profit before tax"` receives +0.003 bonus, ensuring PBT always wins over PBIT for the `Income Before Tax` target
- Comment in Income Before Tax patterns clearly explains the double-stripping risk

---

### Bug 3: TOTAL LIABILITIES — Mapped to Bare "Total" Row = 0

**Symptom:** `Total Liabilities` was mapped to `BalanceSheet::Total` = 0.00 for ALL years.

**Root Cause:** Capitaline exports a bare `"Total"` row (zero-value placeholder) that matched `"total liabilities"` via substring scoring at confidence 0.77. After `Total Assets` and `Total Equity` slots were taken, this generic label fell through to Total Liabilities.

**Impact:** All leverage ratios (Debt/Equity, Equity Multiplier) and the PN balance sheet reconciliation used 0 for Total Liabilities.

**Fix (2-layer):**
1. `Total Liabilities` patterns get exclude guards (`"equity"`, `"assets"`) to prevent gross/asset lines from matching
2. `auto_map_metrics` single-word source protection — any source label that is a single token (e.g. `"total"`, `"others"`, `"quoted"`) requires confidence ≥ 0.95 to be mapped (exact abbreviation matches like `pat`, `pbt`, `eps` still work at 0.98)

**Note:** Total Liabilities is correctly derived by `derive_val` as `Total Assets − Total Equity` when not mapped, so the system works even without a direct mapping.

---

### CapEx Fallback — Confirmed Working

`CashFlow::Capital Expenditure` = 0 for all years (Capitaline zero-header pattern).
`CashFlow::Purchased of Fixed Assets` = −48.91 / −403.88 / −94.34 / −41.03 (real values).

The pre-existing `_get_capex_fallback()` in analyzer.py correctly handles this. The `abs(capex_raw) < 1e-9` check triggers the fallback scan, finding the real CapEx. FCF is correctly computed.

---

### Before vs After: Key Value Comparison

| Metric | Before Fix | After Fix | Impact |
|--------|-----------|-----------|--------|
| Inventory FY24 | ₹0.00 | ₹454.99 Cr | Current Ratio fixed |
| Income Before Tax FY25 | ₹269.12 Cr | ₹369.61 Cr | NOPAT, RNOA fixed |
| Recurring PBT FY25 | ₹168.63 Cr | ₹269.12 Cr | PN analysis correct |
| Total Liabilities FY24 | ₹0.00 | ₹467.68 Cr | Leverage ratios fixed |

---

### New Tiebreakers Added to auto_map_metrics

| TB | Target | Preferred Source | Reason |
|----|--------|-----------------|--------|
| TB-6 | Inventory | `"inventories"`, `"total inventory"` | Total lines must beat sub-items |
| TB-7 | Income Before Tax | `"profit before tax"` | Prevents double-stripping of exceptional items |
| TB-8 | Cost of Goods Sold | Primary COGS labels | Aggregate beats sub-totals |

---

### New Helper Functions Added

- `_get_inventory_fallback(data, year)` — scans BalanceSheet for `"inventories"` / `"total inventory"` exact matches; returns largest non-zero value as safety net
- `_get_capex_fallback()` — enhanced with additional tokens, cleaner logic, comment on behavior

---

### Test Coverage

- **49 regression tests pass** covering all Session 5 (Capitaline variant coverage) and Session 6 (bug fixes)
- All 12 critical targets mapped: Revenue, Net Income, Total Assets, Total Equity, Current Assets, Current Liabilities, Operating Cash Flow, Interest Expense, Income Before Tax, Share Capital, Retained Earnings
- **84.8% target coverage** (67/79 targets mapped directly from real Capitaline data)

---

## v9.1 — Session 5: Exhaustive Capitaline Pattern Coverage

### What Was Done
- Systematically tested all 933 unique Capitaline metric rows
- Added 150+ new pattern variants for Depreciation, COGS, Employee Expenses, Interest Expense, Cash Flow, Balance Sheet items
- Fixed tiebreakers for Total Assets vs Total Equity and Liabilities, Revenue net vs gross
- Added Exceptional Items exclude patterns to prevent PBIT from mapping there

---

## Architecture Overview

### Files
- `fin_platform/metric_patterns.py` — Pattern definitions + `auto_map_metrics` greedy mapper
- `fin_platform/analyzer.py` — `derive_val` (multi-level derivation), `_get_capex_fallback`, `_get_inventory_fallback`, full PN analysis
- `fin_platform/parser.py` — CSV parser (builds `data: FinancialData` dict)
- `fin_platform/types.py` — Type definitions

### Key Design Principles
1. **Two-layer mapping**: Pattern matching → auto_map (Layer 1) + fallback derivation in analyze (Layer 2)
2. **Tiebreakers over exclude**: When two sources tie at 0.980, a small bonus (+0.001–0.003) determines winner
3. **Single-word protection**: Generic labels (bare "Total", "Others") cannot map at low confidence
4. **Fallbacks for zero-value header rows**: CapEx and Inventory both have scanner fallbacks that find real sub-line values when mapped headers export 0

### Unmapped Targets (by design)
- `Gross Profit` — derived as Revenue − COGS
- `Operating Income` — derived as EBIT
- `Free Cash Flow` — derived as OCF − CapEx
- `Total Liabilities` — derived as Total Assets − Total Equity
- `Market Capitalisation`, `Book Value Per Share`, `Face Value`, `Number of Shares` — financial data, not in CF/BS/PL CSV export
- `Manufacturing Expenses` — Capitaline uses specific sub-labels, no generic total
- `Other Short-term Financial Assets`, `Share Buyback` — no consistent Capitaline label

---

## Session 7 — Coverage Regression Fix (67/79 → 69/79, 87.3%)

### Problem Statement
After Session 6, coverage dropped from 87.3% (69/79) to 84.8% (67/79). Two targets were "lost":
- `Other Short-term Liabilities` and `Total Liabilities`
- The v9.1 mappings for both were **false recoveries** (mapped to zero-value rows `BalanceSheet::Other` and `BalanceSheet::Total` respectively, both = 0 all years)
- The single-word source protection added in Session 6 correctly blocked these, but left the targets unmapped

### Root-Cause Analysis (All 6 Bugs)

#### Bug Class A — CSV-order tie, zero-value source wins (3 bugs)
Both zero and correct sources score 0.98. Zero-value row appears first in Capitaline's CSV export.

| Target | Zero source (row) | Correct source (row) |
|--------|------------------|---------------------|
| `Bank Balances` | `Balances with Bank / Margin Money Balances` (row 278, =0) | `Bank Balances Other Than Cash and Cash Equivalents` (row 449, =10.76) |
| `Current Tax Liabilities` | `Income Tax Liability` (row 341, =0) | `Current Tax Liabilities - Short-term` (row 487, =19.98) |
| `Long-term Investments` | `Investments in Subsidiaries...` (row 184, =0) | `Investments - Long-term` (row 217, =200.11) |

**Fix:** Added tiebreakers TB-9/10/11 giving +0.003 to the correct specific source in each case.

#### Bug Class B — "nci" pattern is a substring of "financial" (2 unmapped)
The `Minority Interest` pattern `"nci"` is a 3-char substring of `"finan(nci)al"`. Sources containing "financial" falsely scored 0.857 for `Minority Interest`, blocking the real targets.

| Source | False winner (0.857) | Should map to |
|--------|---------------------|--------------|
| `Others Financial Liabilities - Short-term` | Minority Interest | `Other Short-term Liabilities` |
| `Others Financial Assets - Short-term` | Minority Interest | `Other Short-term Financial Assets` |

**Fix (2-layer):**
1. Added Capitaline-specific exact-match patterns to both targets (score 0.98 >> 0.857)
2. Added `"financial liabilities"` and `"financial assets"` as exclude patterns to `Minority Interest`

#### Bug Class C — `&` normalization strips pattern (1 no-match)
`Total Selling & Administrative Expenses` → `_normalize_text` removes `&` → `"total selling administrative expenses"` — no existing pattern matched this.

Also `Selling and Administration Expenses` matched `Depreciation` via fuzzy match.

**Fix:** Added explicit patterns to `Selling Expenses`:
- `"total selling administrative expenses"` (handles & normalization)
- `"selling and administration expenses"`
- `"total selling and distribution expenses"` and variants

Plus TB-12 tiebreaker ensuring non-zero aggregate labels beat zero sub-labels.

### Before/After Comparison

| Target | Before (v9.2) | After (v9.3) | Impact |
|--------|--------------|--------------|--------|
| Other Short-term Liabilities | UNMAPPED | ₹49.68 Cr (FY25) | Balance sheet complete |
| Other Short-term Financial Assets | UNMAPPED | ₹2.81 Cr (FY24) | Balance sheet complete |
| Bank Balances | ₹0 | ₹10.76 Cr (FY24) | Correct non-cash balances |
| Current Tax Liabilities | ₹0 | ₹19.98 Cr (FY24) | Correct tax payable |
| Long-term Investments | ₹0 | ₹200.11 Cr (FY24) | Correct long-term portfolio |
| Selling Expenses | ₹0 | ₹123.75 Cr (FY25) | Operating cost structure correct |

### Cross-Validation vs Screener.in (VST Industries, March 2025)
All 12 critical targets verified against external source (100% match within ₹1 Cr rounding):
Revenue 1397.76 ✓ | Net Income 290.39 ✓ | PBT 369.61 ✓ | Depreciation 44.49 ✓
OCF 193.47 ✓ | Total Assets 1816.0 ✓ | Share Capital 169.86 ✓ | Retained Earnings 1152.83 ✓
Long-term Debt 0.0 ✓ | Short-term Debt 0.0 ✓ | Interest Expense 0.0 ✓

### Files Modified
- `fin_platform/metric_patterns.py`: 6 fixes across PatternDef definitions and `_sort_key` function
  - `Other Short-term Liabilities`: added Capitaline exact-match patterns
  - `Other Short-term Financial Assets`: added Capitaline exact-match patterns
  - `Minority Interest`: added "financial liabilities" / "financial assets" excludes
  - `Selling Expenses`: added 5 new Capitaline label patterns
  - `_sort_key`: added TB-9 (Bank Balances), TB-10 (Current Tax Liabilities), TB-11 (Long-term Investments), TB-12 (Selling Expenses)

### Test Coverage
- All 17 Session 7 regression tests pass ✓
- All Session 6 fixes intact ✓ (Inventory, Income Before Tax, Total Liabilities derive)
- 240/240 non-fixture unit tests pass ✓
