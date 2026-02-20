"""
fin_platform/parser.py
=======================
Multi-format financial data parser. Handles:
  - Excel (.xlsx, .xls) – multi-sheet with statement detection
  - CSV (.csv)
  - HTML tables (Capitaline export format)

Year detection supports Indian FY formats (FY24, Mar 2024, 2024-25, etc.)
"""
from __future__ import annotations
import re
import io
import zipfile
from typing import Dict, List, Optional, Tuple, Any

import pandas as pd
from bs4 import BeautifulSoup

from .types import FinancialData, MergeDebugInfo


# ─── Year Detection ────────────────────────────────────────────────────────────

def extract_year(col_name: str) -> Optional[str]:
    """
    Parse column header → internal year key (YYYYMM format).
    Supports: YYYYMM, FY2024, Mar 2024, 2024-25, plain YYYY.
    """
    s = str(col_name).strip()

    # Already YYYYMM
    m = re.match(r'^(\d{4})(\d{2})$', s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1990 <= y <= 2099 and 1 <= mo <= 12:
            return s

    # FY2024 or FY 2024
    m = re.search(r'FY\s*(\d{4})', s, re.IGNORECASE)
    if m:
        y = int(m.group(1))
        if 1990 <= y <= 2099:
            return f"{y}03"

    # FY24 / FY 24
    m = re.search(r'FY\s*(\d{2})(?!\d)', s, re.IGNORECASE)
    if m:
        y = 2000 + int(m.group(1))
        if 1990 <= y <= 2099:
            return f"{y}03"

    # Mar 2024 / Mar-24 / Mar'24
    m = re.search(r"Mar(?:ch)?['\-\s]?(\d{2,4})", s, re.IGNORECASE)
    if m:
        yr_str = m.group(1)
        yr = int(yr_str) if len(yr_str) == 4 else 2000 + int(yr_str)
        if 1990 <= yr <= 2099:
            return f"{yr}03"

    # 2024-25 or 2024/25
    m = re.search(r'(\d{4})\s*[-/]\s*(\d{2,4})', s)
    if m:
        y = int(m.group(1))
        if 1990 <= y <= 2099:
            return f"{y}03"

    # Plain year
    m = re.search(r'(20\d{2}|19\d{2})', s)
    if m:
        y = int(m.group(1))
        if 1990 <= y <= 2099:
            return f"{y}03"

    return None


# ─── Numeric Normalisation ────────────────────────────────────────────────────

def to_numeric(val: Any) -> Optional[float]:
    """Convert diverse string formats to float, handling Indian notations."""
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        import math
        return None if math.isnan(val) else float(val)
    s = str(val)
    # Parenthetical negatives: (1234) → -1234
    if s.startswith('(') and s.endswith(')'):
        s = '-' + s[1:-1]
    # Strip currency & separators
    s = (s.replace(',', '').replace('₹', '').replace('$', '')
         .replace('Rs.', '').replace('Rs', '').replace('\u20b9', '')
         .replace('CR', '').replace('Cr', '').replace('crore', '')
         .strip())
    if s in ('', '-', '--', 'N/A', 'NA', 'n/a', 'nan', 'None', ''):
        return None
    if s.lower() == 'nil':
        return 0.0
    try:
        return float(s)
    except ValueError:
        return None


# ─── Statement Classification ──────────────────────────────────────────────────

def classify_metric(text: str) -> str:
    """Classify a raw metric row into statement type."""
    low = text.lower()
    cf_kw = ['cash flow', 'operating activities', 'investing activities',
             'financing activities', 'capex', 'capital expenditure',
             'net cash', 'free cash']
    pl_kw = ['revenue', 'sales', 'income', 'profit', 'loss', 'expense',
             'cost', 'ebit', 'ebitda', 'tax', 'interest', 'depreciation',
             'dividend', 'earning', 'margin', 'turnover']
    bs_kw = ['asset', 'liability', 'equity', 'capital', 'reserve',
             'receivable', 'payable', 'inventory', 'inventories', 'borrowing', 'debt',
             'investment', 'property', 'goodwill', 'cash', 'bank',
             'provision', 'intangible', 'net worth']

    cf_score = sum(3 for kw in cf_kw if kw in low)
    pl_score = sum(1 for kw in pl_kw if kw in low)
    bs_score = sum(1 for kw in bs_kw if kw in low)

    if cf_score > pl_score and cf_score > bs_score:
        return 'CashFlow'
    if bs_score > pl_score:
        return 'BalanceSheet'
    if pl_score > 0:
        return 'ProfitLoss'
    return 'Financial'


def classify_sheet(sheet_name: str) -> str:
    s = sheet_name.lower()
    if any(k in s for k in ['cash', 'flow', 'cf']):
        return 'CashFlow'
    if any(k in s for k in ['profit', 'loss', 'p&l', 'pl', 'income']):
        return 'ProfitLoss'
    if any(k in s for k in ['balance', 'bs', 'position', 'sources', 'funds']):
        return 'BalanceSheet'
    return 'Financial'


def normalize_metric_name(name: str) -> str:
    """Strip leading numbering/bullets, normalize whitespace."""
    name = re.sub(r'^[A-Z]\.|^[0-9]+\.?\s*', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[_:]+', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


# ─── Single-Sheet Parser ──────────────────────────────────────────────────────

def _parse_sheet_df(df: pd.DataFrame, stmt: str) -> FinancialData:
    """Parse a single DataFrame (from one Excel sheet or CSV) into FinancialData."""
    data: FinancialData = {}

    # Find header row with most year columns
    best_row_idx = 0
    best_year_cols: List[Tuple[int, str]] = []

    for i in range(min(20, len(df))):
        year_cols = []
        for j, col in enumerate(df.iloc[i]):
            yr = extract_year(str(col))
            if yr:
                year_cols.append((j, yr))
        if len(year_cols) > len(best_year_cols):
            best_year_cols = year_cols
            best_row_idx = i

    if len(best_year_cols) < 1:
        # Try column headers as years
        year_cols = []
        for j, col in enumerate(df.columns):
            yr = extract_year(str(col))
            if yr:
                year_cols.append((j, yr))
        if year_cols:
            best_year_cols = year_cols
            best_row_idx = -1  # use header
    
    if not best_year_cols:
        return data

    # Metric column = first non-year column
    metric_col = 0
    if best_row_idx >= 0:
        for j in range(min(5, df.shape[1])):
            if not extract_year(str(df.iloc[best_row_idx, j])):
                metric_col = j
                break

    # Parse data rows
    start = best_row_idx + 1 if best_row_idx >= 0 else 0
    for i in range(start, len(df)):
        row = df.iloc[i]
        if best_row_idx >= 0:
            raw_name = str(row.iloc[metric_col] if metric_col < len(row) else '')
        else:
            raw_name = str(row.iloc[0]) if len(row) > 0 else ''
        
        metric_name = normalize_metric_name(raw_name)
        if not metric_name or len(metric_name) < 2 or metric_name.lower() in ('nan', 'none', ''):
            continue

        final_stmt = stmt if stmt != 'Financial' else classify_metric(metric_name)
        key = f"{final_stmt}::{metric_name}"

        values: Dict[str, float] = {}
        for col_idx, year in best_year_cols:
            cell_val = row.iloc[col_idx] if col_idx < len(row) else None
            num = to_numeric(cell_val)
            if num is not None:
                values[year] = num

        if values:
            # Don't override existing higher-priority rows
            if key not in data:
                data[key] = values
            else:
                # Merge: fill missing years
                for y, v in values.items():
                    if y not in data[key]:
                        data[key][y] = v

    return data


# ─── HTML Table Parser ────────────────────────────────────────────────────────

def _parse_html(content: bytes) -> FinancialData:
    """Parse Capitaline HTML export with multiple tables."""
    html = _decode_text(content)
    if not html:
        return {}

    soup = BeautifulSoup(html, 'lxml')
    tables = soup.find_all('table')
    data: FinancialData = {}

    for table in tables:
        rows = []
        for tr in table.find_all('tr'):
            cells = []
            for td in tr.find_all(['td', 'th']):
                colspan = int(td.get('colspan', 1))
                text = ' '.join(td.get_text().split())
                for _ in range(colspan):
                    cells.append(text)
            rows.append(cells)

        if len(rows) < 3:
            continue

        # Find header row
        best_row_idx = -1
        best_year_cols: List[Tuple[int, str]] = []
        for i, row in enumerate(rows[:15]):
            year_cols = [(j, extract_year(c)) for j, c in enumerate(row) if extract_year(c)]
            if len(year_cols) > len(best_year_cols):
                best_year_cols = year_cols  # type: ignore
                best_row_idx = i

        if best_row_idx == -1 or len(best_year_cols) < 2:
            continue

        # Detect statement from surrounding text
        stmt = 'Financial'
        for i in range(max(0, best_row_idx - 3), best_row_idx):
            line = ' '.join(rows[i]).lower()
            if 'balance sheet' in line or 'sources of funds' in line:
                stmt = 'BalanceSheet'; break
            if 'profit' in line or 'loss' in line or 'p&l' in line:
                stmt = 'ProfitLoss'; break
            if 'cash flow' in line:
                stmt = 'CashFlow'; break

        metric_col = 0
        header = rows[best_row_idx]
        for j in range(min(5, len(header))):
            if not extract_year(header[j]):
                metric_col = j; break

        for row in rows[best_row_idx + 1:]:
            if metric_col >= len(row):
                continue
            raw_name = normalize_metric_name(row[metric_col])
            if not raw_name or len(raw_name) < 2:
                continue

            final_stmt = stmt if stmt != 'Financial' else classify_metric(raw_name)
            key = f"{final_stmt}::{raw_name}"

            values: Dict[str, float] = {}
            for col_idx, year in best_year_cols:
                if col_idx >= len(row):
                    continue
                num = to_numeric(row[col_idx])
                if num is not None:
                    values[year] = num

            if values and key not in data:
                data[key] = values

    return data


def _decode_text(content: bytes) -> str:
    """Decode bytes with fallbacks for legacy exports (utf-16/latin1/etc.)."""
    for enc in ("utf-8", "utf-16", "utf-16le", "utf-16be", "latin1", "cp1252"):
        try:
            text = content.decode(enc)
            if text:
                return text
        except Exception:
            continue
    return content.decode("utf-8", errors="replace")


def _looks_like_html(content: bytes) -> bool:
    """Heuristic detection for HTML payloads saved with .xls extension."""
    head = content[:4096]
    low = head.lower().replace(b"\x00", b"")
    return any(tok in low for tok in (b"<html", b"<table", b"<!doctype html", b"<tr", b"<td"))


# ─── Main Parse Entry Point ───────────────────────────────────────────────────

def parse_file(file_bytes: bytes, filename: str) -> Tuple[FinancialData, List[str]]:
    """
    Parse uploaded file bytes into FinancialData.
    Returns (data, list_of_year_keys).
    Supports xlsx, xls, csv, htm/html.
    """
    fn_lower = filename.lower()

    if fn_lower.endswith(('.htm', '.html')):
        data = _parse_html(file_bytes)
    elif fn_lower.endswith('.xls') and _looks_like_html(file_bytes):
        # Capitaline commonly ships HTML tables with .xls extension.
        data = _parse_html(file_bytes)
    elif fn_lower.endswith('.csv'):
        try:
            df = pd.read_csv(io.BytesIO(file_bytes), header=None, dtype=str)
            stmt = classify_sheet(filename)
            data = _parse_sheet_df(df, stmt)
        except Exception:
            data = {}
    elif fn_lower.endswith(('.xlsx', '.xls')):
        data = _parse_excel(file_bytes, filename)
    else:
        # Try Excel fallback
        try:
            data = _parse_excel(file_bytes, filename)
        except Exception:
            data = {}

    # Collect years
    year_set: set = set()
    for vals in data.values():
        year_set.update(vals.keys())
    years = sorted(year_set)

    return data, years


def _parse_excel(file_bytes: bytes, filename: str) -> FinancialData:
    """Parse all sheets of an Excel file."""
    merged: FinancialData = {}
    try:
        if filename.lower().endswith('.xls') and _looks_like_html(file_bytes):
            return _parse_html(file_bytes)
        xl = pd.ExcelFile(io.BytesIO(file_bytes), engine='openpyxl' if filename.lower().endswith('.xlsx') else 'xlrd')
        for sheet_name in xl.sheet_names:
            try:
                df = xl.parse(sheet_name, header=None, dtype=str)
                stmt = classify_sheet(sheet_name)
                sheet_data = _parse_sheet_df(df, stmt)
                for key, vals in sheet_data.items():
                    if key not in merged:
                        merged[key] = vals
                    else:
                        for y, v in vals.items():
                            if y not in merged[key]:
                                merged[key][y] = v
            except Exception:
                continue
    except Exception:
        # Try CSV-like fallback
        try:
            df = pd.read_csv(io.BytesIO(file_bytes), header=None, dtype=str)
            merged = _parse_sheet_df(df, 'Financial')
        except Exception:
            pass
    return merged


def expand_uploaded_files(file_bytes: bytes, filename: str) -> List[Tuple[str, bytes]]:
    """Expand upload into parseable files, including .zip archives."""
    fn_lower = filename.lower()
    if not fn_lower.endswith(".zip"):
        return [(filename, file_bytes)]

    expanded: List[Tuple[str, bytes]] = []
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            inner_name = info.filename
            inner_lower = inner_name.lower()
            if inner_lower.endswith((".xlsx", ".xls", ".csv", ".html", ".htm")):
                expanded.append((inner_name, zf.read(info)))
    return expanded


# ─── Product Tables Parser (Finished Products / Raw Materials) ──────────────

PRODUCT_COLUMN_ALIASES = {
    "year": "year",
    "product name": "product_name",
    "product code": "product_code",
    "unit of measurement": "unit_of_measurement",
    "% of sto": "pct_of_sto",
    "capacity utilised -%": "capacity_utilised_pct",
    "capacity utilized -%": "capacity_utilised_pct",
    "installed capacity": "installed_capacity",
    "production": "production",
    "sales quantity": "sales_quantity",
    "sales": "sales",
    "sales realisation/unit -unit curr": "sales_realisation_per_unit",
    "sales realization/unit -unit curr": "sales_realisation_per_unit",
    "product quantity": "product_quantity",
    "product value": "product_value",
    "cost/unit -unit curr.": "cost_per_unit",
    "cost/unit -unit curr": "cost_per_unit",
}


def _clean_header(value: Any) -> str:
    s = str(value or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _normalize_product_columns(columns: List[Any]) -> List[str]:
    normalized: List[str] = []
    for col in columns:
        cleaned = _clean_header(col)
        normalized.append(PRODUCT_COLUMN_ALIASES.get(cleaned, cleaned.replace(" ", "_")))
    return normalized


def _find_product_header_row(df: pd.DataFrame) -> Optional[int]:
    for i in range(min(30, len(df))):
        row = [_clean_header(v) for v in df.iloc[i].tolist()]
        if "year" in row and "product name" in row:
            return i
    return None


def _materialize_product_frame(df: pd.DataFrame) -> pd.DataFrame:
    hdr_idx = _find_product_header_row(df)
    if hdr_idx is None:
        return pd.DataFrame()

    header = df.iloc[hdr_idx].tolist()
    body = df.iloc[hdr_idx + 1:].copy()
    body.columns = _normalize_product_columns(header)
    body = body.loc[:, ~body.columns.duplicated()].copy()
    body = body.dropna(axis=0, how="all")
    if body.empty:
        return pd.DataFrame()

    body.columns = [str(c) for c in body.columns]
    if "year" not in body.columns or "product_name" not in body.columns:
        return pd.DataFrame()

    body = body[body["year"].notna() & body["product_name"].notna()].copy()
    body["year"] = pd.to_numeric(body["year"], errors="coerce").astype("Int64")
    body = body[body["year"].notna()].copy()

    numeric_cols = [
        c for c in body.columns
        if c not in {"year", "product_name", "product_code", "unit_of_measurement"}
    ]
    for col in numeric_cols:
        body[col] = body[col].apply(to_numeric)

    body["product_name"] = body["product_name"].astype(str).str.strip()
    body["product_code"] = body.get("product_code", "").astype(str).str.strip()
    body["unit_of_measurement"] = body.get("unit_of_measurement", "").astype(str).str.strip()

    return body.reset_index(drop=True)


def _classify_product_table(df: pd.DataFrame, source_name: str) -> Optional[str]:
    cols = {str(c) for c in df.columns}
    low_name = source_name.lower()

    if {"pct_of_sto", "sales_quantity"}.intersection(cols) or "finished" in low_name:
        return "finished_products"
    if {"product_quantity", "product_value", "cost_per_unit"}.intersection(cols) or "raw" in low_name:
        return "raw_materials"
    return None


def parse_product_file(file_bytes: bytes, filename: str) -> Dict[str, pd.DataFrame]:
    """Parse Capitaline Products/Raw Materials tables from xls/xlsx/csv/html files."""
    frames: List[pd.DataFrame] = []
    name = filename.lower()

    try:
        if name.endswith((".html", ".htm")) or (name.endswith(".xls") and _looks_like_html(file_bytes)):
            html = _decode_text(file_bytes)
            frames = [df for df in pd.read_html(io.StringIO(html), header=None)]
        elif name.endswith((".xlsx", ".xls")):
            xl = pd.ExcelFile(io.BytesIO(file_bytes), engine="openpyxl" if name.endswith(".xlsx") else "xlrd")
            frames = [xl.parse(sheet_name, header=None, dtype=str) for sheet_name in xl.sheet_names]
        elif name.endswith(".csv"):
            frames = [pd.read_csv(io.BytesIO(file_bytes), header=None, dtype=str)]
    except Exception:
        return {"finished_products": pd.DataFrame(), "raw_materials": pd.DataFrame()}

    parsed = {"finished_products": [], "raw_materials": []}
    for frame in frames:
        product_df = _materialize_product_frame(frame)
        if product_df.empty:
            continue
        table_type = _classify_product_table(product_df, filename)
        if table_type:
            parsed[table_type].append(product_df)

    out: Dict[str, pd.DataFrame] = {}
    for k, chunks in parsed.items():
        out[k] = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
    return out


# ─── Segment Finance Parser ──────────────────────────────────────────────────

SEGMENT_SECTION_TOKENS = {
    "REVENUE", "RESULT", "OTHER INFORMATION", "OTHER INFO", "OTHERS"
}


def _parse_segment_finance_frame(df: pd.DataFrame) -> pd.DataFrame:
    raw = df.fillna("").astype(str)

    best_row = None
    best_year_cols: List[Tuple[int, str]] = []
    for i in range(min(40, len(raw))):
        row = [str(x).strip() for x in raw.iloc[i].tolist()]
        year_cols = []
        for j, c in enumerate(row):
            yr = extract_year(c)
            if yr:
                year_cols.append((j, yr))
        if len(year_cols) > len(best_year_cols):
            best_year_cols = year_cols
            best_row = i

    if best_row is None or len(best_year_cols) < 3:
        return pd.DataFrame()

    header = [str(x).strip() for x in raw.iloc[best_row].tolist()]
    non_year_cols = [j for j in range(len(header)) if j not in {idx for idx, _ in best_year_cols}]
    label_col = non_year_cols[0] if non_year_cols else 0
    segment_col = non_year_cols[1] if len(non_year_cols) > 1 else None

    records = []
    current_section = "General"
    current_metric = "Unknown"

    for i in range(best_row + 1, len(raw)):
        row = raw.iloc[i].tolist()
        label = normalize_metric_name(row[label_col] if label_col < len(row) else "")
        if not label:
            continue
        label_up = label.upper()

        year_values = {}
        numeric_count = 0
        for cidx, year in best_year_cols:
            if cidx >= len(row):
                continue
            num = to_numeric(row[cidx])
            if num is not None:
                year_values[year] = num
                numeric_count += 1

        if numeric_count == 0 and label_up in SEGMENT_SECTION_TOKENS:
            current_section = label.title()
            continue

        if label.lower() in {"detailed", "segment product", "consolidated", "segment"}:
            continue

        row_segment = ""
        if segment_col is not None and segment_col < len(row):
            row_segment = normalize_metric_name(row[segment_col])

        if numeric_count > 0:
            is_segment_like = label_up == label and any(ch.isalpha() for ch in label)
            if is_segment_like and current_metric not in {"Unknown", ""}:
                metric_name = current_metric
                segment_name = label
            else:
                metric_name = label
                segment_name = row_segment or "Total"
                current_metric = metric_name

            for y, v in year_values.items():
                records.append({
                    "year": y,
                    "section": current_section,
                    "metric": metric_name,
                    "segment": segment_name,
                    "value": v,
                })

    if not records:
        return pd.DataFrame()

    out = pd.DataFrame(records)
    out = out.drop_duplicates(subset=["year", "section", "metric", "segment"], keep="first")
    out = out.sort_values(["section", "metric", "segment", "year"]).reset_index(drop=True)
    return out


def parse_segment_finance_file(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """Parse Capitaline Segment Finance exports from html/xls/xlsx/csv (including html-in-xls)."""
    def _parse_frames_from_bytes(raw_bytes: bytes, source_name: str) -> List[pd.DataFrame]:
        source_lower = source_name.lower()
        try:
            if _looks_like_html(raw_bytes) or source_lower.endswith((".html", ".htm")):
                html = _decode_text(raw_bytes)
                return [df for df in pd.read_html(io.StringIO(html), header=None)]

            if source_lower.endswith((".xlsx", ".xls")):
                xl = pd.ExcelFile(
                    io.BytesIO(raw_bytes),
                    engine="openpyxl" if source_lower.endswith(".xlsx") else "xlrd",
                )
                return [xl.parse(sheet_name, header=None, dtype=str) for sheet_name in xl.sheet_names]

            if source_lower.endswith(".csv"):
                return [pd.read_csv(io.BytesIO(raw_bytes), header=None, dtype=str)]
        except Exception:
            return []
        return []

    frames: List[pd.DataFrame] = []
    name = filename.lower()

    if name.endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    frames.extend(_parse_frames_from_bytes(zf.read(info), info.filename))
        except Exception:
            return pd.DataFrame()
    else:
        frames = _parse_frames_from_bytes(file_bytes, filename)

    chunks = []
    for frame in frames:
        parsed = _parse_segment_finance_frame(frame)
        if not parsed.empty:
            chunks.append(parsed)

    if not chunks:
        return pd.DataFrame()

    out = pd.concat(chunks, ignore_index=True)
    out = out.drop_duplicates(subset=["year", "section", "metric", "segment"], keep="first")
    return out.sort_values(["section", "metric", "segment", "year"]).reset_index(drop=True)


# ─── Merge Multiple Files ────────────────────────────────────────────────────

def merge_financial_data(
    datasets: List[Tuple[FinancialData, str]]
) -> Tuple[FinancialData, List[str], MergeDebugInfo]:
    """
    Merge multiple parsed FinancialData dicts into one unified dataset.
    Returns (merged_data, sorted_years, debug_info).
    """
    merged: FinancialData = {}
    year_set: set = set()
    debug = MergeDebugInfo()

    for data, fname in datasets:
        debug.file_names.append(fname)
        for key, vals in data.items():
            if key not in merged:
                merged[key] = dict(vals)
            else:
                for y, v in vals.items():
                    if y not in merged[key]:
                        merged[key][y] = v
            year_set.update(vals.keys())

    years = sorted(year_set)

    # ── Balance Sheet integrity checks ───────────────────────────────────────
    def _pick(keys: List[str], year: str) -> Optional[float]:
        for k in keys:
            if merged.get(k, {}).get(year) is not None:
                return merged[k][year]
        return None

    check_years = years[-min(5, len(years)):]

    for y in check_years:
        ta = _pick(['BalanceSheet::Total Assets'], y)
        ca = _pick(['BalanceSheet::Current Assets', 'BalanceSheet::Total Current Assets'], y)
        nca = _pick(['BalanceSheet::Non-Current Assets', 'BalanceSheet::Total Reported Non-current Assets'], y)
        eq = _pick(['BalanceSheet::Total Equity', "BalanceSheet::Total Stockholders' Equity", 'BalanceSheet::Shareholders Funds'], y)
        cl = _pick(['BalanceSheet::Current Liabilities', 'BalanceSheet::Total Current Liabilities'], y)
        ncl = _pick(['BalanceSheet::Non-Current Liabilities'], y)
        tl = _pick(['BalanceSheet::Total Liabilities'], y)
        if tl is None and ta is not None and eq is not None:
            tl = ta - eq
        tel = ta  # Total Equity & Liabilities ≈ Total Assets

        assets_gap = (ca + nca - ta) if (ta is not None and ca is not None and nca is not None) else None
        liab_eq_gap = (tl + eq - ta) if (ta is not None and tl is not None and eq is not None) else None

        debug.bs_reconciliation.append({
            "year": y,
            "total_assets": ta,
            "current_assets": ca,
            "non_current_assets": nca,
            "total_equity": eq,
            "total_liabilities": tl,
            "current_liabilities": cl,
            "non_current_liabilities": ncl,
            "assets_gap": assets_gap,
            "liab_eq_gap": liab_eq_gap,
        })

        tol = max(1.0, abs(ta) * 0.01) if ta else 1.0
        if assets_gap is not None and abs(assets_gap) > tol:
            debug.integrity_checks.append(f"BS assets gap {y}: CA+NCA-TA = {assets_gap:.2f}")
        if liab_eq_gap is not None and abs(liab_eq_gap) > tol:
            debug.integrity_checks.append(f"BS L+E gap {y}: TL+EQ-TA = {liab_eq_gap:.2f}")

    return merged, years, debug
