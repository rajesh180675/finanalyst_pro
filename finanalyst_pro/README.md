# 📊 FinAnalyst Pro

**Enterprise Penman-Nissim Financial Analysis Platform — Capitaline Data Specialist**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/streamlit-1.32+-red.svg)](https://streamlit.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 🔬 Overview

FinAnalyst Pro converts raw Capitaline financial exports into rigorous academic-grade financial analysis using the **Penman-Nissim (2001)** reformulation framework, combined with modern financial engineering techniques.

### What It Does

| Module | Capability |
|--------|-----------|
| **Auto-Mapper** | 73+ Capitaline patterns — fuzzy + exact matching with statement gating, exclude-patterns, priority weighting |
| **PN Reformulation** | NOA / NFA / NOPAT with holding company auto-detection (FLEV < 0 = net cash) |
| **ReOI Valuation** | V = NOA₀ + PV(Explicit) + PV(Terminal), 3 forecast methods |
| **Shapley 3-Factor** | NOPAT attribution: Margin × Turnover × Capital Base |
| **Scenario Analysis** | Bear / Base / Bull with mean-reversion pro-forma (configurable speed) |
| **Accrual Quality** | NOA / OA / Sales denominator waterfall with tier classification |
| **Scoring Models** | Altman Z-Score (1968) + Piotroski F-Score (2000) |
| **Diagnostics** | ROE gap check, IS reconciliation, data hygiene, classification audit |

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11 or higher
- pip

### Installation

```bash
# Clone or unzip the project
cd finanalyst_pro

# Install dependencies
pip install -r requirements.txt

# Run the app
streamlit run app.py
```

The app opens at `http://localhost:8501`

### Cloud Deployment (Streamlit Community Cloud)

1. Push this repo to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your GitHub repo
4. Set **Main file path** to `app.py`
5. Click **Deploy**

---

## 📁 Project Structure

```
finanalyst_pro/
├── app.py                          # Streamlit UI — 10 analysis tabs
├── requirements.txt                # Python dependencies
├── README.md                       # This file
├── .streamlit/
│   └── config.toml                 # Theme & server settings
├── .github/
│   └── workflows/
│       └── ci.yml                  # GitHub Actions CI (lint + test)
├── fin_platform/                   # Core analysis package
│   ├── __init__.py
│   ├── types.py                    # 25+ dataclasses (FinancialData → ScenarioValuation)
│   ├── metric_patterns.py          # 73+ Capitaline patterns, fuzzy auto-mapper
│   ├── parser.py                   # Multi-sheet Excel/CSV/HTML parser, year detection
│   ├── analyzer.py                 # Full PN engine, Altman Z, Piotroski F
│   └── formatting.py               # Indian number system (Crores/Lakhs)
└── tests/
    ├── __init__.py
    └── test_analyzer.py            # 45+ unit tests
```

---

## 📊 Supported Input Formats

| Format | Extension | Notes |
|--------|-----------|-------|
| Excel (multi-sheet) | `.xlsx`, `.xls` | Auto-detects P&L / BS / CF sheets |
| CSV | `.csv` | Single statement per file |
| HTML Tables | `.html`, `.htm` | Capitaline web export format |

### Year Format Detection

The parser recognises all common Indian FY formats:

| Input | Resolved To |
|-------|------------|
| `FY2024` | `202403` |
| `Mar 2024` | `202403` |
| `2024-25` | `202403` |
| `202403` | `202403` |
| `2024` | `202403` |

---

## 🔬 Analytical Framework

### 1. Penman-Nissim Balance Sheet Reformulation

```
Total Assets  =  Operating Assets (OA)  +  Financial Assets (FA)
                 Operating Liab (OL)    +  Financial Liab (FL)
                 ─────────────────────────────────────────────
Net Operating Assets (NOA)  =  OA − OL
Net Financial Assets (NFA)  =  FA − FL
Common Equity               =  NOA + NFA
```

**Holding Company Adjustment:** When `investment/asset ratio > 30%` and `inventory ratio < 5%`, investments are automatically reclassified as Operating Assets (configurable).

### 2. Income Statement Reformulation

```
NOPAT  =  Operating Income Before Tax × (1 − Effective Tax Rate)
NFE_AT =  (Financial Expense − Financial Income) × (1 − Tax Rate)
Net Income  =  NOPAT − NFE_AT
```

### 3. PN Ratio Framework

| Ratio | Formula |
|-------|---------|
| RNOA % | NOPAT / Avg NOA |
| ROOA % | NOPAT / Avg OA (stability fallback) |
| OPM % | NOPAT / Revenue |
| NOAT | Revenue / Avg NOA |
| FLEV | −NFA / Avg CE |
| NBC % | NFE_AT / Avg NFO |
| Spread % | RNOA − NBC |
| ROE (PN) | RNOA + FLEV × Spread |

### 4. ReOI Valuation

```
ReOI_t  =  NOPAT_t − r × NOA_{t-1}

Intrinsic Value  =  NOA_0  +  Σ PV(ReOI_t)  +  PV(Terminal)

Terminal Value   =  ReOI_N × (1 + g) / (r − g)
```

Three forecast seeds: `reoi_last` | `reoi_mean3` | `reoi_trend3`

### 5. Shapley 3-Factor NOPAT Attribution

```
NOPAT = OPM × NOAT × AvgNOA

Shapley attributes ΔNOPAT to:
  • Margin Effect    (ΔOPM)
  • Turnover Effect  (ΔNOAT)
  • Capital Base     (ΔAvgNOA)
```

Uses all 6 permutations for exact Shapley values.

### 6. Accrual Quality

```
Operating Accruals = NOPAT − OCF

Denominator waterfall:
  1. Avg NOA (if |AvgNOA| > max(10, 5% of AvgTA))
  2. Avg OA (fallback)
  3. Sales (last resort)

Quality Tiers:
  High   → |Accrual Ratio| < 5%
  Medium → 5% – 15%
  Low    → > 15%
```

---

## 🏢 Holding Company Detection

The platform auto-detects holding/investment companies and adjusts the PN framework:

```python
is_holding_company = (
    investment_asset_ratio > 30%  AND
    inventory_ratio < 5%
)

is_investment_company = (
    investment_asset_ratio > 50%  OR
    (other_income_ratio > 10% AND investment_asset_ratio > 25%)
)
```

Override via **Investment Classification** sidebar control: `auto` | `operating` | `investment`

---

## 🛡️ Scoring Models

### Altman Z-Score (1968)
```
Z = 1.2×(WC/TA) + 1.4×(RE/TA) + 3.3×(EBIT/TA) + 0.6×(E/TL) + 1.0×(Rev/TA)

Z > 2.99  →  Safe Zone
1.81–2.99 →  Grey Zone
Z < 1.81  →  Distress Zone
```

### Piotroski F-Score (2000)
9 binary signals across Profitability, Leverage/Liquidity, and Operating Efficiency.

---

## 🎛️ Configuration

### Sidebar Controls (Runtime)

| Control | Range | Default | Effect |
|---------|-------|---------|--------|
| Cost of Capital (r) | 5%–25% | 10% | ReOI capital charge & discount rate |
| Terminal Growth (g) | 0%–10% | 3% | Perpetuity growth in TV |
| Forecast Horizon | 3–15 years | 5 | Explicit ReOI forecast period |
| Forecast Method | last / mean3 / trend3 | mean3 | ReOI seed for projection |
| Classification Mode | auto / operating / investment | auto | Investment asset treatment |
| Strict Mode | on/off | on | Disables fallback assumption fill |

### `.streamlit/config.toml`

```toml
[theme]
primaryColor = "#1E40AF"
backgroundColor = "#F8FAFC"
secondaryBackgroundColor = "#EFF6FF"
textColor = "#1E293B"

[server]
maxUploadSize = 200   # MB
```

---

## 🧪 Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=fin_platform --cov-report=html

# Run specific test class
pytest tests/test_analyzer.py::TestPenmanNissimAnalysis -v
```

Test coverage spans:
- Year extraction (8 format variants)
- Numeric normalisation (commas, brackets, ₹, Nil)
- Metric pattern matching & auto-mapping
- Standard ratio computation (liquidity, profitability, leverage, efficiency)
- PN balance sheet and income statement reformulation
- ReOI, AEG, accrual quality
- Shapley 3-factor consistency check
- Altman Z zones
- Piotroski F signal count
- Edge cases: empty data, single year, terminal growth ≥ r

---

## 📖 References

1. Penman, S.H. & Nissim, D. (2001). *Ratio Analysis and Equity Valuation: From Research to Practice.* Review of Accounting Studies, 6(1), 109-154.
2. Altman, E.I. (1968). *Financial Ratios, Discriminant Analysis and the Prediction of Corporate Bankruptcy.* Journal of Finance, 23(4), 589-609.
3. Piotroski, J.D. (2000). *Value Investing: The Use of Historical Financial Statement Information to Separate Winners from Losers.* Journal of Accounting Research, 38, 1-41.
4. Shapley, L.S. (1953). *A Value for n-Person Games.* Contributions to the Theory of Games, 2, 307-317.

---

## 📄 License

MIT License — see [LICENSE](LICENSE) file.

---

*FinAnalyst Pro v8.0 — Built for rigorous financial analysis of Indian listed companies.*

---

## 🆕 Nissim (2023) Profitability Analysis Integration

This platform integrates the novel profitability decomposition from:

> **Nissim, D. (2023). "Profitability Analysis."**  
> Columbia Business School. SSRN Working Paper #4064824.  
> https://papers.ssrn.com/abstract_id=4064824

### Key Innovations Implemented

#### 1. 3-Factor RNOA Decomposition
**RNOA = OPM × OAT / OFR**

| Factor | Formula | Interpretation |
|--------|---------|---------------|
| **OPM** — Operating Profit Margin | NOPAT / Revenue | Revenue-to-capital flow efficiency |
| **OAT** — Operating Asset Turnover | Revenue / Avg **OA** (not NOA) | Sales generated per ₹ of ALL operating assets |
| **OFR** — Operations Funding Ratio | NOA / OA | Proportion of OA funded by capital (not operating credit) |

**Why better than standard OPM × NOAT?**
- When NOA is near-zero or negative, NOAT is unstable/meaningless
- Sales are generated by ALL operating assets regardless of funding source  
- OFR captures the operating credit effect explicitly

#### 2. Operations Funding Ratio (OFR)
- `OFR = NOA / OA = 1 - (Operating Liabilities / Operating Assets)`  
- Low OFR → large operating credit → indicates **market power** or future earnings reversals  
- Empirically: Mean ≈ 64%, CV ≈ 0.079 (most stable of the three RNOA drivers)
- Persistence (1-year): ≈ 0.955 vs OAT ≈ 0.946 vs OPM ≈ 0.723

#### 3. Full ROCE Hierarchy
```
ROCE
├── NCI Leverage Effect = NCI Leverage × NCI Spread
└── ROE
    ├── Transitory ROE = Transitory Income / Avg Equity
    └── Recurring ROE
        ├── RNOA = NOPAT / Avg NOA
        ├── Financial Leverage Effect = FLEV × (RNOA − NBC)
        └── Net Other Nonop Assets Effect
```

#### 4. Forecasting Implications
- Anchor OFR to historical mean (most stable) → derive OL forecast = OA × (1−OFR)
- Mean-revert OPM (most volatile) toward industry benchmark
- OAT extrapolation is intermediate in confidence

### New Data Types
- `NissimOperatingDecomposition` — 3-factor drivers + stability CVs
- `NissimROCEHierarchy` — Full ROCE hierarchy decomposition
- `NissimProfitabilityResult` — Container attached to `PenmanNissimResult.nissim_profitability`

### New UI Tab
**PN Analysis → 📐 Nissim (2023) Profitability**
- 3-Factor RNOA table with stability CVs
- Full ROCE hierarchy (3 levels)
- Operating Credit deep-dive  
- Interactive charts
- Methodology reference
