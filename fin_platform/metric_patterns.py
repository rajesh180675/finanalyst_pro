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
    "Bank Balances": PatternDef("BalanceSheet", [
        "bank balances other than cash",
        "bank balances other than",
        "other bank balances",
        "bank balances other than cash and cash equivalents",  # Capitaline full label
        "earmarked balances with bank",
        "balances with bank / margin money balances",
        "margin money balances",
    ], priority=6),
    "Short-term Investments": PatternDef("BalanceSheet", ["current investments", "short term investments", "short-term investments"], ["non-current", "long term", "investments - long"], priority=7),
    "Long-term Investments": PatternDef("BalanceSheet", [
        "investments - long-term",
        "investments - long term",
        "non-current investments",
        "long term investments",
        "investments in subsidiaries",
        "investments in associates",
        "investments in subsidiaries, associates and joint venture",   # Capitaline full label
        "investments in subsidiaries associates and joint venture",
        "total investment in subsidiaries associates and joint venture",
        "total investments",
        "total long-term stock",
        "associate companies",                   # Capitaline BS sub-line for associates
        "joint venture companies",               # Capitaline BS sub-line for JVs
        "subsidiary companies",                  # Capitaline BS sub-line for subs
    ], ["current investments", "short term", "stock in trade"], priority=7),
    "Inventory": PatternDef("BalanceSheet", [
        "inventories",                           # Capitaline INDAS: exact total line — highest priority
        "total inventory",                       # Capitaline totals aggregate
        "total inventories",
        "inventory",
        "stock in trade",
        "stock-in-trade",
        "stores and spares",                     # Capitaline sub-line that represents total inventory in some companies
    ], [
        "changes in inventories",
        "non current portion",
        "raw materials",                         # sub-items — Raw Materials and Components should NOT map here
        "finished goods",                        # sub-item
        "work in progress",                      # sub-item
        "packing material",                      # sub-item
        "other material",                        # sub-item
        "opening stock",                         # sub-item
        "closing stock",                         # sub-item
    ], priority=7),
    "Trade Receivables": PatternDef("BalanceSheet", ["trade receivables", "sundry debtors", "accounts receivable", "debtors"], priority=7),
    "Other Current Assets": PatternDef("BalanceSheet", ["other current assets"], ["total", "non-current"], priority=5),
    "Short-term Loans": PatternDef("BalanceSheet", ["short term loans", "short-term loans", "loans repayable on demand", "loans current"], ["long term", "non-current"], priority=6),
    "Other Short-term Financial Assets": PatternDef("BalanceSheet", [
        "other short term financial assets",
        "other short-term financial assets",
        "other financial assets current",
        # Capitaline INDAS: "Others Financial Assets - Short-term" (normalizes to exact below)
        "others financial assets short term",
        "others financial assets short-term",
        "others financial assets - short-term",
    ], ["non-current"], priority=5),
    "Assets Held for Sale": PatternDef("BalanceSheet", [
        "assets held for sale",
        "non-current assets held for sale",
        "fixed assets held for sale",
        "assets classified as held for sale",                 # Capitaline INDAS label
        "assets classified as disposal group / discontinued operations",
        "assets held for disposal",
    ], priority=5),
    "Property Plant Equipment": PatternDef("BalanceSheet", [
        "property, plant and equipment",
        "property plant and equipment",
        "ppe",
        "net block",
        "net property, plant and equipment",     # Capitaline: "Net Property, plant and equipment"
        "net property plant and equipment",
        "tangible assets",
        "tangible assets net",
    ], ["purchase of property", "gross property", "total accumulated", "total depreciation", "total impairment"], priority=7),
    "Goodwill": PatternDef("BalanceSheet", ["goodwill"], ["goodwill impairment"], priority=6),
    "Intangible Assets": PatternDef("BalanceSheet", ["intangible assets"], ["under development"], priority=6),
    "Right of Use Assets": PatternDef("BalanceSheet", [
        "right of use assets",
        "right-of-use assets",
        "rou assets",
        "net value of rights use assets",        # Capitaline: "Net Value of Rights Use Assets"
        "total cost rights use assets",
        "other rights-use-assets",
        "rou mining properties",
    ], priority=5),
    "Capital Work in Progress": PatternDef("BalanceSheet", [
        "capital work in progress",
        "cwip",
        "capital work-in-progress",
        "gross capital work in progress",
        "net capital work in progress",
        "other capital work in progress",
    ], priority=5),
    "Fixed Assets": PatternDef("BalanceSheet", ["fixed assets", "total fixed assets"], ["purchase of fixed", "sale of fixed", "held for sale"], priority=6),
    "Investment Property": PatternDef("BalanceSheet", ["investment properties", "investment property"], priority=5),
    "Deferred Tax Assets": PatternDef("BalanceSheet", [
        "deferred tax assets",
        "deferred tax asset",
        "deferred tax assets (net)",
        "deferred tax assets (net)",
        "net deferred tax assets",               # Capitaline: "Net Deferred Tax Assets"
    ], ["liabilities"], priority=5),
    "Other Non-Current Assets": PatternDef("BalanceSheet", ["other non-current assets"], ["total"], priority=4),

    # ── Balance Sheet – Liabilities ─────────────────────────────────────────
    "Total Liabilities": PatternDef("BalanceSheet", [
        "total liabilities",
        "total non-current liabilities and current liabilities",
    ], [
        "equity",                # prevent "Total Equity and Liabilities" from matching
        "assets",                # prevent "Total Assets" from matching
        "reported",              # prevent "Total Reported Non-current Liabilities" from matching this target
    ], priority=10),
    "Current Liabilities": PatternDef("BalanceSheet", ["current liabilities", "total current liabilities"], ["non-current", "non current"], priority=9),
    "Non-Current Liabilities": PatternDef("BalanceSheet", ["non-current liabilities", "non current liabilities", "total non-current liabilities", "total reported non-current liabilities"], priority=9),
    "Accounts Payable": PatternDef("BalanceSheet", ["trade payables", "sundry creditors", "accounts payable", "creditors"], priority=7),
    "Short-term Debt": PatternDef("BalanceSheet", ["short term borrowings", "current borrowings", "short-term borrowings"], ["long term", "non-current"], priority=8),
    "Long-term Debt": PatternDef("BalanceSheet", ["long term borrowings", "non-current borrowings", "long-term borrowings", "term loans", "secured loans", "debentures"], ["short term", "current"], priority=8),
    "Lease Liabilities": PatternDef("BalanceSheet", ["lease liabilities", "lease liability", "finance lease obligations"], priority=5),
    "Other Current Liabilities": PatternDef("BalanceSheet", ["other current liabilities"], ["total", "non-current"], priority=5),
    "Current Tax Liabilities": PatternDef("BalanceSheet", [
        "current tax liabilities",
        "current tax liability",
        "income tax payable",
        "current tax payable",
        "income tax liability",                  # Capitaline: "Income Tax Liability"
        "current tax liabilities short-term",    # Capitaline: "Current Tax Liabilities - Short-term"
        "current tax liabilities - short-term",
        "current tax assets short-term",         # Sometimes shows net position
    ], ["deferred", "non current", "long-term", "long term"], priority=5),
    "Other Short-term Liabilities": PatternDef("BalanceSheet", [
        "other short term liabilities",
        "other short-term liabilities",
        # Capitaline INDAS: "Others Financial Liabilities - Short-term" (normalizes to exact below)
        # Previously unmapped because this label scored 0.857 for Minority Interest via the
        # "nci" pattern matching "finan(nci)al" as a false substring — the new exact patterns
        # score 0.98 and correctly win over that spurious 0.857 match.
        "others financial liabilities short term",
        "others financial liabilities short-term",
        "others financial liabilities - short-term",
    ], ["non-current", "non current"], priority=5),
    "Liabilities Held for Sale": PatternDef("BalanceSheet", [
        "liabilities held for sale",
        "liability directly associated with assets held for sale",
        "liabilities directly associated with assets classified as held for sale",  # Capitaline
    ], priority=5),
    "Other Non-Current Liabilities": PatternDef("BalanceSheet", ["other non-current liabilities"], ["total"], priority=5),
    "Provisions": PatternDef("BalanceSheet", ["provisions", "long-term provisions", "short-term provisions"], ["provision for tax"], priority=5),
    "Deferred Tax Liabilities": PatternDef("BalanceSheet", ["deferred tax liabilities", "deferred tax liability", "deferred tax liabilities (net)"], ["assets"], priority=5),

    # ── Balance Sheet – Equity ──────────────────────────────────────────────
    "Total Equity": PatternDef("BalanceSheet", [
        "total equity",
        "total stockholders' equity",
        "total stockholders equity",
        "shareholders funds",
        "shareholders' funds",
        "total shareholders funds",
        "net worth",
        "total equity and minority interest",    # pre-INDAS format
    ], ["total equity and liabilities"], priority=10),
    "Share Capital": PatternDef("BalanceSheet", [
        "share capital",
        "equity share capital",
        "paid-up capital",
        "paid up capital",
        "paid up share capital",
        "equity share capital paid up",
    ], ["number of", "application money"], priority=8),
    "Retained Earnings": PatternDef("BalanceSheet", ["reserves and surplus", "retained earnings", "other equity", "reserves & surplus"], priority=7),
    "Minority Interest": PatternDef("BalanceSheet", [
        "minority interest",
        "non-controlling interest",
        "non controlling interest",
        "non-controlling interests",         # Capitaline INDAS: plural
        "non controlling interests",
        "nci",
    ], [
        # "nci" is a 3-char substring of "finan(nci)al", causing false 0.857 matches on sources
        # like "Others Financial Liabilities - Short-term" and "Others Financial Assets - Short-term".
        # These excludes block any source that actually describes financial assets or liabilities.
        "financial liabilities",
        "financial assets",
    ], priority=5),
    "Contingent Liabilities": PatternDef("BalanceSheet", [
        "contingent liabilities",
        "contingent liabilities and commitments",
        "contingent liabilities and commitments (to the extent not provided for)",  # exact Capitaline label
        "contingent liabilities and commitments to the extent not provided for",
    ], priority=4),

    # ── Profit & Loss – Income ──────────────────────────────────────────────
    # Net revenue (excludes excise duty) must win over gross when both present.
    # Capitaline exports both "Revenue From Operations" (gross) and
    # "Revenue From Operations(Net)". The latter is canonical for analysis.
    # We keep both patterns here but rely on exclude to block the gross line
    # when "(net)" variant is matched first via the priority scoring.
    "Revenue": PatternDef("ProfitLoss", [
        "revenue from operations net",       # Capitaline: highest-priority exact
        "revenue from operations(net)",       # bracketed variant
        "revenue from operations (net)",      # spaced variant
        "net revenue from operations",
        "net sales",
        "sales turnover",
        "total revenue from operations",
        "revenue from operations",            # gross fallback — only if no net line
    ], ["total revenue", "less excise", "excise duty"], priority=10),
    "Total Revenue": PatternDef("ProfitLoss", ["total revenue", "total income"], priority=9),
    "Other Income": PatternDef("ProfitLoss", ["other income", "other operating income", "non-operating income"], ["total income", "operating income"], priority=6),
    "Exceptional Items": PatternDef("ProfitLoss", [
        "exceptional items",
        "extraordinary items",
        "exceptional and extraordinary items",
        "exceptional items before tax",
    ], [
        "before exceptional",            # "Profit Before Exceptional Items and Tax" must NOT match
        "profit before",                 # any "Profit Before X" label should not map here
        "after exceptional",             # "Profit After Exceptional Items" should not match either
    ], priority=6),

    # ── Profit & Loss – Expenses ────────────────────────────────────────────
    "Cost of Goods Sold": PatternDef("ProfitLoss", [
        "cost of goods sold",
        "cost of materials consumed",        # plural (standard)
        "cost of material consumed",         # singular (Capitaline INDAS format)
        "raw material consumed",
        "raw materials consumed",
        "total raw material consumed",
        "purchases of stock-in-trade",
        "purchases of stock in trade",
        "purchases of raw material",         # Capitaline: "Purchases of Raw Material"
        "purchases of raw materials",
        "cost of revenue",
        "direct material cost",
        "material cost",
        "manufacturing direct expenses",
        "total manufacturing direct expenses",
        "manufacturing / direct expenses",   # Capitaline P&L sub-header
        "total manufacturing / direct expenses",
        "consumption of stores and spare parts",
        "power oil fuel",
        "direct labour charges",
        "job work processing charges",
        "job work / processing charges",     # Capitaline slash variant
        "jobwork charges",                   # Capitaline no-space variant
        # Capitaline aggregate & sectoral variants
        "add purchase & direct cost",        # Capitaline older format aggregate line
        "add purchase and direct cost",
        "other direct costs",                # generic label
        "otherdirectcosts",                  # Capitaline CamelCase run-together
        "total other material consumed",     # packing/other consumable totals
        "internally manufactured intermediates or components consumed",
        "cost of land plots development and construction",   # real-estate sector
        "cost of land, plots, development and construction",
        "cost of service maintenance and power generation",  # utility/infra sector
        "cost of cinema operations",                         # media/entertainment
        "cost of software package",                          # IT/software
        "direct expense on purchase adjustment",
        "processing charges",                # contract manufacturing
        "labour charges",
        "manufactured components",
        "finished products",                 # some exporters report finished-goods cost here
    ], priority=8),
    "Employee Expenses": PatternDef("ProfitLoss", [
        "employee benefit expense",
        "employee benefits expense",         # plural 'benefits'
        "employee benefits",
        "employee expenses",
        "employee benefits salaries other staff cost",
        "employee benefits / salaries & other staff cost",   # Capitaline slash variant
        "employee benefits / salaries and other staff cost",
        "staff costs",
        "personnel expenses",
        "wages and salaries",
        "salaries and incentives",
        "salaries wages and bonus",
        "staff welfare expenses",
        "retirement benefits expense",
        "other employee benefit",
        "staff expenses",
        # Capitaline sub-line contributions that appear as granular rows
        "contributions to provident and other fund",
        "contributions to superannuation scheme",
        "gratuity fund contributions",
        "compensated absences",
        "social security and other benefit plans for overseas employees",
        # Director / managerial remuneration (Capitaline separate rows)
        "directors remuneration",
        "other director's remuneration",
        "directors fees",
        "directors commission",
        # VRS / ESOP / manpower
        "vrs compensation",
        "vrs adjustment",
        "payment towards vrs",               # CashFlow label that sometimes mirrors P&L
        "share-based payments",
        "share based payments",
        "expense on employee stock option scheme",
        "expense on employee stock option scheme esop and employee stock purchase plan espp",
        "manpower hire charges",
        "employee recruitment and training expenses",
    ], priority=7),
    "Depreciation": PatternDef("ProfitLoss", [
        "depreciation and amortisation",         # standard INDAS label
        "depreciation and amortization",
        "depreciation & amortisation",
        "depreciation & amortization",
        "depreciation",
        "amortization",
        "d&a",
        # Capitaline granular sub-lines that roll up to total D&A
        "depreciation for the current year",
        "depreciation on tangible assets",
        "depreciation on investment properties",
        "amortisation of intangible assets",
        "amortization of intangible assets",
        "amortisation of investment property",
        "amortization for the current year",
        "amortisation for the current year",
        "depletion for the current year",
        "impairment for the current year",        # Capitaline IND-AS impairment line
        "impairment of fixed assets",
        "impairment of tangible assets",
        "impairment of goodwill",
        "impairment of intangible assets",
        "impairment of other assets",
    ], ["accumulated", "prior year", "capitalised", "capitalized"], priority=7),
    "Interest Expense": PatternDef("ProfitLoss", [
        "finance costs",
        "finance cost",                          # singular — Capitaline INDAS
        "interest expense",
        "interest charges",
        "borrowing costs",
        "financial expenses",
        "total interest expenses",
        "interest on bank borrowings",
        "interest on term fixed loans",
        "interest on term / fixed loans",        # slash variant
        "interest on working capital loans",
        "interest and finance charges on financial liabilities",
        "other interest expenses",
        "bank charges",
        "bill discounting charges",
        # Additional Capitaline granular interest sub-lines
        "financial charges on financial liabilities at amortised cost",
        "financial charges on financial liabilities at amortized cost",
        "interest on bonds and debentures",
        "interest on commercial paper",
        "interest on deposits",
        "interest on external commercial borrowings",
        "interest on finance lease",
        "interest on foreign currency loans",
        "interest on other borrowings",
        "interest on other loans",
        "interest - related parties",
        "other borrowing costs",
        "amotisation of borrowing costs",        # Capitaline typo — "Amotisation" instead of Amortisation
        "amortisation of borrowing costs",
        "amortization of borrowing costs",
        "unwinding expenses",                    # unwinding of discount on provisions — finance cost
        "redemption premium",                    # premium on debenture redemption
        "guarantee commission",
        "guarantee expenses",
    ], priority=8),
    "Total Expenses": PatternDef("ProfitLoss", ["total expenses", "total expenditure", "total costs and expenses"], priority=9),
    "Other Expenses": PatternDef("ProfitLoss", ["other expenses", "other operating expenses", "miscellaneous expenses"], ["total", "non-operating"], priority=5),
    "Changes in Inventory": PatternDef("ProfitLoss", [
        "changes in inventories",
        "change in inventories",
        "(increase)/decrease in inventories",
        "increase decrease in inventories",
        "changes in inventories of finished goods work-in-progress and stock-in-trade",  # full Capitaline label
        "changes in inventories of finished goods, work-in-progress and stock-in-trade",
        "changes in inventories of finished goods work in progress and stock in trade",
    ], priority=5),
    "Manufacturing Expenses": PatternDef("ProfitLoss", ["manufacturing expenses", "factory overhead", "production overhead"], priority=4),
    "Selling Expenses": PatternDef("ProfitLoss", [
        "selling expenses",
        "selling and distribution",
        "marketing expenses",
        # Capitaline: "Total Selling & Administrative Expenses" — '&' normalizes away, giving exact match below
        "total selling administrative expenses",
        # Capitaline: "Selling and Administration Expenses" (Capitaline uses "admin" variant)
        "selling and administration expenses",
        "selling administration expenses",
        # Capitaline: "Total Selling and Distribution Expenses"
        "total selling and distribution expenses",
        "total selling distribution expenses",
    ], priority=4),

    # ── Profit & Loss – Profit ──────────────────────────────────────────────
    "Gross Profit": PatternDef("ProfitLoss", ["gross profit", "gross margin"], priority=7),
    "Operating Income": PatternDef("ProfitLoss", ["operating profit", "operating income", "profit from operations", "ebit"], ["before", "interest", "tax", "d&a"], priority=8),
    "Income Before Tax": PatternDef("ProfitLoss", [
        "profit before tax",                     # Capitaline: canonical PBT (AFTER exceptional items) — highest priority
        "income before tax",
        "earnings before tax",
        "pbt",
        "profit before taxation",
        # Note: "profit before exceptional items and tax" (PBIT) maps here ONLY if "profit before tax" is absent.
        # The analyzer strips exceptional items from PBT itself; mapping PBIT here causes double-stripping.
        "profit before exceptional items and tax",
        "profit before extraordinary items and tax",
    ], priority=9),
    # Tax Expense: must map to the TOTAL tax line, not sub-items.
    # "Current Tax" and "Deferred Tax" are components; "Tax Expenses" / "Tax Expense" is the total.
    # Exclude sub-item labels to prevent "Current Tax" from taking the slot.
    "Tax Expense": PatternDef("ProfitLoss", [
        "tax expense",
        "tax expenses",
        "income tax expense",
        "provision for tax",
        "total tax expense",
        "income tax",
        "tax on income",
        "other tax adjustments",
        "fringe benefits tax",
    ], [
        "deferred tax assets", "deferred tax liabilities", "deferred tax (credit)",
        "current tax - mat", "current tax mat",      # MAT sub-items
        "current tax only",                          # prevents bare "current tax" matching
    ], priority=8),
    "Net Income": PatternDef("ProfitLoss", [
        "profit after tax",
        "net income",
        "profit for the year",
        "profit for the period",
        "net profit",
        "pat",
        "profit attributable to shareholders",
        "profit attributable to equity holders",
        "profit attributable to ordinary shareholders",          # Capitaline variant
        "profit after pre-acquisition profit",
        "profit/(loss) for the period from continuing operations",  # Capitaline INDAS continuing ops
        "profit loss for the period from continuing operations",
    ], ["before tax", "minority", "non-controlling", "discontinued", "extraordinary"], priority=10),
    "Minority Earnings": PatternDef("ProfitLoss", [
        "profit attributable to minority",
        "profit attributable to non-controlling",
        "minority interest in profit",
        "non-controlling interests",             # Capitaline INDAS P&L allocation line
        "non controlling interests",
    ], priority=4),
    "EPS Basic": PatternDef("ProfitLoss", [
        "basic eps",
        "earnings per share (basic)",
        "basic earnings per share",
        "earnings per share basic",
        "earning per share basic",           # Capitaline: singular "Earning"
        "earning per share - basic",
        "eps basic",
    ], priority=5),
    "EPS Diluted": PatternDef("ProfitLoss", [
        "diluted eps",
        "earnings per share (diluted)",
        "diluted earnings per share",
        "earnings per share diluted",
        "earning per share diluted",         # Capitaline: singular "Earning"
        "earning per share - diluted",
        "eps diluted",
    ], priority=5),
    "Dividend": PatternDef("ProfitLoss", ["dividend paid", "dividend per share", "dividends"], ["dividend income", "dividend received"], priority=5),

    # ── Cash Flow Statement ──────────────────────────────────────────────────
    "Operating Cash Flow": PatternDef("CashFlow", [
        "net cash from operating activities",
        "cash flow from operating activities",
        "cash generated from operations",
        "cash generated from used in operations",
        "cash generated from/(used in) operations",       # Capitaline slash variant
        "cash inflow from operating activities",
        "net cash generated from operations",
        "net cash used in operating activities",           # loss-making firms
        "net cash from operations",
        "cash flows from operating activities",
    ], priority=10),
    # Capital Expenditure: Capitaline has two relevant CF lines:
    #   "Capital Expenditure"       — the total capex line (correct)
    #   "Purchased of Fixed Assets" — PPE component only (sub-total)
    # "Capital Expenditure" must win. Exact match scores 0.98 for it;
    # "Purchased of Fixed Assets" also scores 0.98 but appears later in the file.
    # We raise "capital expenditure" to the top of the list to guarantee priority.
    # Capital Expenditure: Capitaline has multiple relevant CF lines:
    #   "Capital Expenditure"        — the total capex line (correct, wins by exact-match)
    #   "Purchased of Fixed Assets"  — PPE component (sub-total, fallback)
    #   "Purchase of Fixed Assets"   — clean variant of above
    #   "capital WIP"                — capital work-in-progress additions
    # "Capital Expenditure" must win; others are fallbacks used when capex row is zero.
    "Capital Expenditure": PatternDef("CashFlow", [
        "capital expenditure",               # Capitaline: total capex line — highest priority
        "purchase of property plant and equipment",
        "purchase of property, plant and equipment",
        "capex",
        "purchase of fixed assets",
        "acquisition of property plant and equipment",
        "acquisition of property, plant and equipment",
        "purchase of tangible assets",
        "payment for property plant and equipment",
        "capital expenditure capital wip",
        "purchased of fixed assets",         # Capitaline sub-item — fallback
        "purchased of fixed asset",
        "capital wip",                       # Capitaline CashFlow: "capital WIP" additions
        "capital work in progress",          # CashFlow sub-line for CWIP spend
        "additions to fixed assets",
        "additions to property plant and equipment",
    ], ["sale of", "proceeds from sale", "disposal"], priority=9),
    "Investing Cash Flow": PatternDef("CashFlow", ["net cash from investing activities", "cash flow from investing activities", "net cash used in investing activities"], priority=8),
    "Financing Cash Flow": PatternDef("CashFlow", ["net cash from financing activities", "cash flow from financing activities", "net cash used in financing activities"], priority=8),
    "Free Cash Flow": PatternDef("CashFlow", ["free cash flow", "fcf"], priority=6),
    "Net Change in Cash": PatternDef("CashFlow", [
        "net increase in cash",
        "net decrease in cash",
        "net inc/(dec) in cash",
        "net inc dec in cash and cash equivalent",
        "net inc/(dec) in cash and cash equivalent",     # Capitaline slash variant
        "net change in cash and cash equivalents",
        "net increase/(decrease) in cash and cash equivalents",
        "net increase decrease in cash and cash equivalents",
        "net increase in cash and cash equivalents",
        "net decrease in cash and cash equivalents",
    ], priority=7),
    "Cash Beginning": PatternDef("CashFlow", ["cash at beginning", "cash and cash equivalents at beginning", "opening cash", "cash at the beginning of the year", "cash and cash equivalents at beginning of the year"], priority=6),
    "Cash Ending": PatternDef("CashFlow", ["cash at end", "cash and cash equivalents at end", "closing cash", "cash at the end of the year", "cash and cash equivalents at end of the year", "cash and cash equivalents at end of the period"], priority=6),
    "Dividends Paid": PatternDef("CashFlow", [
        "dividends paid",
        "dividend paid to shareholders",
        "dividend paid (equity)",
        "dividend paid",                         # Capitaline: bare "Dividend Paid"
        "preference dividend paid",
        "preference dividend including corporate tax",
    ], priority=5),
    "Debt Repayment": PatternDef("CashFlow", [
        "repayment of borrowings",
        "repayment of long term borrowings",
        "repayment of term loans",
        "of the long tem borrowings",            # Capitaline truncated label (typo "Tem")
        "of the long term borrowings",
        "of the short term borrowings",
        "of the short tem borrowings",           # Capitaline typo variant
        "of financial liabilities",              # Capitaline: "Of financial Liabilities"
        "on redemption of debenture",            # Capitaline: debenture redemption CF line
        "repayment of debentures",
        "repayment of borrowings long term",
    ], priority=5),
    "Proceeds from Borrowing": PatternDef("CashFlow", [
        "proceeds from borrowings",
        "proceeds from long term borrowings",
        "loans raised",
        "proceeds from issue of shares incl share premium",  # equity is also "proceeds" in CF
        "proceed from bank borrowings",          # Capitaline: "Proceed from Bank Borrowings"
        "proceed from 0ther long term borrowings",  # Capitaline typo: "0ther" not "Other"
        "proceed from other long term borrowings",
        "proceed from short tem borrowings",     # Capitaline typo: "Tem" not "Term"
        "proceed from short term borrowings",
        "proceed from issue of debentures",      # Capitaline: debenture proceeds
        "proceed from deposits",                 # deposit-backed borrowings
        "change in borrowing",                   # net borrowing change line
        "loans from a corporate body",
    ], priority=5),
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


def _normalize_text(s: str) -> str:
    """Normalize labels for robust matching across punctuation/spacing variants."""
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


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
    clean = _normalize_text(source.split("::")[-1])
    results: List[MatchResult] = []

    for target, defn in METRIC_DEFS.items():
        # Statement gating
        if source_stmt and source_stmt not in ("Financial",) and defn.statement != source_stmt:
            continue

        # Exclude patterns
        if any(_normalize_text(ep) in clean for ep in defn.exclude_patterns):
            continue

        best_score = 0.0
        for pattern in defn.patterns:
            pat = _normalize_text(pattern)
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

    # Sort by confidence desc, then priority desc, then prefer canonical sources over sub-items/variants.
    # Each tiebreaker adds a tiny bonus (0.001–0.003) to the confidence of the preferred source
    # so that when two sources both score 0.980 for the same target, the right one wins.
    def _sort_key(item):
        source, target, conf, pri = item
        src_clean = _normalize_text(source.split("::")[-1])

        # TB-1: Net revenue preferred over gross (Capitaline exports both "Revenue From Operations"
        #        and "Revenue From Operations(Net)"; the latter is canonical for analysis).
        net_bonus = 0.001 if "net" in src_clean and target == "Revenue" else 0.0

        # TB-2: "Capital Expenditure" exact label preferred over PPE purchase sub-lines.
        #        When the header row is zero, _get_capex_fallback() in analyzer.py takes over.
        capex_bonus = 0.001 if src_clean == "capital expenditure" and target == "Capital Expenditure" else 0.0

        # TB-3: Total tax label preferred over sub-items (Current Tax, Deferred Tax)
        #        for Tax Expense target. Prevents a sub-item from locking the total slot.
        total_tax_bonus = 0.001 if target == "Tax Expense" and any(
            p in src_clean for p in ["tax expense", "tax expenses", "provision for tax", "income tax expense"]
        ) else 0.0

        # TB-4: Exact "total equity" wins over "total stockholders equity" / other variants.
        equity_bonus = 0.002 if src_clean == "total equity" and target == "Total Equity" else 0.0

        # TB-5: Exact "total assets" wins over "total equity and liabilities" (both score 0.98).
        total_assets_bonus = 0.002 if src_clean == "total assets" and target == "Total Assets" else 0.0

        # TB-6: INVENTORY — "Inventories" / "Total Inventory" (the total lines) must win over
        #        "Raw Materials and Components" (a sub-item that often has value=0 in Capitaline).
        #        Without this, the greedy mapper picks the sub-item first (CSV row order), leaving
        #        the real total (e.g. ₹454.99 Cr) unmapped and breaking every inventory-based ratio.
        _inv_totals = frozenset({"inventories", "total inventory", "total inventories"})
        inventory_bonus = 0.003 if target == "Inventory" and src_clean in _inv_totals else 0.0

        # TB-7: INCOME BEFORE TAX — "Profit Before Tax" (post-exceptional PBT) MUST WIN over
        #        "Profit Before Exceptional Items and Tax" (PBIT, pre-exceptional).
        #        The PN framework in analyzer.py already strips exceptional items from PBT:
        #            recurring_pbt = pbt - exceptional_items
        #        If PBIT is mapped instead, exceptional items are double-subtracted, producing
        #        a wrong (too-low) recurring PBT, NOPAT, RNOA, and EBIT. E.g. in a year where
        #        exceptional items = 100: recurring_pbt = 269 - 100 = 169 (wrong),
        #        vs correct: 369 - 100 = 269. Map "Profit Before Tax" to fix this.
        pbt_bonus = 0.003 if target == "Income Before Tax" and src_clean == "profit before tax" else 0.0

        # TB-8: Primary COGS labels win over sub-items / sub-totals of raw material components.
        _cogs_primary = frozenset({
            "cost of goods sold", "cost of material consumed", "cost of materials consumed",
            "cost of revenue", "total cost of goods sold",
        })
        cogs_bonus = 0.002 if target == "Cost of Goods Sold" and src_clean in _cogs_primary else 0.0

        # TB-9: BANK BALANCES — "Bank Balances Other Than Cash and Cash Equivalents" must win over
        #        "Balances with Bank / Margin Money Balances" (a zero-value catch-all row in Capitaline
        #        that appears earlier in the CSV and would otherwise grab the slot).
        bank_bonus = 0.003 if target == "Bank Balances" and "bank balances other than" in src_clean else 0.0

        # TB-10: CURRENT TAX LIABILITIES — "Current Tax Liabilities - Short-term" must win over
        #         "Income Tax Liability" (a long-term/deferred line that is zero in many companies
        #         but appears earlier in the CSV at the same 0.98 confidence).
        curtax_bonus = 0.003 if target == "Current Tax Liabilities" and src_clean == "current tax liabilities short term" else 0.0

        # TB-11: LONG-TERM INVESTMENTS — "Investments - Long-term" must win over
        #         "Investments in Subsidiaries, Associates and Joint Venture" (a sub-item row that
        #         is zero for standalone companies like VST but appears earlier in the CSV).
        _ltinv_specifics = frozenset({"investments long term", "investments - long term", "total investments"})
        ltinv_bonus = 0.003 if target == "Long-term Investments" and src_clean in _ltinv_specifics else 0.0

        # TB-12: SELLING EXPENSES — "Selling and Administration Expenses" / "Total Selling &
        #         Administrative Expenses" (non-zero aggregate totals) must win over "Marketing
        #         Expenses" (a sub-line that Capitaline often exports as zero).
        _selling_totals = frozenset({
            "selling and administration expenses",
            "total selling administrative expenses",   # "Total Selling & Administrative Expenses" normalized
            "total selling and distribution expenses",
            "total selling distribution expenses",
        })
        selling_bonus = 0.003 if target == "Selling Expenses" and src_clean in _selling_totals else 0.0

        return (
            conf + net_bonus + capex_bonus + total_tax_bonus + equity_bonus
            + total_assets_bonus + inventory_bonus + pbt_bonus + cogs_bonus
            + bank_bonus + curtax_bonus + ltinv_bonus + selling_bonus,
            pri,
        )

    scored.sort(key=_sort_key, reverse=True)

    for source, target, conf, _ in scored:
        if source in used_sources or target in used_targets:
            continue

        # ── Single-word / generic label guard ────────────────────────────────
        # Very short Capitaline labels like "Total", "Others", "Quoted", "Unquoted"
        # match important targets via substring rules at confidence 0.75–0.79.
        # They are too semantically vague to map reliably and would map with wrong
        # zero values (e.g. "Total" → Total Liabilities = 0). Require conf ≥ 0.95
        # for any source whose cleaned label is a single token.
        # Exception: standard abbreviations (eps, pat, fcf, pbt) score 0.98 (exact match)
        # and are unaffected.
        src_label = _normalize_text(source.split("::")[-1])
        src_token_count = len(src_label.split()) if src_label else 0
        if src_token_count <= 1 and conf < 0.95:
            continue  # too generic — skip to avoid wrong zero-value mappings

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
