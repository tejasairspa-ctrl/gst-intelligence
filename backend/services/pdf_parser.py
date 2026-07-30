"""
GST PDF Parser — Text-based, section-aware extraction.

AUDIT-SAFE RULE: NEVER assumes or infers values.
All missing fields are explicitly marked as None.
Uses page.extract_text() + section/label-based approach, NOT table indices.
"""
print("*** PARSER FILE ACTIVE:", __file__, "***")
import re
import logging
from typing import Any, Dict, List, Optional

import pdfplumber

logger = logging.getLogger(__name__)

# ── Type Detection ────────────────────────────────────────────────────────────

GST_TYPE_PATTERNS = {
    "GSTR-1":  [r"GSTR\s*-?\s*1\b", r"Form\s+GSTR-1", r"GSTR1"],
    "GSTR-3B": [r"GSTR\s*-?\s*3B\b", r"Form\s+GSTR-3B", r"GSTR3B"],
    "GSTR-9":  [r"GSTR\s*-?\s*9\b(?!C)", r"Form\s+GSTR-9\b(?!C)", r"Annual\s+Return"],
    "GSTR-9C": [r"GSTR\s*-?\s*9C\b", r"Form\s+GSTR-9C", r"Reconciliation\s+Statement"],
}


def detect_gst_type(text: str) -> str:
    """Return the GSTR form type detected in the text, or 'UNKNOWN'."""
    for gst_type in ["GSTR-9C", "GSTR-9", "GSTR-3B", "GSTR-1"]:
        for pat in GST_TYPE_PATTERNS[gst_type]:
            if re.search(pat, text, re.IGNORECASE):
                return gst_type
    return "UNKNOWN"


# ── Core number utilities ─────────────────────────────────────────────────────

def _clean_number(raw: str) -> Optional[float]:
    """Parse a number string → float or None. Never returns None for 0."""
    if raw is None:
        return None
    cleaned = re.sub(r"[₹,\s]", "", str(raw).strip())
    if cleaned in ("", "-", "–", "N/A", "NA", "nil", "Nil", "NIL"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_all_numbers(line: str) -> List[float]:
    """Extract all numbers from a line, handling Indian number formatting."""
    line_clean = re.sub(r"₹", "", line)
    # Handle currency-prefixed numbers like L1473924.52 → space before digit
    # (some PDFs encode ₹ as 'L' or other letters, leaving no word boundary)
    line_clean = re.sub(r'(?<=[A-Za-z])([\d])', r' \1', line_clean)
    # Match Indian-format numbers: 1,00,000.00 or 18,000 or 0.00
    matches = re.findall(r"\b[\d,]+(?:\.\d+)?\b", line_clean)
    results = []
    for m in matches:
        cleaned = m.replace(",", "")
        try:
            val = float(cleaned)
            results.append(val)
        except ValueError:
            continue
    return results


def _extract_period(text: str) -> str:
    """Extract the filing period from document text."""

    # ── Format: "Year\n2021-22\nPeriod March(M)" or "Year 2025-26\nPeriod April" ──
    m_year   = re.search(r"Year\s*[\n\r\s]+(\d{4}-\d{2,4})", text, re.IGNORECASE)
    # Accept both "Period April(M)" (older) and "Period April" (newer portal, no suffix)
    m_month  = re.search(r"Period\s+([A-Za-z]+)\s*(?:\([MQ]\))?", text, re.IGNORECASE)
    if m_year and m_month:
        year_part  = m_year.group(1)          # e.g. "2025-26"
        month_name = m_month.group(1)          # e.g. "April"
        parts      = year_part.split("-")
        fy_start   = parts[0]                  # "2025"
        fy_end_s   = parts[-1]
        fy_end     = ("20" + fy_end_s) if len(fy_end_s) == 2 else fy_end_s  # "2026"
        # April–December belong to the FY start year; January–March to the FY end year
        _LATE_MONTHS = {'january', 'february', 'march', 'jan', 'feb', 'mar'}
        cal_year = fy_end if month_name.lower()[:3] in {'jan', 'feb', 'mar'} else fy_start
        return f"{month_name} {cal_year}"

    # ── Format: "Period: March 2024" or "Month: April 2023" ──
    m = re.search(
        r"(?:for\s+the\s+period|Period\s+of\s+Return|Tax\s+Period|Month|Period)\s*[:\-]?\s*"
        r"([A-Za-z]+[\s\-]\d{4})",
        text, re.IGNORECASE,
    )
    if m:
        try:
            return m.group(1).strip()
        except IndexError:
            return m.group(0).strip()

    # ── Format: "March 2024" anywhere in text ──
    m = re.search(
        r"(?:April|May|June|July|August|September|October|November|December|"
        r"January|February|March)\s+\d{4}",
        text, re.IGNORECASE,
    )
    if m:
        return m.group(0).strip()

    # ── Financial year: "2021-22" ──
    m = re.search(r"\b(\d{4}-\d{2,4})\b", text)
    if m:
        return m.group(1).strip()

    return "Period not found"


def _extract_period_from_filename(filename: str) -> Optional[str]:
    """
    Try to extract a human-readable month-year period from a filename.

    Supports:
      Pattern 1 — alphabetic month before year:  Apr_2023, April-2023, Apr2023
      Pattern 2 — year before alphabetic month:  2023_Apr, 2023-April
      Pattern 3 — numeric MM before YYYY:        042023, 04_2023, 04-2023
                  e.g. GSTR1_GSTIN_042023.pdf → April 2023
      Pattern 4 — numeric YYYY before MM:        2023_04, 2023-04

    Returns "April 2023" style string, or None if no month detected.
    """
    _MONTH_MAP = {
        'jan': 'January', 'feb': 'February', 'mar': 'March',  'apr': 'April',
        'may': 'May',     'jun': 'June',      'jul': 'July',   'aug': 'August',
        'sep': 'September','oct': 'October',  'nov': 'November','dec': 'December',
    }
    _NUM_TO_MONTH = [
        '', 'January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December',
    ]

    # Pattern 1: alphabetic month before year — Apr_2023, April2023, etc.
    m = re.search(
        r'(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|'
        r'jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)'
        r'[\s_\-]?(\d{4})',
        filename, re.IGNORECASE,
    )
    if m:
        key = m.group(1).lower()[:3]
        return f"{_MONTH_MAP[key]} {m.group(2)}"

    # Pattern 2: year before alphabetic month — 2023_Apr, 2023-April
    m = re.search(
        r'(\d{4})[\s_\-]?(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|'
        r'jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|'
        r'nov(?:ember)?|dec(?:ember)?)',
        filename, re.IGNORECASE,
    )
    if m:
        key = m.group(2).lower()[:3]
        return f"{_MONTH_MAP[key]} {m.group(1)}"

    # Pattern 3: numeric MM immediately followed by YYYY (no separator, or _ or -)
    # Matches: _042023.pdf  _04_2023.pdf  _04-2023.pdf
    # Requires a non-digit boundary before MM to avoid matching GSTIN digits.
    m = re.search(r'(?<!\d)(0[1-9]|1[0-2])[\-_]?(\d{4})(?!\d)', filename)
    if m:
        month_num = int(m.group(1))
        return f"{_NUM_TO_MONTH[month_num]} {m.group(2)}"

    # Pattern 4: YYYY before numeric MM — 2023_04, 2023-04
    m = re.search(r'(?<!\d)(\d{4})[\-_](0[1-9]|1[0-2])(?!\d)', filename)
    if m:
        month_num = int(m.group(2))
        return f"{_NUM_TO_MONTH[month_num]} {m.group(1)}"

    return None


def _extract_gstin(text: str) -> Optional[str]:
    m = re.search(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b", text)
    return m.group(0) if m else None


def _extract_legal_name(text: str) -> Optional[str]:
    # Skip patterns that are just column/field labels (no actual value on the same line)
    _LABEL_JUNK = re.compile(
        r"of\s+the\s+registered|Legal\s+name\s+of|Name\s+of\s+taxpayer",
        re.IGNORECASE,
    )

    candidates: List[str] = []

    # 1. "Legal name: COMPANY" or "Trade name: COMPANY" (label followed by colon + value)
    m = re.search(
        r"(?:Legal\s+name|Trade\s+name)\s*[:\-]\s*([^\n]{3,80})",
        text, re.IGNORECASE,
    )
    if m and not _LABEL_JUNK.search(m.group(1)):
        candidates.append(m.group(1).strip())

    # 2. "M/S. COMPANY NAME" format (common in GST portal PDFs)
    m = re.search(r"M/[sS]\.?\s+([A-Z0-9][^\n]{3,80}?)(?:\s*\.|$)", text, re.IGNORECASE | re.MULTILINE)
    if m:
        val = m.group(1).strip().rstrip(".")
        if not _LABEL_JUNK.search(val):
            candidates.append(val)

    # 3. Text on line immediately after GSTIN (GST portal summary PDFs)
    m = re.search(
        r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b[\s\n]+([A-Z][A-Z0-9 &./\-]{3,80})",
        text,
    )
    if m:
        val = m.group(1).strip()
        if not _LABEL_JUNK.search(val):
            candidates.append(val)

    # Return the first clean candidate
    for c in candidates:
        c = c.strip()
        if len(c) >= 3 and not _LABEL_JUNK.search(c):
            return c

    return None


# ── Section extraction helpers ────────────────────────────────────────────────

def _find_section(
    text: str,
    *start_patterns: str,
    end_patterns: Optional[List[str]] = None,
    max_chars: int = 5000,
) -> Optional[str]:
    """
    Extract text starting from first matching start_pattern
    up to the first matching end_pattern (or max_chars).
    """
    start_pos = None
    for pat in start_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            start_pos = m.start()
            break
    if start_pos is None:
        return None

    section = text[start_pos : start_pos + max_chars]

    if end_patterns:
        end_pos = len(section)
        for pat in end_patterns:
            # Skip first 30 chars to avoid matching the start itself
            m = re.search(pat, section[30:], re.IGNORECASE)
            if m:
                end_pos = min(end_pos, m.start() + 30)
        section = section[:end_pos]

    return section


def _find_line_with_labels(text: str, *label_patterns: str) -> Optional[str]:
    """Return the first line that matches ALL label patterns (case-insensitive)."""
    for line in text.split("\n"):
        if all(re.search(pat, line, re.IGNORECASE) for pat in label_patterns):
            return line
    return None


def _find_lines_with_label(text: str, *label_patterns: str) -> List[str]:
    """Return ALL lines matching all given label patterns."""
    results = []
    for line in text.split("\n"):
        if all(re.search(pat, line, re.IGNORECASE) for pat in label_patterns):
            results.append(line)
    return results


def _numbers_from_line(line: str) -> List[float]:
    """Extract all valid numbers from a single line."""
    return _extract_all_numbers(line)


def _numbers_from_line_and_next(text: str, label: str) -> List[float]:
    """
    Find line matching label, return numbers from that line AND the next line
    combined (handles cases where numbers wrap to next line in PDF).
    """
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if re.search(label, line, re.IGNORECASE):
            combined = line
            if i + 1 < len(lines):
                combined += " " + lines[i + 1]
            if i + 2 < len(lines):
                combined += " " + lines[i + 2]
            return _extract_all_numbers(combined)
    return []


# ── Table utilities (for fallback) ───────────────────────────────────────────

def _table_to_rows(table: List[List]) -> List[List[str]]:
    rows = []
    for row in table:
        cleaned = [str(c).strip() if c is not None else "" for c in row]
        if any(cleaned):
            rows.append(cleaned)
    return rows


def _find_value_in_table(
    rows: List[List[str]],
    label_fragments: List[str],
) -> Optional[float]:
    for row in rows:
        joined = " ".join(row).lower()
        if all(frag.lower() in joined for frag in label_fragments):
            for cell in reversed(row):
                v = _clean_number(cell)
                if v is not None:
                    return v
    return None


def _row_numbers(row: List[str]) -> List[float]:
    nums = []
    for cell in row:
        v = _clean_number(cell)
        if v is not None:
            nums.append(v)
    return nums


# ── GSTR-3B Parser ────────────────────────────────────────────────────────────
# Strategy:
#   1. Try _parse_gstr3b_tables() — reads values directly from grid columns,
#      no fragile text-scanning. Works for all GST portal formats FY18 onwards.
#   2. Fall back to text-based section parser for any field still missing.
#   3. Final safety net: _gstr3b_table_fallback() for critical missing fields.

def parse_gstr3b(text: str, tables: List[List[List]]) -> Dict[str, Any]:
    """
    Parse GSTR-3B — table-first strategy with text fallback.

    Section 3.1 — Outward supplies (taxable value, IGST, CGST, SGST)
    Section 4   — ITC: available, reversed, net
    Section 5.1 — Interest and late fee
    Section 6.1 — Payment of tax (ITC used, cash paid)
    """
    data: Dict[str, Any] = {
        "form_type": "GSTR-3B",
        # True for the GSTR-3B "System Generated Summary" (annual) reference file —
        # excluded from risk-ratio aggregation so it is not double-counted.
        "is_annual_summary": bool(re.search(r'system\s+generated\s+summary', text, re.IGNORECASE)),
        "gstin": _extract_gstin(text),
        "legal_name": _extract_legal_name(text),
        "period": _extract_period(text),
        # Section 3.1 — outward supplies
        "taxable_sales": None,       # 3.1(a) taxable
        "igst_on_sales": None,       # 3.1(a) IGST
        "cgst_on_sales": None,       # 3.1(a) CGST
        "sgst_on_sales": None,       # 3.1(a) SGST
        "cess_on_sales": None,       # 3.1(a) Cess
        "zero_rated_sales": None,    # 3.1(b) taxable
        "s31b_igst": None,           # 3.1(b) IGST
        "nil_rated_sales": None,     # 3.1(c) taxable (nil/exempt)
        "exempt_sales": None,
        "non_gst_sales": None,       # 3.1(e) taxable
        # 3.1(d) RCM inward supplies
        "s31d_rcm_taxable": None,
        "s31d_rcm_igst": None,
        "s31d_rcm_cgst": None,
        "s31d_rcm_sgst": None,
        # 3.1.1 — Supplies notified under section 9(5) of CGST Act, 2017
        "s311i_taxable": None,   # (i) ECO operator pays tax — taxable value
        "s311i_igst": None,      # (i) IGST
        "s311i_cgst": None,      # (i) CGST
        "s311i_sgst": None,      # (i) SGST
        "s311i_cess": None,      # (i) Cess
        "s311ii_taxable": None,  # (ii) Registered person through ECO — taxable only
        # 3.2 Inter-state supplies
        "s32_unreg_taxable": None,
        "s32_unreg_igst": None,
        "s32_comp_taxable": None,
        "s32_uin_taxable": None,
        # Section 4 — ITC (A) individual sub-items
        "itc_a1_igst": None, "itc_a1_cgst": None, "itc_a1_sgst": None, "itc_a1_cess": None,  # (1) Import of goods
        "itc_a2_igst": None, "itc_a2_cgst": None, "itc_a2_sgst": None, "itc_a2_cess": None,  # (2) Import of services
        "itc_a3_igst": None, "itc_a3_cgst": None, "itc_a3_sgst": None, "itc_a3_cess": None,  # (3) Inward RCM
        "itc_a4_igst": None, "itc_a4_cgst": None, "itc_a4_sgst": None, "itc_a4_cess": None,  # (4) ISD
        "itc_a5_igst": None, "itc_a5_cgst": None, "itc_a5_sgst": None, "itc_a5_cess": None,  # (5) All other ITC
        # Section 4 — ITC (A) gross available (sum of sub-items 1-5)
        "itc_avail_igst": None,
        "itc_avail_cgst": None,
        "itc_avail_sgst": None,
        "itc_avail_cess": None,
        # Section 4 — ITC (B) individual sub-items
        "itc_b1_igst": None, "itc_b1_cgst": None, "itc_b1_sgst": None, "itc_b1_cess": None,  # (1) Rules 38,42,43 & s17(5)
        "itc_b2_igst": None, "itc_b2_cgst": None, "itc_b2_sgst": None, "itc_b2_cess": None,  # (2) Others
        # Section 4 — ITC (B) reversed (sum of sub-items 1-2)
        "itc_reversed_igst": None,
        "itc_reversed_cgst": None,
        "itc_reversed_sgst": None,
        "itc_rev_cess": None,
        # Section 4 — ITC (C) net available
        "itc_igst_available": None,
        "itc_cgst_available": None,
        "itc_sgst_available": None,
        "itc_net_cess": None,
        # Section 4 — ITC (D)(1) ITC reclaimed which was reversed under Table 4(B)(2)
        "itc_d1_igst": None,
        "itc_d1_cgst": None,
        "itc_d1_sgst": None,
        "itc_d1_cess": None,
        # Section 4 — ITC (D)(2) Ineligible ITC u/s 16(4) & restricted due to PoS rules
        "itc_d2_igst": None,
        "itc_d2_cgst": None,
        "itc_d2_sgst": None,
        "itc_d2_cess": None,
        # Sec 4D ineligible (legacy alias)
        "itc_ineligible_igst": None,
        "itc_ineligible_cgst": None,
        "itc_ineligible_sgst": None,
        # Table 5 — values of nil/exempt and non-GST inward supplies
        "s5_nil_interstate": None,
        "s5_nil_intrastate": None,
        "s5_nongst_interstate": None,
        "s5_nongst_intrastate": None,
        # Section 5.1 — Interest per component
        "s51_int_igst": None,
        "s51_int_cgst": None,
        "s51_int_sgst": None,
        "s51_int_cess": None,
        # Section 5.1 — Late Fee per component
        "s51_latefee_cgst": None,
        "s51_latefee_sgst": None,
        # Section 6 — Payment
        "cash_paid_igst": None,
        "cash_paid_cgst": None,
        "cash_paid_sgst": None,
        "itc_used_igst": None,
        "itc_used_cgst": None,
        "itc_used_sgst": None,
        # Legacy aggregates (kept for backward compat)
        "interest_paid": None,
        "late_fee_paid": None,
        "_parse_warnings": [],
    }

    logger.info("[GSTR-3B] Parsing started. Text length=%d", len(text))

    # ── Step 1: Table-based extraction (primary, most accurate) ───────────────
    # Run the table parser first and pre-populate fields from clean grid data.
    # Any field set here won't be overwritten by the text parser below
    # (text parser uses "data[field] = data[field] or value" pattern).
    if tables:
        tbl_result = _parse_gstr3b_tables(tables)
        if tbl_result:
            # Merge table results into data dict — only set fields that are
            # currently None, preserving any field already set.
            for k, v in tbl_result.items():
                if k in data and data[k] is None:
                    data[k] = v
            logger.info("[GSTR-3B] Table parser populated %d fields", len(tbl_result))

    _annual_pdfminer_mode = False   # set True if annual "System Generated Summary" format detected

    # ── Section 3.1: Outward Supplies ─────────────────────────────────────────
    sec31 = _find_section(
        text,
        r"3\.1\s+Details\s+of\s+Outward",
        r"3\.1[\.\s]",
        r"Outward\s+Supplies\s+and\s+inward",
        end_patterns=[r"\n3\.2", r"\n4[\s\.]", r"3\.2\s"],
        max_chars=3000,
    )

    if sec31:
        logger.debug("[GSTR-3B] Section 3.1 found (%d chars): %.200s", len(sec31), sec31)

        # (a) Outward taxable supplies — the MAIN field
        line_a = _find_line_with_labels(
            sec31,
            r"\(a\)|^\s*a\b",
            r"outward taxable",
        )
        if line_a is None:
            line_a = _find_line_with_labels(sec31, r"outward taxable", r"other than")
        if line_a is None:
            # fallback: any line with "other than zero rated"
            line_a = _find_line_with_labels(sec31, r"other than zero rated")
        if line_a is None:
            # Look at lines in section for "(a)"
            for ln in sec31.split("\n"):
                if re.match(r"^\s*\(a\)", ln.strip()):
                    line_a = ln
                    break

        if line_a:
            nums = _numbers_from_line(line_a)
            # If numbers are few (PDF wrapped), also grab next line(s)
            if len(nums) < 3:
                nums = _numbers_from_line_and_next(sec31, re.escape(line_a.strip()[:30]))
            logger.info("[GSTR-3B] 3.1(a) line='%.80s' nums=%s", line_a.strip(), nums)
            if len(nums) >= 1:
                data["taxable_sales"] = nums[0]
            if len(nums) >= 2:
                data["igst_on_sales"] = nums[1]
            if len(nums) >= 3:
                data["cgst_on_sales"] = nums[2]
            if len(nums) >= 4:
                data["sgst_on_sales"] = nums[3]
            if len(nums) >= 5:
                data["cess_on_sales"] = nums[4]
        else:
            logger.warning("[GSTR-3B] 3.1(a) line NOT found")
            data["_parse_warnings"].append("Section 3.1(a) outward taxable supplies not found in text")

        # pdfminer fallback: annual GSTR-3B "System Generated Summary" format puts
        # numbers in scrambled column order. IGST+CGST appear BEFORE "Total Taxable value"
        # header; taxable value appears as the first standalone number AFTER that header.
        if data["taxable_sales"] is None and sec31 and 'Total Taxable' in sec31:
            parts = sec31.split('Total Taxable', 1)
            pre, post = parts[0], parts[1]
            # IGST + CGST/SGST are a pair of numbers on the same line before the header
            paired = re.search(r'([\d,]+\.\d{2})\s+([\d,]+\.\d{2})', pre)
            if paired:
                try:
                    igst = float(paired.group(1).replace(',', ''))
                    cgst = float(paired.group(2).replace(',', ''))
                    if igst > 10000:
                        if data["igst_on_sales"] is None: data["igst_on_sales"] = igst
                        if data["cgst_on_sales"] is None: data["cgst_on_sales"] = cgst
                        if data["sgst_on_sales"] is None: data["sgst_on_sales"] = cgst
                        logger.info("[GSTR-3B][pdfminer-summary] igst=%s cgst=%s", igst, cgst)
                except ValueError:
                    pass
            # First number after the header = taxable value
            m_tax = re.search(r'([\d,]+\.\d{2})', post)
            if m_tax:
                try:
                    v = float(m_tax.group(1).replace(',', ''))
                    if v > 10000:
                        data["taxable_sales"] = v
                        _annual_pdfminer_mode = True
                        logger.info("[GSTR-3B][pdfminer-summary] taxable_sales=%s", v)
                except ValueError:
                    pass

        # (b) Zero rated — taxable value + IGST
        # NOTE: allow optional whitespace inside the label parens — some portal
        # PDFs render "(b )" / "(c )" / "(d )" with a stray space (see 3.1(c) below).
        line_b = _find_line_with_labels(sec31, r"\(\s*b\s*\)", r"zero")
        if line_b is None:
            line_b = _find_line_with_labels(sec31, r"zero.?rated.*supplies")
        if line_b:
            nums = _numbers_from_line(line_b)
            if nums:
                data["zero_rated_sales"] = nums[0]
                if len(nums) >= 2:
                    data["s31b_igst"] = nums[1]
                logger.info("[GSTR-3B] Zero-rated taxable=%s igst=%s", nums[0], data["s31b_igst"])

        # (c) Nil rated / exempt
        # Tolerate "(c )" (stray space). CRITICAL: the fallback must NOT match row
        # (a), whose label reads "...(other than zero rated, nil rated and exempted)"
        # — matching it here copies 3.1(a)'s taxable value straight into 3.1(c).
        line_c = _find_line_with_labels(sec31, r"\(\s*c\s*\)", r"nil|exempt")
        if line_c is None:
            for _ln in sec31.split("\n"):
                if (re.search(r"nil\s*rated|exempt", _ln, re.IGNORECASE)
                        and not re.search(r"other\s+than|\(\s*a\s*\)", _ln, re.IGNORECASE)):
                    line_c = _ln
                    break
        if line_c:
            nums = _numbers_from_line(line_c)
            if nums:
                data["nil_rated_sales"] = nums[0]

        # (d) Inward supplies liable to reverse charge (RCM)
        line_d = _find_line_with_labels(sec31, r"\(\s*d\s*\)", r"inward|reverse")
        if line_d is None:
            line_d = _find_line_with_labels(sec31, r"inward supplies.*liable|reverse charge")
        if line_d:
            nums = _numbers_from_line(line_d)
            if len(nums) < 3:
                nums = _numbers_from_line_and_next(sec31, re.escape(line_d.strip()[:30]))
            logger.info("[GSTR-3B] 3.1(d) RCM='%.60s' nums=%s", line_d.strip(), nums)
            if len(nums) >= 1: data["s31d_rcm_taxable"] = nums[0]
            if len(nums) >= 2: data["s31d_rcm_igst"]    = nums[1]
            if len(nums) >= 3: data["s31d_rcm_cgst"]    = nums[2]
            if len(nums) >= 4: data["s31d_rcm_sgst"]    = nums[3]

        # (e) Non-GST
        line_e = _find_line_with_labels(sec31, r"non.?gst")
        if line_e:
            nums = _numbers_from_line(line_e)
            if nums:
                data["non_gst_sales"] = nums[0]
    else:
        logger.warning("[GSTR-3B] Section 3.1 NOT found")
        data["_parse_warnings"].append("Section 3.1 (Outward Supplies) not found — will try table fallback")

    # ── Section 3.1.1: Supplies notified under section 9(5) of CGST Act ─────────
    sec311 = _find_section(
        text,
        r"3\.1\.1\s", r"3\.1\.1\b",
        r"section\s+9\s*\(\s*5\s*\)",
        end_patterns=[r"\n3\.2", r"3\.2\s", r"\n4[\s\.]"],
        max_chars=1500,
    )
    if sec311:
        logger.debug("[GSTR-3B] Section 3.1.1 found (%d chars): %.200s", len(sec311), sec311)
        # (i) ECO operator pays tax — 5 values: Taxable, IGST, CGST, SGST, Cess
        line_311i = _find_line_with_labels(sec311, r"\(i\)|eco.*operator.*pays|operator.*pays.*tax")
        if line_311i is None:
            line_311i = _find_line_with_labels(sec311, r"eco.*operator|electronic.*commerce.*operator")
        if line_311i:
            nums = _numbers_from_line(line_311i)
            if len(nums) < 3:
                nums = _numbers_from_line_and_next(sec311, re.escape(line_311i.strip()[:30]))
            logger.info("[GSTR-3B] 3.1.1(i) line='%.80s' nums=%s", line_311i.strip(), nums)
            # Section 3.1.1(i) label contains "section 9(5)" which contributes false
            # positives 9 and 5. The actual 5 values (Taxable/IGST/CGST/SGST/Cess) are
            # always at the END of the number list — take the last 5.
            if len(nums) >= 5:
                v = nums[-5:]
                data["s311i_taxable"] = v[0] or None
                data["s311i_igst"]    = v[1] or None
                data["s311i_cgst"]    = v[2] or None
                data["s311i_sgst"]    = v[3] or None
                data["s311i_cess"]    = v[4] or None
            elif len(nums) >= 1:
                data["s311i_taxable"] = nums[0] or None
                if len(nums) >= 2: data["s311i_igst"]    = nums[1] or None
                if len(nums) >= 3: data["s311i_cgst"]    = nums[2] or None
                if len(nums) >= 4: data["s311i_sgst"]    = nums[3] or None
        # (ii) Registered person through ECO — taxable value only (IGST/CGST/SGST are "-")
        line_311ii = _find_line_with_labels(sec311, r"\(ii\)|registered.*person.*through|through.*eco")
        if line_311ii:
            nums = _numbers_from_line(line_311ii)
            if nums:
                data["s311ii_taxable"] = nums[0]
            logger.info("[GSTR-3B] 3.1.1(ii) taxable=%s", data["s311ii_taxable"])
    else:
        logger.debug("[GSTR-3B] Section 3.1.1 not found (may not be present in older PDFs)")

    # ── Section 3.2: Inter-State Supplies ─────────────────────────────────────
    sec32 = _find_section(
        text,
        r"3\.2\s", r"3\.2\b",
        r"inter.?state.*supplies.*unregistered",
        end_patterns=[r"\n4[\.\s]", r"\n4\s+Eligible"],
        max_chars=2000,
    )
    if sec32:
        # Require "\d+\.\d{2}" to skip the section header line which mentions
        # "3.2 ...Unregistered Persons" and "3.1(a)" but has no decimal amounts.
        line_unreg = _find_line_with_labels(sec32, r"unregistered|unreg", r"\d+\.\d{2}")
        if line_unreg:
            nums = _numbers_from_line(line_unreg)
            if len(nums) >= 1: data["s32_unreg_taxable"] = nums[0]
            if len(nums) >= 2: data["s32_unreg_igst"]    = nums[1]
        line_comp = _find_line_with_labels(sec32, r"composition", r"\d+\.\d{2}")
        if line_comp:
            nums = _numbers_from_line(line_comp)
            if nums: data["s32_comp_taxable"] = nums[0]
        line_uin = _find_line_with_labels(sec32, r"uin\b|unique.*identification", r"\d+\.\d{2}")
        if line_uin:
            nums = _numbers_from_line(line_uin)
            if nums: data["s32_uin_taxable"] = nums[0]
        logger.info("[GSTR-3B] 3.2 unreg_tax=%s comp_tax=%s uin_tax=%s",
                    data["s32_unreg_taxable"], data["s32_comp_taxable"], data["s32_uin_taxable"])

    # ── Section 4: Eligible ITC ────────────────────────────────────────────────
    sec4 = _find_section(
        text,
        r"4\s+Eligible\s+ITC",
        r"4[\.\s]+Eligible\s+ITC",
        r"Eligible\s+ITC",
        end_patterns=[r"\n5[\.\s]", r"\n6[\.\s]", r"5\s*Values\s*of"],
        max_chars=4000,
    )

    if sec4:
        logger.debug("[GSTR-3B] Section 4 found (%d chars)", len(sec4))

        # ── (A) ITC Available — extract each sub-item individually, then sum ──
        # The header "A. ITC Available (whether in full or part)" carries NO numbers.
        itc_a_igst = itc_a_cgst = itc_a_sgst = itc_a_cess = 0.0
        _itc_a_found = False
        _sub_patterns_a = [
            (r"\(1\).*import.*goods|import.*goods.*\(1\)",           "itc_a1"),
            (r"\(2\).*import.*serv|import.*services.*\(2\)",         "itc_a2"),
            (r"\(3\).*reverse\s*charge|\(3\).*inward",               "itc_a3"),
            (r"\(4\).*isd|\(4\).*inward.*isd",                       "itc_a4"),
            (r"\(5\).*all.*other.*itc|all.*other.*itc.*\(5\)",       "itc_a5"),
        ]
        for sub_pat, prefix in _sub_patterns_a:
            ln = _find_line_with_labels(sec4, sub_pat)
            if ln:
                nums = _extract_all_numbers(ln)
                if len(nums) < 4:
                    nums = _numbers_from_line_and_next(sec4, re.escape(ln.strip()[:30]))
                if len(nums) >= 4:
                    # Sub-item lines start with "(n)" — LAST 4 values are IGST/CGST/SGST/Cess
                    v = nums[-4:]
                    data[f"{prefix}_igst"] = v[0] or None
                    data[f"{prefix}_cgst"] = v[1] or None
                    data[f"{prefix}_sgst"] = v[2] or None
                    data[f"{prefix}_cess"] = v[3] or None
                    itc_a_igst += v[0]; itc_a_cgst += v[1]
                    itc_a_sgst += v[2]; itc_a_cess += v[3]
                    _itc_a_found = True
                elif len(nums) >= 1:
                    data[f"{prefix}_igst"] = nums[0] or None
                    itc_a_igst += nums[0]
                    _itc_a_found = True
        if _itc_a_found:
            data["itc_avail_igst"] = itc_a_igst or None
            data["itc_avail_cgst"] = itc_a_cgst or None
            data["itc_avail_sgst"] = itc_a_sgst or None
            data["itc_avail_cess"] = itc_a_cess or None
            logger.info("[GSTR-3B] ITC(A) summed igst=%s cgst=%s sgst=%s",
                        itc_a_igst, itc_a_cgst, itc_a_sgst)

        # ── (B) ITC Reversed — extract each sub-item individually, then sum ──
        itc_b_igst = itc_b_cgst = itc_b_sgst = itc_b_cess = 0.0
        _itc_b_found = False
        _sub_patterns_b = [
            (r"\(1\).*rule|rules.*38|42.*43|section\s+17\s*\(5\)",  "itc_b1"),
            (r"\(2\).*others",                                        "itc_b2"),
        ]
        for sub_pat, prefix in _sub_patterns_b:
            ln = _find_line_with_labels(sec4, sub_pat)
            if ln:
                nums = _extract_all_numbers(ln)
                if len(nums) < 4:
                    nums = _numbers_from_line_and_next(sec4, re.escape(ln.strip()[:30]))
                if len(nums) >= 4:
                    v = nums[-4:]
                    data[f"{prefix}_igst"] = v[0] or None
                    data[f"{prefix}_cgst"] = v[1] or None
                    data[f"{prefix}_sgst"] = v[2] or None
                    data[f"{prefix}_cess"] = v[3] or None
                    itc_b_igst += v[0]; itc_b_cgst += v[1]
                    itc_b_sgst += v[2]; itc_b_cess += v[3]
                    _itc_b_found = True
        if _itc_b_found:
            data["itc_reversed_igst"] = itc_b_igst or None
            data["itc_reversed_cgst"] = itc_b_cgst or None
            data["itc_reversed_sgst"] = itc_b_sgst or None
            data["itc_rev_cess"]      = itc_b_cess or None

        # ── (C) Net ITC Available ─────────────────────────────────────────────
        line_net = _find_line_with_labels(sec4, r"Net ITC.*Available|C\s*\.\s*Net|Net.*ITC.*A\s*[-–]\s*B")
        if line_net is None:
            line_net = _find_line_with_labels(sec4, r"\(C\)", r"Net")
        if line_net is None:
            line_net = _find_line_with_labels(sec4, r"Net ITC")
        if line_net:
            nums = _numbers_from_line(line_net)
            if len(nums) < 3:
                nums = _numbers_from_line_and_next(sec4, re.escape(line_net.strip()[:30]))
            logger.info("[GSTR-3B] Net ITC='%.80s' nums=%s", line_net.strip(), nums)
            if len(nums) >= 1: data["itc_igst_available"] = nums[0]
            if len(nums) >= 2: data["itc_cgst_available"] = nums[1]
            if len(nums) >= 3: data["itc_sgst_available"] = nums[2]
            if len(nums) >= 4: data["itc_net_cess"]       = nums[3]
        else:
            logger.warning("[GSTR-3B] Net ITC line NOT found in section 4")
            data["_parse_warnings"].append("Section 4 Net ITC not found")
            # Fall back to (A) total as net if no reversal row
            if _itc_a_found:
                data["itc_igst_available"] = data["itc_avail_igst"]
                data["itc_cgst_available"] = data["itc_avail_cgst"]
                data["itc_sgst_available"] = data["itc_avail_sgst"]

        # ── (D)(1) ITC reclaimed which was reversed under Table 4(B)(2) ──────
        line_d1 = _find_line_with_labels(sec4, r"\(1\).*reclaimed|reclaimed.*reversed|4\(B\)\(2\)")
        if line_d1 is None:
            line_d1 = _find_line_with_labels(sec4, r"reclaimed")
        if line_d1:
            nums = _extract_all_numbers(line_d1)
            if len(nums) < 4:
                nums = _numbers_from_line_and_next(sec4, re.escape(line_d1.strip()[:30]))
            logger.info("[GSTR-3B] 4(D)(1) line='%.80s' nums=%s", line_d1.strip(), nums)
            v = nums[-4:] if len(nums) >= 4 else nums
            if len(v) >= 1: data["itc_d1_igst"] = v[0]
            if len(v) >= 2: data["itc_d1_cgst"] = v[1]
            if len(v) >= 3: data["itc_d1_sgst"] = v[2]
            if len(v) >= 4: data["itc_d1_cess"] = v[3]

        # ── (D)(2) Ineligible ITC u/s 16(4) & ITC restricted due to PoS rules ─
        line_d2 = _find_line_with_labels(sec4, r"\(2\).*ineligible|ineligible.*16\s*\(4\)|pos\s*rules|place\s+of\s+supply")
        if line_d2 is None:
            line_d2 = _find_line_with_labels(sec4, r"section\s+16.*\(4\)|16\s*\(4\)")
        if line_d2:
            nums = _extract_all_numbers(line_d2)
            if len(nums) < 4:
                nums = _numbers_from_line_and_next(sec4, re.escape(line_d2.strip()[:30]))
            logger.info("[GSTR-3B] 4(D)(2) line='%.80s' nums=%s", line_d2.strip(), nums)
            v = nums[-4:] if len(nums) >= 4 else nums
            if len(v) >= 1: data["itc_d2_igst"] = v[0]
            if len(v) >= 2: data["itc_d2_cgst"] = v[1]
            if len(v) >= 3: data["itc_d2_sgst"] = v[2]
            if len(v) >= 4: data["itc_d2_cess"] = v[3]

    else:
        logger.warning("[GSTR-3B] Section 4 (ITC) NOT found")
        data["_parse_warnings"].append("Section 4 (ITC) not found")

    # ── Table 5: Nil/Exempt and Non-GST inward/outward supplies ──────────────
    sec5 = _find_section(
        text,
        r"5\s+Values\s+of\s+exempt", r"5\.\s*Values.*exempt",
        r"nil.*rated.*exempt.*non.?gst",
        end_patterns=[r"\n5\.1", r"\n6[\.\s]"],
        max_chars=2000,
    )
    if sec5:
        # Table 5 layout: each row has TWO values — Inter-State and Intra-State on the SAME line.
        # Row 1: "From a supplier under composition scheme, Exempt, Nil rated supply  X.XX  Y.YY"
        # Row 2: "Non GST supply  X.XX  Y.YY"
        # So nums[0] = interstate, nums[1] = intrastate for both rows.

        # Find nil/exempt row — MUST have ≥2 numbers (inter + intra on same line).
        # Skip header lines like "5 Values of exempt, nil-rated..." that also contain
        # "exempt" but only have a section number (5) as a spurious number.
        line_nil = None
        for ln in sec5.split('\n'):
            if re.search(r"composition|nil\s*rated|exempt", ln, re.IGNORECASE):
                nums_check = _extract_all_numbers(ln)
                if len(nums_check) >= 2:
                    line_nil = ln
                    break
        if line_nil is None:
            # Fallback: first data line that has ≥2 numbers
            for ln in sec5.split('\n')[1:]:
                nums_check = _extract_all_numbers(ln)
                if len(nums_check) >= 2:
                    line_nil = ln
                    break
        if line_nil:
            nums = _extract_all_numbers(line_nil)
            if len(nums) >= 1: data["s5_nil_interstate"]  = nums[0]
            if len(nums) >= 2: data["s5_nil_intrastate"]  = nums[1]

        line_ng = None
        for ln in sec5.split('\n'):
            if re.search(r"non.?gst", ln, re.IGNORECASE):
                nums_check = _extract_all_numbers(ln)
                if len(nums_check) >= 2:
                    line_ng = ln
                    break
        if line_ng:
            nums = _extract_all_numbers(line_ng)
            if len(nums) >= 1: data["s5_nongst_interstate"] = nums[0]
            if len(nums) >= 2: data["s5_nongst_intrastate"] = nums[1]

        logger.info("[GSTR-3B] Table5 nil_inter=%s nil_intra=%s ng_inter=%s ng_intra=%s",
                    data["s5_nil_interstate"], data["s5_nil_intrastate"],
                    data["s5_nongst_interstate"], data["s5_nongst_intrastate"])

    # ── Section 5.1: Interest and Late Fee ────────────────────────────────────
    sec51 = _find_section(
        text,
        r"5\.1\s*Interest",
        r"Interest.*Late\s*Fee",
        end_patterns=[r"\n6[\.\s]", r"Payment\s+of\s+Tax"],
        max_chars=1500,
    )

    if sec51:
        # Iterate lines to find the interest DATA row — skip the combined header
        # "5.1 Interest and Late Fee" which has no usable numbers
        int_line_found = None
        for ln in sec51.split('\n'):
            if re.search(r'\binterest\b', ln, re.IGNORECASE) and not re.search(r'late.?fee', ln, re.IGNORECASE):
                nums = _extract_all_numbers(ln)
                if nums:  # only accept lines that actually contain numbers
                    int_line_found = ln
                    break
        if int_line_found:
            nums = _extract_all_numbers(int_line_found)
            # Per-component: IGST, CGST, SGST, Cess
            if len(nums) >= 1: data["s51_int_igst"] = nums[0]
            if len(nums) >= 2: data["s51_int_cgst"] = nums[1]
            if len(nums) >= 3: data["s51_int_sgst"] = nums[2]
            if len(nums) >= 4: data["s51_int_cess"] = nums[3]
            data["interest_paid"] = sum(n for n in [data["s51_int_igst"], data["s51_int_cgst"],
                                                     data["s51_int_sgst"], data["s51_int_cess"]]
                                        if n is not None)
            logger.info("[GSTR-3B] Interest igst=%s cgst=%s sgst=%s cess=%s",
                        data["s51_int_igst"], data["s51_int_cgst"],
                        data["s51_int_sgst"], data["s51_int_cess"])

        # Late fee data row — skip header lines
        late_line_found = None
        for ln in sec51.split('\n'):
            if re.search(r'late.?fee', ln, re.IGNORECASE) and not re.search(r'\binterest\b', ln, re.IGNORECASE):
                nums = _extract_all_numbers(ln)
                if nums:
                    late_line_found = ln
                    break
        if late_line_found:
            nums = _extract_all_numbers(late_line_found)
            # Late fee columns: CGST, SGST (no IGST on late fee)
            if len(nums) >= 1: data["s51_latefee_cgst"] = nums[0]
            if len(nums) >= 2: data["s51_latefee_sgst"] = nums[1]
            data["late_fee_paid"] = sum(n for n in [data["s51_latefee_cgst"], data["s51_latefee_sgst"]]
                                        if n is not None)
            logger.info("[GSTR-3B] Late fee cgst=%s sgst=%s",
                        data["s51_latefee_cgst"], data["s51_latefee_sgst"])

    # ── Section 6.1: Payment of Tax ───────────────────────────────────────────
    # NOTE: Do NOT use "Late\s+fee" as an end_pattern — it appears in the COLUMN
    # HEADER of section 6.1 itself ("Late fee paid in cash") and would cut the
    # section to just one line.
    sec61 = _find_section(
        text,
        r"6\.1\s*Payment\s+of\s+Tax",
        r"6\s*Payment\s+of\s+Tax",
        r"Payment\s+of\s+Tax.*6",
        end_patterns=[r"\n7[\.\s]", r"Verification", r"Breakup\s+of\s+tax"],
        max_chars=3000,
    )

    if sec61:
        logger.debug("[GSTR-3B] Section 6.1 found (%d chars)", len(sec61))

        # In GSTR-3B PDFs, section 6.1 has TWO sub-sections:
        #   (A) Other than reverse charge — rows: Integrated tax | Central tax | State/UT tax
        #   (B) Reverse charge — same row structure
        #
        # Each row label ("Integrated", "Central", "State/UT") is split across 2 lines:
        #   Line n  : "Integrated 29867208 0.00 29867208 26038068 0.00 0.00 - 3829140. 0.00 -"
        #   Line n+1: "tax .00 .00 .00 00"
        #
        # Column layout (10 cols; dashes "-" are omitted from extracted numbers):
        #   [0] Payable  [1] Adj  [2] Net  [3] ITC_IGST  [4] ITC_CGST  [5] ITC_SGST
        #   [ITC_Cess="-" → skipped]  [6] Cash  [7] Interest  [8] LateFee
        #
        # For CGST/SGST rows ITC_IGST=0 so ITC col is at index 4, Cash at index 5.
        # For IGST row all four ITC sub-cols are present (CGST/SGST=0) → Cash at 6.
        #
        # Strategy: separate (A) and (B) subsections, parse each tax row in (A)
        # for ITC, sum (A)+(B) for cash.

        lines61 = sec61.split('\n')
        a_start = b_start = None
        for i, ln in enumerate(lines61):
            if re.search(r'\(A\).*other.*reverse|other.*reverse.*charge', ln, re.IGNORECASE):
                a_start = i
            if re.search(r'\(B\).*reverse\s*charge', ln, re.IGNORECASE):
                b_start = i

        # Default: whole section is (A) if no (B) header found
        if a_start is None: a_start = 0
        sec61_a = '\n'.join(lines61[a_start : b_start]) if b_start else '\n'.join(lines61[a_start:])
        sec61_b = '\n'.join(lines61[b_start:]) if b_start else ''

        # Pattern that marks the start of a new tax row — used to avoid bleeding
        # numbers from the next row into the current one when combining lines.
        _ROW_LABEL_RE = re.compile(
            r'^\s*(central|state[\s/]|integrated|reverse|cess\b)', re.IGNORECASE
        )

        def _parse_61_tax_rows(block: str, igst_itc_idx: int = 3, cgst_itc_idx: int = 4,
                                igst_cash_idx: int = 6, other_cash_idx: int = 5):
            """
            Extract (ITC, Cash) for each of IGST/CGST/SGST from a 6.1 sub-block.
            Returns dict keyed by 'igst'/'cgst'/'sgst' → (itc, cash) tuples.
            """
            result = {}
            blk_lines = block.split('\n')
            for i, ln in enumerate(blk_lines):
                # Combine current line with the next continuation line (e.g. "tax" after
                # "Integrated"). Stop BEFORE any line that starts a new tax row label —
                # otherwise Central/State numbers bleed into the Integrated row's list.
                combined = ln
                if i + 1 < len(blk_lines):
                    combined += ' ' + blk_lines[i + 1]
                if i + 2 < len(blk_lines):
                    next2 = blk_lines[i + 2]
                    if not _ROW_LABEL_RE.match(next2):
                        combined += ' ' + next2
                nums = _extract_all_numbers(combined)
                if not nums or len(nums) < 3:
                    continue

                # "Tax payable" (Table 6.1 Column (2)) is always the first number.
                payable = nums[0] if nums else 0

                if re.search(r'\bintegrated\b', ln, re.IGNORECASE) and 'igst' not in result:
                    itc  = nums[igst_itc_idx]  if len(nums) > igst_itc_idx  else 0
                    cash = nums[igst_cash_idx] if len(nums) > igst_cash_idx else 0
                    result['igst'] = (itc, cash, payable)
                    logger.info("[GSTR-3B] 6.1 IGST nums=%s → itc=%s cash=%s payable=%s", nums, itc, cash, payable)

                elif re.search(r'\bcentral\b', ln, re.IGNORECASE) and 'cgst' not in result:
                    itc  = nums[cgst_itc_idx]   if len(nums) > cgst_itc_idx   else 0
                    cash = nums[other_cash_idx]  if len(nums) > other_cash_idx else 0
                    result['cgst'] = (itc, cash, payable)
                    logger.info("[GSTR-3B] 6.1 CGST nums=%s → itc=%s cash=%s payable=%s", nums, itc, cash, payable)

                elif re.search(r'\bstate\b|\bstate/ut\b|\butgst\b', ln, re.IGNORECASE) and 'sgst' not in result:
                    itc  = nums[cgst_itc_idx]   if len(nums) > cgst_itc_idx   else 0
                    cash = nums[other_cash_idx]  if len(nums) > other_cash_idx else 0
                    result['sgst'] = (itc, cash, payable)
                    logger.info("[GSTR-3B] 6.1 SGST nums=%s → itc=%s cash=%s payable=%s", nums, itc, cash, payable)

            return result

        # Column layout after removing dashes:
        # IGST row: [0=Payable] [1=ITC_IGST_used] [2..3=ITC_CGST/SGST→IGST] [4=Cash] [5=Interest]
        # CGST row: [0=Payable] [1=ITC_IGST→CGST] [2=ITC_CGST_used] [3=Cash] [4=Interest] [5=LateFee]
        # SGST row: [0=Payable] [1=ITC_IGST→SGST] [2=ITC_SGST_used] [3=Cash] [4=Interest] [5=LateFee]
        rows_a = _parse_61_tax_rows(sec61_a,
                                     igst_itc_idx=1, cgst_itc_idx=1,
                                     igst_cash_idx=4, other_cash_idx=3)
        # In (B) reverse-charge rows, all ITC columns are "-" (dashes) so skipped.
        # After removing dashes: [payable, adj, net, cash, interest, latefee]
        # Cash is at index 3 for (B) rows.
        rows_b = _parse_61_tax_rows(sec61_b,
                                     igst_itc_idx=99, cgst_itc_idx=99,
                                     igst_cash_idx=3, other_cash_idx=3)

        # Write final values: ITC from (A) only; Cash = (A) + (B).
        # Only fill if NOT already set by the table parser (step 1) — the table parser
        # uses exact column indices and is more reliable than text-based index detection.
        for key, tax in [('igst', 'itc_used_igst'), ('cgst', 'itc_used_cgst'), ('sgst', 'itc_used_sgst')]:
            if key in rows_a and data.get(tax) is None:
                data[tax] = rows_a[key][0] or None

        for key, (itc_key, cash_key, pay_key) in [
            ('igst', ('itc_used_igst', 'cash_paid_igst', 'tax_payable_igst')),
            ('cgst', ('itc_used_cgst', 'cash_paid_cgst', 'tax_payable_cgst')),
            ('sgst', ('itc_used_sgst', 'cash_paid_sgst', 'tax_payable_sgst')),
        ]:
            itc_a   = rows_a.get(key, (0, 0, 0))[0]
            cash_a  = rows_a.get(key, (0, 0, 0))[1]
            cash_b  = rows_b.get(key, (0, 0, 0))[1]
            pay_a   = rows_a.get(key, (0, 0, 0))[2] if len(rows_a.get(key, (0, 0, 0))) > 2 else 0
            if itc_a and data.get(itc_key) is None:
                data[itc_key] = itc_a or None
            if data.get(cash_key) is None:
                data[cash_key] = (cash_a + cash_b) or None
            # Table 6.1 Column (2) total tax liability (Section A — forward charge)
            if data.get(pay_key) is None:
                data[pay_key] = pay_a or None
    else:
        logger.warning("[GSTR-3B] Section 6.1 NOT found")
        data["_parse_warnings"].append("Section 6.1 (Payment of Tax) not found")

    # ── Annual pdfminer mode: clear garbage values ────────────────────────────
    # When the pdfminer fallback fires (annual "System Generated Summary" format),
    # sections 3.1.1, 3.2, and ITC sub-items can't be reliably parsed — the text
    # parser picks up section numbers (3.2, 42, 43) and date artifacts (72022) as
    # data values. Clear those fields so they show as missing rather than wrong.
    if _annual_pdfminer_mode:
        _annual_garbage_fields = [
            "s311i_taxable", "s311i_igst", "s311i_cgst", "s311i_sgst", "s311i_cess",
            "s311ii_taxable",
            "s32_unreg_taxable", "s32_unreg_igst", "s32_comp_taxable", "s32_uin_taxable",
            "itc_a1_igst", "itc_a1_cgst", "itc_a1_sgst", "itc_a1_cess",
            "itc_a2_igst", "itc_a2_cgst", "itc_a2_sgst", "itc_a2_cess",
            "itc_a3_igst", "itc_a3_cgst", "itc_a3_sgst", "itc_a3_cess",
            "itc_a4_igst", "itc_a4_cgst", "itc_a4_sgst", "itc_a4_cess",
            "itc_a5_igst", "itc_a5_cgst", "itc_a5_sgst", "itc_a5_cess",
            "itc_avail_igst", "itc_avail_cgst", "itc_avail_sgst", "itc_avail_cess",
            "itc_b1_igst", "itc_b1_cgst", "itc_b1_sgst", "itc_b1_cess",
            "itc_b2_igst", "itc_b2_cgst", "itc_b2_sgst", "itc_b2_cess",
            "itc_reversed_igst", "itc_reversed_cgst", "itc_reversed_sgst", "itc_rev_cess",
            "itc_igst_available", "itc_cgst_available", "itc_sgst_available", "itc_net_cess",
            "itc_d1_igst", "itc_d1_cgst", "itc_d1_sgst", "itc_d1_cess",
            "itc_d2_igst", "itc_d2_cgst", "itc_d2_sgst", "itc_d2_cess",
        ]
        for f in _annual_garbage_fields:
            data[f] = None
        logger.info("[GSTR-3B][pdfminer-summary] Cleared unreliable fields for annual format")

    # ── Table-based fallback for any missing critical fields ──────────────────
    missing_critical = (
        data["taxable_sales"] is None
        or data["igst_on_sales"] is None
        or data["itc_igst_available"] is None
    )
    if missing_critical and not _annual_pdfminer_mode:
        logger.info("[GSTR-3B] Running table fallback (critical fields missing)")
        _gstr3b_table_fallback(data, tables)

    # ── Final reconcile: table fills only missing (None) values ───────────────
    # Only populate fields the text parser couldn't find. We deliberately do NOT
    # overwrite existing values here — the pdfminer fallback may have correctly
    # set fields that garbled pdfplumber tables would clobber (e.g. annual PDFs
    # where column order is scrambled).
    if tables and not _annual_pdfminer_mode:
        tbl_final = _parse_gstr3b_tables(tables)
        for k, v in tbl_final.items():
            if k in data and data[k] is None and v is not None:
                data[k] = v

    # ── Summary log ───────────────────────────────────────────────────────────
    logger.info(
        "[GSTR-3B] RESULT: taxable_sales=%s igst=%s cgst=%s sgst=%s "
        "itc_igst=%s itc_cgst=%s itc_sgst=%s cash_igst=%s",
        data["taxable_sales"], data["igst_on_sales"], data["cgst_on_sales"],
        data["sgst_on_sales"], data["itc_igst_available"], data["itc_cgst_available"],
        data["itc_sgst_available"], data["cash_paid_igst"],
    )
    return data


# ── Table-based GSTR-3B parser ────────────────────────────────────────────────

def _tbl_clean(cell) -> str:
    """Strip watermark letter-artifacts and whitespace from a pdfplumber cell."""
    if cell is None:
        return ''
    s = str(cell).strip()
    # Portal PDFs embed single-letter watermarks before/after real content:
    # e.g. "D\ncash", "I\n8794931.00", "L\nTotal taxable value", "E\n4.44"
    s = re.sub(r'^[A-Z]\n', '', s)   # Leading  "X\n"
    s = re.sub(r'\n[A-Z]$', '', s)   # Trailing "\nX"
    return s.strip()


def _tbl_num(cell) -> Optional[float]:
    """Parse a numeric value from a cell; return None for dashes / empty."""
    s = _tbl_clean(cell)
    s = re.sub(r'[,\s]', '', s)
    if not s or s in ('-', '--', 'N/A', 'nil', 'Nil'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _tbl_label(cell) -> str:
    """Normalised lowercase label from a cell (strips artefacts)."""
    return _tbl_clean(cell).lower().strip()


def _parse_gstr3b_tables(tables: List) -> Dict[str, Any]:
    """
    Primary table-based GSTR-3B extractor.
    Uses pdfplumber table grids which preserve column alignment perfectly.

    Returns a dict with all extractable fields, or an empty dict if the
    expected table structure is not found (caller falls back to text parser).

    Tables identified by column count + header keywords:
      Table 3.1  — 6 cols, header has 'Nature of Supplies' + taxable value
      Table 4    — 5 cols, header has 'Details'/'Integrated tax' OR starts with
                   ITC sub-item row (newer PDFs split Table 4 across 2 pages;
                   the second part has no header row)
      Table 6.1  — 9 cols (older) OR 11 cols (newer portal format that added
                   'Adjustment of negative liability' column).
                   Header contains 'Description'/'Descripti' + payment keywords.
    """
    result: Dict[str, Any] = {}

    # ── Classify tables by shape and header ───────────────────────────────────
    t31_tbl   = None   # Section 3.1 outward supplies (first 6-col Nature-of-Supplies table)
    t311_tbl  = None   # Section 3.1.1 (second 6-col Nature-of-Supplies table)
    t32_tbl   = None   # Section 3.2 inter-state supplies (3-col)
    t4_rows   = []     # ITC section (may merge 2 tables from different pages)
    t61_tbl   = None   # Payment of tax
    t61_ncols = 9      # track which column layout was found (9 or 11)

    # Keywords that identify a row as belonging to Table 4 (ITC section)
    _T4_ROW_KEYS = [
        'integrated', 'details', 'itc available', 'inward supplies from',
        'all other itc', '(4)', '(5)', 'b. itc', 'c. net itc', 'net itc',
        'import of goods', 'import of services', 'itc reversed', 'inward supplies liable',
        '(1) import', '(2) import', '(3) inward', '(4) inward', '(5) all other',
    ]

    for tbl in tables:
        if not tbl:
            continue
        ncols = max(len(r) for r in tbl)
        hdr   = ' '.join(_tbl_label(c) for c in (tbl[0] or []))

        if ncols == 6 and 'nature of supplies' in hdr and ('taxable' in hdr or 'value' in hdr):
            # Take the FIRST matching table as section 3.1; the SECOND is section 3.1.1.
            # Annual PDFs have both tables (3.1 on page 1, 3.1.1 on page 2) with identical
            # header signatures — without first-wins logic the 3.1.1 table (all zeros) would
            # overwrite the correctly-extracted 3.1 values.
            if t31_tbl is None:
                t31_tbl = tbl
            elif t311_tbl is None:
                t311_tbl = tbl

        elif ncols == 3 and 'nature of supplies' in hdr and 'taxable' in hdr and 'integrated' in hdr:
            t32_tbl = tbl

        elif ncols == 5 and any(kw in hdr for kw in _T4_ROW_KEYS):
            # Table 4 may be split across pages — accumulate all candidate 5-col ITC tables.
            # Newer PDFs: second half starts directly with a data row (no header), so the
            # "header" of that pdfplumber table is actually a data row like "(4) Inward...".
            t4_rows.extend(tbl)

        elif ncols in (9, 11) and ('descrip' in hdr) and (
                'tax paid through itc' in hdr or 'adjustment' in hdr or 'net tax' in hdr):
            # Table 6.1 — accept both old 9-col and new 11-col formats.
            # New format added 'Adjustment of negative liability' + 'Net Tax Payable' columns.
            t61_tbl   = tbl
            t61_ncols = ncols

    # ── Table 3.1: Outward Supplies ───────────────────────────────────────────
    if t31_tbl:
        for row in t31_tbl:
            lbl = _tbl_label(row[0]) if row else ''
            if '(a)' in lbl and 'outward' in lbl:
                result['taxable_sales'] = _tbl_num(row[1])
                result['igst_on_sales'] = _tbl_num(row[2])
                result['cgst_on_sales'] = _tbl_num(row[3])
                result['sgst_on_sales'] = _tbl_num(row[4])
                break
            # Fallback: first numeric row after header
            if not result.get('taxable_sales') and any(_tbl_num(c) for c in row[1:5]):
                if 'nature' not in lbl and 'taxable' not in lbl:
                    result['taxable_sales'] = _tbl_num(row[1])
                    result['igst_on_sales'] = _tbl_num(row[2])
                    result['cgst_on_sales'] = _tbl_num(row[3])
                    result['sgst_on_sales'] = _tbl_num(row[4])

    # ── Table 3.1.1: Supplies notified under section 9(5) ───────────────────
    if t311_tbl:
        for row in t311_tbl:
            if not row:
                continue
            lbl = _tbl_label(row[0])
            if '(i)' in lbl and '(ii)' not in lbl:
                result['s311i_taxable'] = _tbl_num(row[1])
                result['s311i_igst']    = _tbl_num(row[2])
                result['s311i_cgst']    = _tbl_num(row[3])
                result['s311i_sgst']    = _tbl_num(row[4])
                if len(row) > 5:
                    result['s311i_cess'] = _tbl_num(row[5])
            elif '(ii)' in lbl:
                result['s311ii_taxable'] = _tbl_num(row[1])

    # ── Table 3.2: Inter-State Supplies ──────────────────────────────────────
    if t32_tbl:
        for row in t32_tbl:
            if not row:
                continue
            lbl = _tbl_label(row[0])
            if 'unregistered' in lbl:
                result['s32_unreg_taxable'] = _tbl_num(row[1])
                if len(row) > 2:
                    result['s32_unreg_igst'] = _tbl_num(row[2])
            elif 'composition' in lbl:
                result['s32_comp_taxable'] = _tbl_num(row[1])
            elif 'uin' in lbl or 'unique' in lbl:
                result['s32_uin_taxable'] = _tbl_num(row[1])

    # ── Table 4: ITC ─────────────────────────────────────────────────────────
    # Row labels we look for (col 0):
    #   "A. ITC Available..."   → section header (skip, no values)
    #   "(1) Import of goods"   → itc_a1_igst etc.
    #   "(5) All other ITC"     → itc_a5 (the main ITC bucket for domestic)
    #   "B. ITC Reversed"       → section header
    #   "(1) As per rules 42"   → reversed per Rule 42&43
    #   "(2) Others"            → reversed other
    #   "C. Net ITC available"  → NET ITC = the authoritative total
    #   "D. Ineligible ITC"     → ineligible section

    # Track A-section gross ITC and B-section reversals separately.
    # CRITICAL: itc_avail_igst must be GROSS (A total, before reversal) so that
    # the risk engine can correctly compute: reversal ratio = B / A,
    # and net ITC = A - B. Storing the C row (net) in itc_avail_igst causes
    # double-deduction in the risk engine.
    itc_a_igst = itc_a_cgst = itc_a_sgst = 0.0   # A-section gross sum
    itc_rev_igst = itc_rev_cgst = itc_rev_sgst = 0.0  # B-section sum
    in_avail_section    = True    # start in A section (before any header found)
    in_reversed_section = False
    in_d_section        = False

    for row in t4_rows:
        if not row or not any(row):
            continue
        lbl = _tbl_label(row[0])

        # ── Section boundary detection ────────────────────────────────────────
        # Monthly PDFs use "A. ITC Available"; annual PDFs use "(A) ITC Available"
        if 'a. itc available' in lbl or '(a) itc available' in lbl:
            in_avail_section = True
            in_reversed_section = False
            in_d_section = False
            continue

        # Monthly: "B. ITC Reversed"; annual: "(B) ITC Reversed"
        if 'b. itc reversed' in lbl or ('itc reversed' in lbl and 'b.' in lbl) or '(b) itc reversed' in lbl:
            in_avail_section = False
            in_reversed_section = True
            in_d_section = False
            continue

        if 'c. net itc' in lbl or ('net itc available' in lbl) or ('(a-b)' in lbl and 'net' in lbl):
            in_avail_section = False
            in_reversed_section = False
            in_d_section = False
            # Store C row as itc_igst_available (net, used for ITC-to-turnover ratio)
            result['itc_igst_available'] = _tbl_num(row[1])
            result['itc_cgst_available'] = _tbl_num(row[2])
            result['itc_sgst_available'] = _tbl_num(row[3])
            continue

        # Monthly: "D. Other Details"; annual: "(D) Ineligible ITC..."
        if (('d.' in lbl or '(d)' in lbl) and
                ('other details' in lbl or 'ineligible' in lbl or 'itc reclaimed' in lbl)):
            in_avail_section = False
            in_reversed_section = False
            in_d_section = True
            continue

        # Skip D-section rows (reclaimed ITC, ineligible ITC — not part of A or B)
        if in_d_section:
            continue

        # ── A-section: accumulate GROSS ITC available ─────────────────────────
        if in_avail_section:
            v_i = _tbl_num(row[1]) or 0
            v_c = _tbl_num(row[2]) or 0
            v_s = _tbl_num(row[3]) or 0
            # Only count rows that look like ITC sub-items (skip pure headers)
            if v_i or v_c or v_s:
                itc_a_igst += v_i
                itc_a_cgst += v_c
                itc_a_sgst += v_s

        # ── B-section: accumulate reversals ───────────────────────────────────
        elif in_reversed_section:
            v_i = _tbl_num(row[1]) or 0
            v_c = _tbl_num(row[2]) or 0
            v_s = _tbl_num(row[3]) or 0
            v_cess = (_tbl_num(row[4]) or 0) if len(row) > 4 else 0
            itc_rev_igst += v_i
            itc_rev_cgst += v_c
            itc_rev_sgst += v_s
            # Also split into 4(B)(1) rules 38/42/43 & 17(5) vs 4(B)(2) Others so
            # the MOM sub-columns are populated on the TABLE path too (the text
            # path already sets these; some layouts — e.g. Eden Reality Dec-2025 —
            # take only the table path, which previously left b1/b2 blank).
            if '(1)' in lbl or 'rule' in lbl or '17(5)' in lbl or '17 (5)' in lbl:
                result['itc_b1_igst'] = v_i or None
                result['itc_b1_cgst'] = v_c or None
                result['itc_b1_sgst'] = v_s or None
                result['itc_b1_cess'] = v_cess or None
            elif '(2)' in lbl or 'other' in lbl:
                result['itc_b2_igst'] = v_i or None
                result['itc_b2_cgst'] = v_c or None
                result['itc_b2_sgst'] = v_s or None
                result['itc_b2_cess'] = v_cess or None

    # Store GROSS ITC (A total) — this is the correct denominator for reversal ratio
    if itc_a_igst or itc_a_cgst or itc_a_sgst:
        result['itc_avail_igst'] = itc_a_igst or None
        result['itc_avail_cgst'] = itc_a_cgst or None
        result['itc_avail_sgst'] = itc_a_sgst or None

    # Store reversals (use None instead of 0 to distinguish "zero" from "not found")
    if itc_rev_igst or itc_rev_cgst or itc_rev_sgst:
        result['itc_reversed_igst'] = itc_rev_igst or None
        result['itc_reversed_cgst'] = itc_rev_cgst or None
        result['itc_reversed_sgst'] = itc_rev_sgst or None
    elif t4_rows:
        # Table 4 was found but reversals section had all zeros → explicitly zero
        result['itc_reversed_igst'] = 0.0
        result['itc_reversed_cgst'] = 0.0
        result['itc_reversed_sgst'] = 0.0

    # If A-section sum is still zero (e.g., older format where section header
    # was not recognised) fall back to C row + B sum = A gross
    if not result.get('itc_avail_igst') and result.get('itc_igst_available') is not None:
        c_i = result.get('itc_igst_available') or 0
        c_c = result.get('itc_cgst_available') or 0
        c_s = result.get('itc_sgst_available') or 0
        b_i = result.get('itc_reversed_igst') or 0
        b_c = result.get('itc_reversed_cgst') or 0
        b_s = result.get('itc_reversed_sgst') or 0
        a_i, a_c, a_s = c_i + b_i, c_c + b_c, c_s + b_s
        if a_i or a_c or a_s:
            result['itc_avail_igst'] = a_i or None
            result['itc_avail_cgst'] = a_c or None
            result['itc_avail_sgst'] = a_s or None

    # ── Table 6.1: Payment ────────────────────────────────────────────────────
    # Two known column layouts:
    #
    # OLD (9 cols):
    #   [0] Description  [1] Tax payable  [2] ITC IGST  [3] ITC CGST  [4] ITC SGST
    #   [5] ITC Cess  [6] Cash paid  [7] Interest cash  [8] Late fee cash
    #
    # NEW (11 cols, portal added "Adjustment of negative liability" + "Net Tax Payable"):
    #   [0] Description  [1] Tax payable  [2] Adjustment  [3] Net Tax Payable
    #   [4] ITC IGST  [5] ITC CGST  [6] ITC SGST  [7] ITC Cess
    #   [8] Cash paid  [9] Interest cash  [10] Late fee cash
    #
    # Row labels: "Integrated\ntax" | "Central\ntax" | "State/UT\ntax"

    if t61_tbl:
        # Column index offsets by format.
        # Column [1] = "Tax payable" (Table 6.1 Column (2) = total tax liability)
        # in BOTH the 9-col and 11-col layouts.
        _C_PAYABLE = 1
        if t61_ncols == 11:
            _C_ITC_IGST, _C_ITC_CGST, _C_ITC_SGST, _C_CASH = 4, 5, 6, 8
        else:  # 9-col (legacy)
            _C_ITC_IGST, _C_ITC_CGST, _C_ITC_SGST, _C_CASH = 2, 3, 4, 6

        in_section_b = False

        for row in t61_tbl:
            if len(row) < (_C_CASH + 1):
                continue
            lbl = _tbl_label(row[0])

            # Section boundary detection
            if '(b)' in lbl and 'reverse' in lbl:
                in_section_b = True
                continue
            if '(a)' in lbl and 'reverse' in lbl:
                in_section_b = False
                continue

            if 'integrated' in lbl and 'tax' in lbl and 'central' not in lbl:
                if not in_section_b:
                    result['itc_used_igst']     = _tbl_num(row[_C_ITC_IGST])
                    result['cash_paid_igst']    = _tbl_num(row[_C_CASH])
                    result['tax_payable_igst']  = _tbl_num(row[_C_PAYABLE])
                else:
                    result['cash_paid_rcm_igst'] = _tbl_num(row[_C_CASH])

            elif 'central' in lbl:
                if not in_section_b:
                    result['itc_used_cgst']     = _tbl_num(row[_C_ITC_CGST])
                    result['cash_paid_cgst']    = _tbl_num(row[_C_CASH])
                    result['tax_payable_cgst']  = _tbl_num(row[_C_PAYABLE])
                else:
                    result['cash_paid_rcm_cgst'] = _tbl_num(row[_C_CASH])

            elif 'state' in lbl or 'utgst' in lbl:
                if not in_section_b:
                    result['itc_used_sgst']     = _tbl_num(row[_C_ITC_SGST])
                    result['cash_paid_sgst']    = _tbl_num(row[_C_CASH])
                    result['tax_payable_sgst']  = _tbl_num(row[_C_PAYABLE])
                else:
                    result['cash_paid_rcm_sgst'] = _tbl_num(row[_C_CASH])

    logger.info(
        "[GSTR-3B][table] taxable=%s igst=%s itc_net=%s cash_igst=%s",
        result.get('taxable_sales'), result.get('igst_on_sales'),
        result.get('itc_igst_available'), result.get('cash_paid_igst'),
    )
    return result


def _gstr3b_table_fallback(data: Dict, tables: List) -> None:
    """Table-based fallback extraction for GSTR-3B missing fields."""
    all_rows: List[List[str]] = []
    for tbl in tables:
        all_rows.extend(_table_to_rows(tbl))

    for row in all_rows:
        row_text = " ".join(row).lower()

        # Taxable outward supplies
        if data["taxable_sales"] is None:
            if ("outward taxable" in row_text and "other than" in row_text) or \
               ("(a)" in row_text and "outward" in row_text):
                nums = _row_numbers(row)
                if nums:
                    data["taxable_sales"] = nums[0]
                    if len(nums) > 1: data["igst_on_sales"]  = data["igst_on_sales"]  or nums[1]
                    if len(nums) > 2: data["cgst_on_sales"]  = data["cgst_on_sales"]  or nums[2]
                    if len(nums) > 3: data["sgst_on_sales"]  = data["sgst_on_sales"]  or nums[3]
                    logger.info("[GSTR-3B][fallback] Found taxable_sales=%s from table", data["taxable_sales"])

        # Net ITC
        if data["itc_igst_available"] is None:
            if "net itc" in row_text or ("(c)" in row_text and "net" in row_text):
                nums = _row_numbers(row)
                if nums:
                    data["itc_igst_available"] = nums[0]
                    if len(nums) > 1: data["itc_cgst_available"] = nums[1]
                    if len(nums) > 2: data["itc_sgst_available"] = nums[2]
                    logger.info("[GSTR-3B][fallback] Found itc_igst_available=%s from table", data["itc_igst_available"])

        # Cash payment
        if data["cash_paid_igst"] is None:
            if "cash" in row_text and ("ledger" in row_text or "paid" in row_text):
                nums = _row_numbers(row)
                if nums:
                    data["cash_paid_igst"] = nums[0]
                    if len(nums) > 1: data["cash_paid_cgst"] = nums[1]
                    if len(nums) > 2: data["cash_paid_sgst"] = nums[2]

        # ITC payment
        if data["itc_used_igst"] is None:
            if "itc" in row_text and ("paid" in row_text or "credit" in row_text):
                nums = _row_numbers(row)
                if nums:
                    data["itc_used_igst"] = nums[0]
                    if len(nums) > 1: data["itc_used_cgst"] = nums[1]
                    if len(nums) > 2: data["itc_used_sgst"] = nums[2]

        # Interest/late fee
        if data["interest_paid"] is None and "interest" in row_text:
            nums = _row_numbers(row)
            if nums:
                data["interest_paid"] = nums[0]

        if data["late_fee_paid"] is None and "late fee" in row_text:
            nums = _row_numbers(row)
            if nums:
                data["late_fee_paid"] = nums[0]


# ── GSTR-1 Production Parser Helpers ─────────────────────────────────────────

def _norm(text: str) -> str:
    """Collapse all whitespace (including newlines) to single space — normalises PDF text."""
    return re.sub(r'\s+', ' ', text.replace("\r", "")).strip()


def _gstr1_parse_amount(val: str) -> float:
    """Safe numeric conversion from string — returns 0.0 on any failure."""
    try:
        return float(val.replace(",", ""))
    except Exception:
        return 0.0


def parse_amount(x) -> float:
    """
    Public-facing amount parser — handles Indian number format, ₹ symbol,
    commas, and any non-numeric garbage. Always returns float, never raises.
    """
    if x is None:
        return 0.0
    s = str(x).replace(",", "").replace("₹", "").replace(" ", "").strip()
    if not s or s in ("-", "–", "N/A", "NA", "NIL", "Nil", "nil", "--"):
        return 0.0
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def _normalize_gstr1_text(text: str) -> str:
    """
    Normalize variant section labels so section anchors match reliably.
    Call BEFORE section extraction — does NOT alter case (patterns use IGNORECASE).
    """
    t = text
    # B2CS variants
    t = re.sub(r"B2C\s*\(Others\)", "B2CS",   t, flags=re.IGNORECASE)
    t = re.sub(r"B2C\s+Small",      "B2CS",   t, flags=re.IGNORECASE)
    t = re.sub(r"B2C-Others",       "B2CS",   t, flags=re.IGNORECASE)
    t = re.sub(r"B2C\(Others\)",    "B2CS",   t, flags=re.IGNORECASE)
    # Nil / Exempt variants
    t = re.sub(r"Exempted\b",       "Exempt", t, flags=re.IGNORECASE)
    t = re.sub(r"Non\s+GST\b",      "NonGST", t, flags=re.IGNORECASE)
    t = re.sub(r"Non-GST\b",        "NonGST", t, flags=re.IGNORECASE)
    # CDN variants
    t = re.sub(r"Credit\s+Note",    "CreditNote", t, flags=re.IGNORECASE)
    t = re.sub(r"Debit\s+Note",     "DebitNote",  t, flags=re.IGNORECASE)
    return t


def _gstr1_extract_nums(text: str) -> List[str]:
    """
    Extract DECIMAL numbers only (must have .XX suffix).
    Intentionally excludes bare integers such as HSN codes (9954, 8421),
    invoice counts (5, 12), and GST rate % (18, 28) — preventing
    contamination of the tax column mapping.
    Negative sign supported (-12,81,21,444.19) for CDN credit notes.
    """
    return re.findall(r'-?\d[\d,]*\.\d{2}', text)


def _gstr1_map_cols(nums: List[str]) -> Dict[str, float]:
    """
    Map extracted decimal strings to GSTR-1 tax columns.

    Standard column order (4+): taxable_value, IGST, CGST, SGST [, Cess …]
    3-value fallback:           taxable, CGST, SGST  (B2CS intra-state, no IGST column)
    2-value fallback:           taxable, IGST
    Returns 0.0 defaults for any missing column — never raises.
    """
    vals = [_gstr1_parse_amount(n) for n in nums]
    result = {"taxable": 0.0, "igst": 0.0, "cgst": 0.0, "sgst": 0.0}
    if len(vals) >= 4:
        result["taxable"] = vals[0]
        result["igst"]    = vals[1]
        result["cgst"]    = vals[2]
        result["sgst"]    = vals[3]
    elif len(vals) == 3:
        # B2CS / intra-state: taxable, CGST, SGST (no IGST column present)
        result["taxable"] = vals[0]
        result["cgst"]    = vals[1]
        result["sgst"]    = vals[2]
    elif len(vals) == 2:
        result["taxable"] = vals[0]
        result["igst"]    = vals[1]
    elif len(vals) == 1:
        result["taxable"] = vals[0]
    return result


def _gstr1_map_cdn_cols(nums: List[str]) -> Dict[str, float]:
    """
    CDN-specific column mapper (CDNR / CDNUR).

    Column order: taxable, IGST, CGST, SGST [, Cess]
    Unlike B2CS, the 3-value fallback is interpreted as [taxable, IGST, CGST]
    — NOT [taxable, CGST, SGST] — because CDNs are typically inter-state.

    Post-mapping structural rules applied to the AGGREGATE total:
      • Pure IGST row (igst>0, cgst=sgst=0): keep as-is
      • Pure intra-state (cgst>0, igst=0): enforce CGST == SGST (mirror missing side)
      • Mixed (both igst>0 and cgst>0): valid aggregate; enforce CGST == SGST symmetry
      • All values are enforced NEGATIVE (credit notes reduce output liability)
    """
    vals = [_gstr1_parse_amount(n) for n in nums]
    result = {"taxable": 0.0, "igst": 0.0, "cgst": 0.0, "sgst": 0.0}

    if len(vals) >= 4:
        result["taxable"] = vals[0]
        result["igst"]    = vals[1]
        result["cgst"]    = vals[2]
        result["sgst"]    = vals[3]
    elif len(vals) == 3:
        # CDN 3-val: [taxable, IGST, CGST]  — NOT B2CS style
        result["taxable"] = vals[0]
        result["igst"]    = vals[1]
        result["cgst"]    = vals[2]
        # sgst stays 0.0; mirrored below if intra-state component detected
    elif len(vals) == 2:
        result["taxable"] = vals[0]
        result["igst"]    = vals[1]
    elif len(vals) == 1:
        result["taxable"] = vals[0]

    # ── Structural GST rules ──────────────────────────────────────────────────
    igst_abs = abs(result["igst"])
    cgst_abs = abs(result["cgst"])
    sgst_abs = abs(result["sgst"])

    if igst_abs > 0 and cgst_abs == 0 and sgst_abs == 0:
        # Pure inter-state CDN — correct, no-op
        pass
    elif cgst_abs > 0 and igst_abs == 0:
        # Pure intra-state CDN — zero IGST, enforce CGST == SGST
        result["igst"] = 0.0
        sym  = max(cgst_abs, sgst_abs)
        sign = -1 if result["cgst"] < 0 else 1
        result["cgst"] = sign * sym
        result["sgst"] = sign * sym
    elif igst_abs > 0 and cgst_abs > 0:
        # Mixed CDNs (inter + intra in same month) — valid aggregate
        # Enforce CGST == SGST symmetry for intra-state component
        if sgst_abs == 0 and cgst_abs > 0:
            result["sgst"] = result["cgst"]
        elif cgst_abs == 0 and sgst_abs > 0:
            result["cgst"] = result["sgst"]

    # ── Preserve each head's own net sign from the PDF ───────────────────────
    # The row is "Net off (Debit notes − Credit notes)". Each head nets
    # independently: a month can be net-credit overall (negative taxable) yet
    # net-debit on inter-state (positive IGST), or vice-versa. Do NOT force a
    # uniform sign — keep the signs exactly as reported so the columns reconcile
    # to the annual. (Old all-negative layouts are already negative, so unaffected.)
    return result


def _nil_row_amount(monetary_strs: List[str]) -> float:
    """
    Extract the supply value from a NIL/Exempt/Non-GST sub-row.

    GST portal PDFs show NIL rows as:
      [inter-state value]  [intra-state value]  [total]   → 3 values: take last
      [inter-state value]  [intra-state value]             → 2 values: sum both
      [total value only]                                   → 1 value:  use it

    Filters out 0.00 placeholders before counting.
    """
    amounts = [_gstr1_parse_amount(n) for n in monetary_strs
               if _gstr1_parse_amount(n) >= 0.01]
    if not amounts:
        return 0.0
    if len(amounts) >= 3:
        return amounts[-1]          # Last column = Total
    elif len(amounts) == 2:
        return amounts[0] + amounts[1]   # Inter-state + Intra-state
    else:
        return amounts[0]


def _gstr1_cdn_row(section_text: str) -> List[str]:
    """Return the decimals of a CDN section's grand-total data row.

    The 'Net off / Net Total' row holds every head (taxable, IGST, CGST, SGST,
    Cess) on ONE line, so reading that line directly is more robust than the
    300-char window heuristic in _gstr1_total_nums (which can clip a small head
    like a ₹647 CGST). Returns the first line carrying >= 2 decimal numbers.
    """
    for ln in section_text.split('\n'):
        d = _gstr1_extract_nums(ln)
        if len(d) >= 2:
            return d
    return []


def _gstr1_total_nums(section_text: str) -> List[str]:
    """
    Find the Grand Total / Total row in a section and return its decimal numbers.

    Scans ALL 'Total' occurrences in the normalised section text and picks the
    occurrence with the most decimal values (avoids false matches on column
    header labels like 'Total Qty', 'Total Value' which carry no decimal nums).

    Falls back to all decimal numbers in the section when no 'Total' keyword
    exists (handles compact summary PDFs where numbers appear on their own lines
    and the normaliser has already collapsed them into a single line).
    """
    norm = _norm(section_text)
    best: List[str] = []
    for m in re.finditer(r'(?:Grand\s+)?Total\b', norm, re.IGNORECASE):
        tail = norm[m.start(): m.start() + 300]
        nums = _gstr1_extract_nums(tail)
        if len(nums) > len(best):
            best = nums
    if best:
        return best
    # No Total keyword found — return every decimal number in the section
    return _gstr1_extract_nums(norm)


def extract_gstr1_sections(text: str) -> Dict[str, Any]:
    """
    Production-grade GSTR-1 section extractor.

    Strategy:
      - Uses existing _find_section() for reliable section boundary detection
      - Uses _gstr1_total_nums() with decimal-only regex to prevent
        HSN code / invoice count contamination of tax column mapping
      - Handles multi-line split rows via _norm() (collapses split lines)
      - Returns 0.0 defaults for every section — never crashes

    Extracts: B2B (4A/4B/6B/6C), B2CS (7), HSN Summary (12)
    B2CL is intentionally left to the existing extraction (DO NOT touch B2CL).
    """
    # Apply text normalization before extraction
    text = _normalize_gstr1_text(text)

    sections: Dict[str, Any] = {
        "b2b":   {"taxable": 0.0, "igst": 0.0, "cgst": 0.0, "sgst": 0.0},
        "b2cs":  {"taxable": 0.0, "igst": 0.0, "cgst": 0.0, "sgst": 0.0},
        "hsn":   {"taxable": 0.0, "igst": 0.0, "cgst": 0.0, "sgst": 0.0},
        # New sections
        "nil":   {"nil_rated": 0.0, "exempt": 0.0, "non_gst": 0.0},
        "cdnr":  {"taxable": 0.0, "igst": 0.0, "cgst": 0.0, "sgst": 0.0},
        "cdnur": {"taxable": 0.0, "igst": 0.0, "cgst": 0.0, "sgst": 0.0},
    }

    try:
        # ── B2B: Section 4A, 4B, 6B, 6C ──────────────────────────────────────
        sec_b2b = _find_section(
            text,
            r"4A,?\s*4B,?\s*6B,?\s*6C\s*[-–]\s*B2B",
            r"B2B.*Invoices.*Registered",
            r"4[AB].*B2B",
            end_patterns=[r"5A,?\s*5B", r"7\s*[-–]", r"9B\s*[-–]",
                          r"HSN.{0,10}[Ss]ummary", r"Exports"],
            max_chars=5000,
        )
        if sec_b2b:
            nums = _gstr1_total_nums(sec_b2b)
            data = _gstr1_map_cols(nums)
            if data["taxable"] > 0:
                sections["b2b"] = data
                logger.info("[GSTR-1][sections] B2B: taxable=%s igst=%s cgst=%s sgst=%s",
                            data["taxable"], data["igst"], data["cgst"], data["sgst"])
            else:
                logger.warning("[GSTR-1][sections] B2B section found but no taxable value extracted")

        # ── B2CS: Section 7 ───────────────────────────────────────────────────
        sec_b2cs = _find_section(
            text,
            r"7\s*[-–]\s*B2C.*Others",
            r"7\s*[-–]\s*B2C\s*\(Others\)",
            r"B2C.*Small|B2CS",
            # Anchor the section-8 boundary to "8 - Nil" — a bare r"8\s*[-–]"
            # matches "8 -" INSIDE decimals (e.g. "1,23,062.28 -50,815") and
            # truncates the data row, dropping the IGST/CGST heads.
            end_patterns=[r"9B\s*[-–]", r"HSN", r"Credit.*Note", r"8\s*[-–]\s*Nil"],
            max_chars=3000,
        )
        if sec_b2cs:
            # Read the data row directly (robust to small/mixed-sign heads).
            nums = _gstr1_cdn_row(sec_b2cs) or _gstr1_total_nums(sec_b2cs)
            data = _gstr1_map_cols(nums)
            if data["taxable"] > 0:
                sections["b2cs"] = data
                logger.info("[GSTR-1][sections] B2CS: taxable=%s igst=%s cgst=%s sgst=%s",
                            data["taxable"], data["igst"], data["cgst"], data["sgst"])

        # ── HSN Summary: Section 12 (authoritative totals) ───────────────────
        sec_hsn = _find_section(
            text,
            r"12\s*[-–]\s*HSN",
            r"HSN.{0,30}[Ss]ummary",
            r"HSN.*Outward\s+Supply",
            end_patterns=[r"13\s*[-–]", r"Verification", r"Documents\s+Issued"],
            max_chars=5000,
        )
        if sec_hsn:
            nums_raw = _gstr1_total_nums(sec_hsn)
            # Filter sub-1000 values (e.g. decimal qty like "100.00") to prevent
            # column shift where qty lands in taxable slot and shifts igst/cgst/sgst.
            nums_filtered = [n for n in nums_raw if abs(_gstr1_parse_amount(n)) >= 1000]
            nums = nums_filtered if nums_filtered else nums_raw
            data = _gstr1_map_cols(nums)
            # Accept negative totals too: a credit-note-only month (e.g. only a
            # 9B CDN) has a net-negative Table-12 HSN total (e.g. −1,712.71).
            if data["taxable"] != 0:
                sections["hsn"] = data
                logger.info("[GSTR-1][sections] HSN: taxable=%s igst=%s cgst=%s sgst=%s",
                            data["taxable"], data["igst"], data["cgst"], data["sgst"])
            else:
                # Fallback: monetary filter for one-value-per-line summary PDFs
                # (decimal-only regex already excludes HSN codes — safe to use)
                all_dec  = _gstr1_extract_nums(_norm(sec_hsn))
                monetary = [n for n in all_dec if abs(_gstr1_parse_amount(n)) >= 1000]
                if len(monetary) >= 2:
                    data = _gstr1_map_cols(monetary)
                    sections["hsn"] = data
                    logger.info("[GSTR-1][sections] HSN (fallback): taxable=%s igst=%s cgst=%s sgst=%s",
                                data["taxable"], data["igst"], data["cgst"], data["sgst"])
                else:
                    logger.warning("[GSTR-1][sections] HSN section found but no extractable totals")

        # ── NIL / EXEMPT / NON-GST: Section 8 ───────────────────────────────
        sec_nil = _find_section(
            text,
            r"8\s*[-–]\s*Nil",
            r"Nil\s+rated,?\s+exempted\s+and\s+non\s+GST",
            r"Nil\s+Rated.*Exempt",
            r"Nil\s+Rated\s+Supplies",
            r"Nil.*Exempt.*Non",
            end_patterns=[r"9[AB]\s*[-–]", r"10\s*[-–]", r"HSN", r"Credit.*Note",
                          r"Advance", r"Amendment"],
            max_chars=3000,
        )
        if sec_nil:
            logger.debug("[GSTR-1][sections] NIL section found (%d chars)", len(sec_nil))

            # ── Structural per-keyword sub-row detection ───────────────────────
            # For each sub-type we scan ALL lines and keep the FIRST matching
            # data line that actually contains monetary values.  We explicitly
            # skip lines where the keyword appears only as a column header
            # (those lines have no decimal numbers).
            #
            # Value extraction uses _nil_row_amount() which handles:
            #   1 value  → use directly
            #   2 values → sum (inter-state + intra-state, no total column)
            #   3+ values→ take last (total column)

            def _nil_line_value(label_pat: str, exclude_line: Optional[str] = None) -> float:
                for ln in sec_nil.split("\n"):
                    if not re.search(label_pat, ln, re.IGNORECASE):
                        continue
                    if exclude_line and ln == exclude_line:
                        continue
                    nums = _gstr1_extract_nums(_norm(ln))
                    val  = _nil_row_amount(nums)
                    if val > 0.0:
                        return val
                    # Values might be on the NEXT line (wrapped PDF layout)
                    # (handled via Fallback A/B below if still 0)
                return 0.0

            # "Nil Rated" row
            nil_val = _nil_line_value(r"nil\s+rated")
            if nil_val > 0.0:
                sections["nil"]["nil_rated"] = nil_val

            # "Exempt" / "Exempted" row
            exempt_val = _nil_line_value(r"\bexempt")
            if exempt_val > 0.0:
                sections["nil"]["exempt"] = exempt_val

            # "Non-GST" / "NonGST" row
            nongst_val = _nil_line_value(r"non.?gst|nongst")
            if nongst_val > 0.0:
                sections["nil"]["non_gst"] = nongst_val

            # ── Fallback A: Total row with exactly 3 decimal values ───────────
            # Some PDFs show: Nil Rated | Exempt | Non-GST in ONE Total row
            if all(v == 0.0 for v in sections["nil"].values()):
                total_line = _find_line_with_labels(sec_nil, r"total")
                if total_line:
                    nums = _gstr1_extract_nums(_norm(total_line))
                    amts = [_gstr1_parse_amount(n) for n in nums
                            if _gstr1_parse_amount(n) >= 0.01]
                    if len(amts) == 3:
                        sections["nil"]["nil_rated"] = amts[0]
                        sections["nil"]["exempt"]    = amts[1]
                        sections["nil"]["non_gst"]   = amts[2]
                    elif len(amts) == 2:
                        sections["nil"]["nil_rated"] = amts[0]
                        sections["nil"]["exempt"]    = amts[1]
                    elif len(amts) == 1:
                        sections["nil"]["nil_rated"] = amts[0]

            # ── Fallback B: all decimals in section ───────────────────────────
            if all(v == 0.0 for v in sections["nil"].values()):
                all_nums = _gstr1_extract_nums(_norm(sec_nil))
                amts = [_gstr1_parse_amount(n) for n in all_nums
                        if _gstr1_parse_amount(n) >= 0.01]
                if len(amts) >= 3:
                    sections["nil"]["nil_rated"] = amts[0]
                    sections["nil"]["exempt"]    = amts[1]
                    sections["nil"]["non_gst"]   = amts[2]
                elif len(amts) >= 1:
                    sections["nil"]["nil_rated"] = amts[0]

            logger.info("[GSTR-1][sections] NIL: nil_rated=%s exempt=%s non_gst=%s",
                        sections["nil"]["nil_rated"], sections["nil"]["exempt"],
                        sections["nil"]["non_gst"])
            print("[NIL STRUCTURED] nil_rated={:.2f} exempt={:.2f} non_gst={:.2f}".format(
                sections["nil"]["nil_rated"], sections["nil"]["exempt"],
                sections["nil"]["non_gst"]))

        # ── CDNR: Section 9B/10 — Credit/Debit Notes Registered ──────────────
        # Use word-boundary anchors so r"CDNR\b" does NOT match "CDNUR".
        # In PDFs where 9B = CDNUR, the "Unregistered" end-pattern clips this
        # section short immediately, producing no data — which is correct.
        sec_cdnr = _find_section(
            text,
            r"9B\s*[-–]\s*CDNR\b",                    # exact: no CDNUR false-match
            r"10\s*[-–]\s*CDNR\b",                    # some PDF formats use section 10
            r"CDNR\b",                                 # word boundary: no CDNUR match
            # Old 2-column portal layout: "9B - Credit / Debit Notes (Registered)"
            # has NO "CDNR" acronym. The parenthesised "(Registered)" uniquely
            # distinguishes it from "(Unregistered)" without a fragile lookahead.
            r"Credit\s*/?\s*Debit\s*Notes?\s*\(\s*Registered\s*\)",
            r"Credit.*Debit.*Notes.*Registered(?!.*Unregistered)",
            # NOTE: do NOT use loose r"10\s*[-–]" / r"11\s*[-–]" here — they match
            # "10 -" inside decimals like "647.10 -647.10" and truncate the data
            # row mid-line. 9B is bounded by 9C / the Unregistered block / HSN.
            end_patterns=[r"9C\s*[-–]", r"9B\s*[-–].*Unregistered",
                          r"\(\s*Unregistered\s*\)", r"HSN", r"Advance",
                          r"Unregistered"],
            max_chars=3000,
        )
        if sec_cdnr:
            logger.debug("[GSTR-1][sections] CDNR section found (%d chars)", len(sec_cdnr))
            # Drop "IP Address: x.x.x.x" lines — they leak spurious decimals.
            sec_cdnr_clean = re.sub(r'(?im)^.*IP\s*Address.*$', '', sec_cdnr)
            # Old 2-column portal layout has an extra leading "Total Note value"
            # column before "Total Taxable value". Skip it so the amount we keep is
            # the TAXABLE base (consistent with the newer format's "Value" column).
            _note_col = bool(re.search(r'note\s*value', sec_cdnr_clean, re.IGNORECASE))
            # Read the data row directly (robust to small heads); fall back to the
            # window scan only if no single-line row is found.
            cdnr_nums = _gstr1_cdn_row(sec_cdnr_clean) or _gstr1_total_nums(sec_cdnr_clean)
            if _note_col and len(cdnr_nums) >= 2:
                cdnr_nums = cdnr_nums[1:]   # drop Note value → first value becomes Taxable
            cdnr_data = _gstr1_map_cdn_cols(cdnr_nums)   # CDN-specific: 3-val=[taxable,IGST,CGST]
            if cdnr_data["taxable"] != 0.0:   # negative CDN values are valid
                sections["cdnr"] = cdnr_data
                # Structural validation prints
                _cdnr_igst  = cdnr_data["igst"]
                _cdnr_cgst  = cdnr_data["cgst"]
                _cdnr_sgst  = cdnr_data["sgst"]
                _sym_ok  = abs(abs(_cdnr_cgst) - abs(_cdnr_sgst)) < 0.02
                _igst_ok = not (abs(_cdnr_igst) > 0 and abs(_cdnr_cgst) > 0 and not _sym_ok)
                print(f"[CDNR STRUCTURED] taxable={cdnr_data['taxable']:.2f}"
                      f" igst={_cdnr_igst:.2f} cgst={_cdnr_cgst:.2f} sgst={_cdnr_sgst:.2f}")
                print(f"[CDNR CHECK] CGST==SGST: {'OK' if _sym_ok else 'MISMATCH'}"
                      f"  IGST_XOR_CGST_valid: {'OK' if _igst_ok else 'MIXED-REVIEW'}")
                logger.info("[GSTR-1][sections] CDNR: taxable=%s igst=%s cgst=%s sgst=%s",
                            cdnr_data["taxable"], cdnr_data["igst"],
                            cdnr_data["cgst"], cdnr_data["sgst"])

        # ── CDNUR: Section 9B/9C — Credit/Debit Notes Unregistered ──────────
        # GST portal PDFs label CDNUR as "9B - Credit/DebitNotes (Unregistered)"
        # (confirmed via keyword dump). 9C in these PDFs = CDNRA/CDNURA (amendments).
        # Keep 9C as fallback for older PDF formats where 9C = CDNUR.
        sec_cdnur = _find_section(
            text,
            r"9B\s*[-–].*Unregistered",   # primary: 9B = CDNUR in GST portal PDFs
            r"9C\s*[-–].*Unregistered",   # fallback: older format where 9C = CDNUR
            r"CDNUR",
            r"Credit.*Debit.*Notes.*Unregistered",
            end_patterns=[r"9C\s*[-–]", r"10\s*[-–]", r"11\s*[-–]", r"12\s*[-–]",
                          r"HSN", r"Advance"],
            max_chars=3000,
        )
        if sec_cdnur:
            logger.debug("[GSTR-1][sections] CDNUR section found (%d chars)", len(sec_cdnur))
            print(f"[CDNUR RAW SEC first 600 chars]:\n{sec_cdnur[:600]}\n[END CDNUR RAW]")
            cdnur_nums = _gstr1_total_nums(sec_cdnur)
            print(f"[CDNUR NUMS extracted]: {cdnur_nums}")
            # Filter noise values — valid CDNUR amounts are always >= 1000 (GST transaction
            # amounts). Small decimals like 115.96 / 111.1 are section-boundary artifacts.
            # If NOTHING survives the filter, treat as no real CDNUR data (pass empty list
            # so the mapper returns zeros) — do NOT fall back to the noisy original.
            cdnur_nums_clean = [n for n in cdnur_nums if abs(_gstr1_parse_amount(n)) >= 1000]
            # Old layout: skip leading "Total Note value" column → keep Taxable base.
            if re.search(r'note\s*value', sec_cdnur, re.IGNORECASE) and len(cdnur_nums_clean) >= 2:
                cdnur_nums_clean = cdnur_nums_clean[1:]
            cdnur_data = _gstr1_map_cdn_cols(cdnur_nums_clean)   # empty list → all-zero row
            # CDNUR structural fix:
            # All CDNUR types (B2CL, EXPWP, EXPWOP) are inter-state — CGST/SGST must
            # always be 0. IGST and CGST+SGST are mutually exclusive under GST law.
            # Also: if |IGST| ≈ |Taxable|, the taxable value was read twice by the
            # 300-char window scan and mapped as IGST — zero IGST too in that case.
            if (abs(cdnur_data["igst"]) > 0 and
                    abs(abs(cdnur_data["igst"]) - abs(cdnur_data["taxable"])) < 1.0):
                cdnur_data["igst"] = 0.0
                print("[CDNUR FIX] Cleared spurious IGST — equaled Taxable (parsing artifact)")
            # Always enforce CGST = SGST = 0 for CDNUR (always inter-state)
            cdnur_data["cgst"] = 0.0
            cdnur_data["sgst"] = 0.0
            if cdnur_data["taxable"] != 0.0:   # negative CDN values are valid
                sections["cdnur"] = cdnur_data
                _cdnur_igst = cdnur_data["igst"]
                _cdnur_cgst = cdnur_data["cgst"]
                _cdnur_sgst = cdnur_data["sgst"]
                _sym_ok2 = abs(abs(_cdnur_cgst) - abs(_cdnur_sgst)) < 0.02
                print(f"[CDNUR STRUCTURED] taxable={cdnur_data['taxable']:.2f}"
                      f" igst={_cdnur_igst:.2f} cgst={_cdnur_cgst:.2f} sgst={_cdnur_sgst:.2f}")
                print(f"[CDNUR CHECK] CGST==SGST: {'OK' if _sym_ok2 else 'MISMATCH'}")
                logger.info("[GSTR-1][sections] CDNUR: taxable=%s igst=%s cgst=%s sgst=%s",
                            cdnur_data["taxable"], cdnur_data["igst"],
                            cdnur_data["cgst"], cdnur_data["sgst"])

    except Exception as exc:
        logger.warning("[GSTR-1][sections] extract_gstr1_sections error: %s", exc)

    return sections


# ── GSTR-1 Table-based extractor ─────────────────────────────────────────────

def _parse_gstr1_tables(tables: List) -> Dict[str, Any]:
    """
    Table-based GSTR-1 extractor — works with pdfplumber grid output.

    GSTR-1 table structure (all formats from FY 2018 onwards):
      B2B   — 6 cols: Records | Invoice | Taxable | IGST | CGST | SGST
      B2CL  — 5 cols: Records | Invoice | Taxable | IGST | Cess  (no CGST/SGST — inter-state)
      CDNR  — 7 cols: Records | Note value | Taxable | IGST | CGST | SGST | Cess
      CDNUR — 5 cols: Records | Note value | Taxable | IGST | Cess
      Nil   — 4 cols: Records | Nil amount | Exempt | Non-GST
      B2CS  — 7 cols: Records | Invoice | Taxable | IGST | CGST | SGST | Cess  (first such table)
      HSN   — 7 cols: Records | Invoice | Taxable | IGST | CGST | SGST | Cess  (last such table = largest)
      Exports — 4 cols: Records | Invoice | Taxable | IGST

    Called before the text parser so reliable table data takes precedence.
    Returns a dict of field-name → value (None if not found).
    """
    result: Dict[str, Any] = {}

    # We'll collect all 7-col "invoice+central+state" tables in order — first = B2CS, last = HSN
    seven_col_tables: List[Dict] = []

    for tbl in tables:
        if not tbl or len(tbl) < 2:
            continue
        ncols   = max(len(r) for r in tbl)
        hdr     = ' '.join(_tbl_label(c) for c in (tbl[0] or []))
        data_row = tbl[1]  # values are always in row index 1

        def _n(col_idx):
            try:
                return _tbl_num(data_row[col_idx])
            except IndexError:
                return None

        # ── B2B (6 cols: Records|Invoice|Taxable|IGST|CGST|SGST) ────────────
        if ncols == 6 and 'central' in hdr and 'state' in hdr and 'invoice' in hdr and 'note' not in hdr:
            t = _n(2)
            if t is not None:
                result['b2b_taxable_value'] = t
                result['b2b_igst']          = _n(3)
                result['b2b_cgst']          = _n(4)
                result['b2b_sgst']          = _n(5)

        # ── B2CL (5 cols: Records|Invoice|Taxable|IGST|Cess — NO central/state) ──
        elif (ncols == 5 and 'integrated' in hdr and 'central' not in hdr
              and 'note' not in hdr and 'invoice' in hdr):
            t = _n(2)
            if t is not None:
                result['b2cl_taxable_value'] = t
                result['b2cl_igst']          = _n(3)

        # ── CDNR (7 cols: Records|Note value|Taxable|IGST|CGST|SGST|Cess) ──
        elif ncols == 7 and 'note value' in hdr and 'central' in hdr:
            t = _n(2)
            if t is not None:
                result['cdnr_taxable'] = t
                result['cdn_value']    = t   # keep cdn_value in sync
                result['cdnr_igst']    = _n(3)
                result['cdnr_cgst']    = _n(4)
                result['cdnr_sgst']    = _n(5)

        # ── CDNUR (5 cols: Records|Note value|Taxable|IGST|Cess — no central) ──
        elif ncols == 5 and 'note value' in hdr and 'integrated' in hdr and 'central' not in hdr:
            t = _n(2)
            if t is not None:
                result['cdnur_taxable'] = t
                result['cdnur_igst']    = _n(3)

        # ── Nil/Exempt/Non-GST (4 cols with nil/exempt keywords) ─────────────
        elif ncols == 4 and ('nil' in hdr or 'exempt' in hdr or 'non-gst' in hdr or 'non gst' in hdr):
            result['nil_taxable_value'] = _n(1)
            result['nil_exempt']        = _n(2)
            result['nil_non_gst']       = _n(3)

        # ── Exports (4 cols: Records|Invoice|Taxable|IGST — no central/state) ──
        elif (ncols == 4 and 'integrated' in hdr and 'invoice' in hdr
              and 'central' not in hdr and 'nil' not in hdr and 'note' not in hdr):
            t = _n(2)
            if t is not None:
                result['export_taxable_value'] = t
                result['export_igst']          = _n(3)

        # ── B2CS / HSN (7 cols: Records|Invoice|Taxable|IGST|CGST|SGST|Cess) ──
        elif ncols == 7 and 'invoice' in hdr and 'central' in hdr and 'note' not in hdr:
            t = _n(2)
            if t is not None:
                seven_col_tables.append({
                    'taxable': t,
                    'igst': _n(3), 'cgst': _n(4), 'sgst': _n(5),
                })

    # Among 7-col tables: the LARGEST taxable = HSN (covers all supplies)
    # Remaining ones = supply sub-types (B2CS, amendments, etc.)
    if seven_col_tables:
        seven_col_tables.sort(key=lambda x: x['taxable'] or 0, reverse=True)
        hsn = seven_col_tables[0]
        result['total_taxable_value'] = hsn['taxable']
        result['total_igst']          = hsn['igst']
        result['total_cgst']          = hsn['cgst']
        result['total_sgst']          = hsn['sgst']
        # Second-largest = B2CS (if it exists and is significantly smaller than HSN)
        if len(seven_col_tables) >= 2:
            b2cs = seven_col_tables[1]
            # Only assign as B2CS if it's clearly a sub-table (< 95% of HSN total)
            if b2cs['taxable'] and hsn['taxable'] and b2cs['taxable'] < hsn['taxable'] * 0.95:
                if result.get('b2cs_taxable_value') is None:
                    result['b2cs_taxable_value'] = b2cs['taxable']
                    result['b2cs_igst']          = b2cs['igst']
                    result['b2cs_cgst']          = b2cs['cgst']
                    result['b2cs_sgst']          = b2cs['sgst']

    return result


def _gstr1_is_annual_summary(text: str) -> bool:
    """Detect the GSTR-1/IFF 'System generated summary' (annual/consolidated) format.

    This format has an extra 'Total Invoice Value' (or 'Total Note Value') column
    BEFORE 'Total Taxable Value', which shifts every value in the generic parsers.
    """
    return bool(re.search(r'system\s+generated\s+summary', text, re.IGNORECASE))


def _gstr1_decimals(line: str) -> List[float]:
    """Extract only DECIMAL numbers (e.g. 76,06,03,613.40) from a line.

    Decimal-only on purpose: it drops the integer record count (e.g. '3200') and
    stray watermark digits, so positional column mapping stays aligned. Keeps
    explicit zeros like '0.00'. Negatives (credit notes) supported.
    """
    out = []
    for m in re.findall(r'-?\d[\d,]*\.\d{1,2}', line):
        try:
            out.append(float(m.replace(',', '')))
        except ValueError:
            pass
    return out


def _gstr1_annual_row(lines: List[str], anchor_re: str) -> List[float]:
    """Find a section by its (table-number) anchor and return its data-row decimals.

    Handles BOTH summary layouts:
      • Old IFF: <anchor> / 'No. of Records Total Invoice value Total Taxable...' / <data>
      • New:     <anchor> / 'Total <n> Invoice|Net Value|Note <values...>'
    The caller applies a per-format offset to pick the Taxable column.
    """
    for i, ln in enumerate(lines):
        if not re.search(anchor_re, ln, re.IGNORECASE):
            continue
        window = lines[i + 1: i + 16]
        # Old layout: data row sits right after the 'No. of Records' column header.
        for j, w in enumerate(window):
            if re.search(r'No\.\s*of\s*Records', w, re.IGNORECASE):
                for w2 in window[j + 1:]:
                    d = _gstr1_decimals(w2)
                    if len(d) >= 1:
                        return d
                break
        # New layout: data row is the 'Total ...' / 'Net Total ...' line.
        for w in window:
            if re.search(r'\b(?:Total|Net)\b', w, re.IGNORECASE):
                d = _gstr1_decimals(w)
                if len(d) >= 1:
                    return d
        # Fallback: first line carrying decimals.
        for w in window:
            d = _gstr1_decimals(w)
            if len(d) >= 1:
                return d
        break
    return []


# Signature of the OLD compact GSTR-1 summary layout (≈FY 2020-21 / 2021-22 portal
# PDFs): B2B, SEZ and Deemed Export are collapsed into ONE combined row.
_LEGACY_A_SIG = re.compile(r'4A,\s*4B,\s*6B,\s*6C\s*[-–]\s*B2B', re.IGNORECASE)


def _parse_gstr1_legacy_summary(text: str) -> Dict[str, Any]:
    """Isolated reader for the OLD compact GSTR-1 summary layout (FY≈2020-21/21-22).

    Every table is one header line followed by a single data row shaped:
        <records> <invoice-value|NA> <taxable> <igst> [<cgst> <sgst>] <cess>
    so the TAXABLE amount is ALWAYS the 3rd whitespace token. This is robust to
    (a) integer-valued columns that the decimal-only annual reader drops (which
    shifted B2CL onto its IGST), and (b) a literal "NA" in the invoice column
    (which shifted the HSN total onto its IGST on FY21-22).

    B2B/SEZ/DE are physically merged in this layout and cannot be split — the
    combined taxable is stored in b2b_taxable_value with legacy_combined_b2b=True
    so B2B-level risk ratios can exclude these years. Table 12 (HSN) total is the
    authoritative turnover and reconciles exactly.
    """
    def _num(tok):
        try:
            return float(tok.replace(',', ''))
        except (ValueError, AttributeError):
            return None

    def _row(label):
        i = text.find(label)
        if i < 0:
            return None
        for ln in text[i + len(label): i + 600].split('\n'):
            s = ln.strip()
            if not s or 'IP Address' in s:
                continue
            if re.match(r'^[A-Za-z]$', s):                 # watermark letter (L/A/N/I/F)
                continue
            if re.search(r'No\.\s*of|Total\s+(?:Invoice|Note|Nil|Exempt|Integrated|Records)'
                         r'|Description|Type', s, re.IGNORECASE):
                continue
            toks = s.split()
            if toks and re.match(r'^\d+$', toks[0]) and len(toks) >= 2:
                return toks
        return None

    def _tax(label, idx=2):
        t = _row(label)
        return _num(t[idx]) if t and len(t) > idx else None

    out: Dict[str, Any] = {}
    comb = _row(r"4A, 4B, 6B, 6C")                          # B2B + SEZ + DE (merged)
    if comb and len(comb) > 2:
        out["b2b_taxable_value"] = _num(comb[2])
        out["b2b_igst"] = _num(comb[3]) if len(comb) > 3 else 0.0
        out["b2b_cgst"] = _num(comb[4]) if len(comb) > 4 else 0.0
        out["b2b_sgst"] = _num(comb[5]) if len(comb) > 5 else 0.0

    b2cl = _row(r"5A, 5B")                                  # Records Inv Taxable IGST Cess
    if b2cl and len(b2cl) > 2:
        out["b2cl_taxable_value"] = _num(b2cl[2])
        out["b2cl_igst"] = _num(b2cl[3]) if len(b2cl) > 3 else 0.0
        out["b2cl_cgst"] = 0.0
        out["b2cl_sgst"] = 0.0

    b2cs = _row(r"7 - B2C (Others)")                        # Records Inv Taxable IGST CGST SGST Cess
    if b2cs and len(b2cs) > 2:
        out["b2cs_taxable_value"] = _num(b2cs[2])
        out["b2cs_igst"] = _num(b2cs[3]) if len(b2cs) > 3 else 0.0
        out["b2cs_cgst"] = _num(b2cs[4]) if len(b2cs) > 4 else 0.0
        out["b2cs_sgst"] = _num(b2cs[5]) if len(b2cs) > 5 else 0.0

    exp = _row(r"6A - Exports")                             # Records Inv Taxable IGST
    if exp and len(exp) > 2:
        out["exp_expwp_taxable"] = _num(exp[2])

    nil = _row(r"8 - Nil")                                  # Records Nil Exempt Non-GST
    if nil and len(nil) > 3:
        out["nil_taxable_value"] = _num(nil[1])
        out["nil_exempt"] = _num(nil[2])
        out["nil_non_gst"] = _num(nil[3])

    for lbl, base in ((r"9B - Credit / Debit Notes (Registered)", "cdnr"),
                      (r"9B - Credit / Debit Notes (Unregistered)", "cdnur")):
        r = _row(lbl)                                       # Records NoteValue Taxable ...
        if r and len(r) > 2:
            out[f"{base}_taxable"] = _num(r[2])
            if base == "cdnr":
                out["cdn_value"] = _num(r[2])

    hsn = _row(r"12 - HSN")                                 # Records Inv Taxable IGST CGST SGST Cess
    if hsn and len(hsn) > 2:
        out["total_taxable_value"] = _num(hsn[2])
        out["total_igst"] = _num(hsn[3]) if len(hsn) > 3 else 0.0
        out["total_cgst"] = _num(hsn[4]) if len(hsn) > 4 else 0.0
        out["total_sgst"] = _num(hsn[5]) if len(hsn) > 5 else 0.0

    return {k: v for k, v in out.items() if v is not None}


def _parse_gstr1_annual_summary(text: str) -> Dict[str, Any]:
    """Positional parser for the GSTR-1/IFF "System generated summary" formats.

    Two known layouts:
      A) old IFF — has a leading 'Total Invoice value' column before 'Total
         Taxable value'  → Taxable is the 2nd decimal of the data row.
      B) newer    — single 'Value (₹)' column (Value == Taxable)
         → Taxable is the 1st decimal of the data row.
    Sections are anchored on TABLE NUMBERS (4A, 5A, 6A, 6C, 7, 8, 9B, 12) so a
    watermark mangling the label text (e.g. 'B2MB') can't break extraction.
    """
    lines = text.split('\n')
    fmt_a = bool(re.search(r'Total\s+Invoice\s+value', text, re.IGNORECASE)
                 and re.search(r'Total\s+Taxable\s+value', text, re.IGNORECASE))
    t = 1 if fmt_a else 0   # index of the Taxable column among the data-row decimals
    out: Dict[str, Any] = {}

    def col(d, idx):
        return d[idx] if 0 <= idx < len(d) else None

    # 4A B2B Regular
    d = _gstr1_annual_row(lines, r"\b4A\b\s*[-–,]")
    if len(d) > t:
        out["b2b_taxable_value"] = col(d, t)
        out["b2b_igst"]  = col(d, t + 1)
        out["b2b_cgst"]  = col(d, t + 2)
        out["b2b_sgst"]  = col(d, t + 3)

    # 5A/5B B2C (Large)
    d = _gstr1_annual_row(lines, r"\b5A\b\s*[-–,]")
    if len(d) > t:
        out["b2cl_taxable_value"] = col(d, t)
        out["b2cl_igst"] = col(d, t + 1)
        out["b2cl_cgst"] = 0.0
        out["b2cl_sgst"] = 0.0

    # 7 B2C (Others) = B2CS
    d = _gstr1_annual_row(lines, r"\b7\s*[-–]")
    if len(d) > t:
        out["b2cs_taxable_value"] = col(d, t)
        out["b2cs_igst"] = col(d, t + 1)
        out["b2cs_cgst"] = col(d, t + 2)
        out["b2cs_sgst"] = col(d, t + 3)

    # 9B CDNR (Registered) — has a leading Note Value column ONLY in layout A
    d = _gstr1_annual_row(lines, r"9B.*\(\s*Registered\s*\)|9B.*[-–]\s*CDNR\b")
    if len(d) > t:
        out["cdnr_taxable"] = col(d, t); out["cdn_value"] = col(d, t)
        out["cdnr_igst"] = col(d, t + 1)
        out["cdnr_cgst"] = col(d, t + 2)
        out["cdnr_sgst"] = col(d, t + 3)

    # 9B CDNUR (Unregistered)
    d = _gstr1_annual_row(lines, r"9B.*\(\s*Unregistered\s*\)|9B.*CDNUR")
    if len(d) > t:
        out["cdnur_taxable"] = col(d, t)
        out["cdnur_igst"] = col(d, t + 1)
        out["cdnur_cgst"] = 0.0
        out["cdnur_sgst"] = 0.0

    # 6A Exports
    d = _gstr1_annual_row(lines, r"\b6A\b\s*[-–]")
    if len(d) > t:
        out["export_taxable_value"] = col(d, t)

    # 6C Deemed Exports
    d = _gstr1_annual_row(lines, r"\b6C\b\s*[-–]")
    if len(d) > t:
        out["de_taxable"] = col(d, t)

    # 8 Nil/Exempt/Non-GST — no leading value column in either layout
    d = _gstr1_annual_row(lines, r"\b8\s*[-–].*Nil")
    if d:
        out["nil_taxable_value"] = col(d, 0)
        out["nil_exempt"]  = col(d, 1) if len(d) > 1 else 0.0
        out["nil_non_gst"] = col(d, 2) if len(d) > 2 else 0.0

    # 12 HSN summary = authoritative total turnover
    d = _gstr1_annual_row(lines, r"\b12\s*[-–].*HSN")
    if len(d) > t:
        out["total_taxable_value"] = col(d, t)
        out["total_igst"] = col(d, t + 1)
        out["total_cgst"] = col(d, t + 2)
        out["total_sgst"] = col(d, t + 3)

    logger.info("[GSTR-1][annual-summary fmt=%s] b2b=%s b2cl=%s b2cs=%s cdnr=%s total=%s",
                "A" if fmt_a else "B", out.get("b2b_taxable_value"),
                out.get("b2cl_taxable_value"), out.get("b2cs_taxable_value"),
                out.get("cdnr_taxable"), out.get("total_taxable_value"))
    return {k: v for k, v in out.items() if v is not None}


# ── GSTR-1 Parser (TEXT-BASED, SECTION-AWARE) ─────────────────────────────────

def parse_gstr1(text: str, tables: List[List[List]]) -> Dict[str, Any]:
    """
    Parse GSTR-1 using keyword-based section detection.

    Sections:
      4A, 4B, 6B, 6C  — B2B Invoices (registered taxpayers)
      5A, 5B           — B2C Large
      7                — B2C Others (Small)
      9B               — Credit/Debit Notes Registered
      12               — HSN-wise Summary → AUTHORITATIVE final sales
    """
    # Strip "IP Address: x.x.x.x" metadata lines up front — when a section (esp.
    # empty amendment tables 9C/10/11B) is read, the IP octets (e.g. 115.96,
    # 111.10) otherwise leak in as spurious taxable/IGST values.
    text = re.sub(r'(?im)^.*IP\s*Address.*$', '', text)

    data: Dict[str, Any] = {
        "form_type": "GSTR-1",
        # True for the GSTR-1/IFF "System generated summary" (annual/consolidated)
        # reference file — excluded from MOM totals and from risk-ratio aggregation
        # so it is never double-counted on top of the monthly returns.
        "is_annual_summary": _gstr1_is_annual_summary(text),
        "gstin": _extract_gstin(text),
        "legal_name": _extract_legal_name(text),
        "period": _extract_period(text),
        # B2B
        "b2b_invoice_count": None,
        "b2b_taxable_value": None,
        "b2b_igst": None,
        "b2b_cgst": None,
        "b2b_sgst": None,
        "b2b_cess": None,
        # B2CL
        "b2cl_taxable_value": None,
        "b2cl_igst": None,
        "b2cl_cgst": None,
        "b2cl_sgst": None,
        # B2CS (intra-state small; IGST is 0 for pure intra-state but may be non-zero
        # for inter-state supplies to unregistered persons — extract actual value)
        "b2cs_taxable_value": None,
        "b2cs_igst": None,
        "b2cs_cgst": None,
        "b2cs_sgst": None,
        # Nil / Exempt / Non-GST
        "nil_taxable_value": None,   # used by export route → nil_rated
        "nil_exempt": None,
        "nil_non_gst": None,
        # CDN (backward-compat keys kept; cdnr_* aliases added below)
        "cdn_count": None,
        "cdn_value": None,
        "cdn_igst": None,
        "cdn_cgst": None,
        "cdn_sgst": None,
        # CDNR (standardised keys — aliases of cdn_*)
        "cdnr_taxable": None,
        "cdnr_igst": None,
        "cdnr_cgst": None,
        "cdnr_sgst": None,
        # CDNUR
        "cdnur_taxable": None,
        "cdnur_igst": None,
        "cdnur_cgst": None,
        "cdnur_sgst": None,
        # Exports
        "export_value": None,
        "export_igst": None,
        # Advance
        "advance_received": None,
        "advance_adjusted": None,
        # HSN totals (authoritative)
        "total_taxable_value": None,
        "total_igst": None,
        "total_cgst": None,
        "total_sgst": None,
        "total_cess": None,
        # ── NEW: 4B B2B Reverse Charge ───────────────────────────────────────
        "b2b_rcm_taxable": None, "b2b_rcm_igst": None,
        "b2b_rcm_cgst": None,   "b2b_rcm_sgst": None,
        # ── NEW: 6A Exports (EXPWP / EXPWOP) ────────────────────────────────
        "exp_expwp_taxable": None, "exp_expwp_igst": None,
        "exp_expwop_taxable": None,
        # ── NEW: 6B SEZ (SEZWP / SEZWOP) ────────────────────────────────────
        "sez_sezwp_taxable": None, "sez_sezwp_igst": None,
        "sez_sezwop_taxable": None,
        # ── NEW: 6C Deemed Exports ───────────────────────────────────────────
        "de_taxable": None, "de_igst": None, "de_cgst": None, "de_sgst": None,
        # ── NEW: 9A Amendments ───────────────────────────────────────────────
        "amend_b2b_taxable": None, "amend_b2b_igst": None,
        "amend_b2b_cgst": None,    "amend_b2b_sgst": None,
        "amend_b2cl_taxable": None, "amend_b2cl_igst": None,
        "amend_exp_taxable": None,  "amend_exp_igst": None,
        "amend_sez_taxable": None,  "amend_sez_igst": None,
        "amend_de_taxable": None,   "amend_de_igst": None,
        # ── NEW: 9C CDNRA / CDNURA ───────────────────────────────────────────
        "cdnra_taxable": None, "cdnra_igst": None,
        "cdnra_cgst": None,    "cdnra_sgst": None,
        "cdnura_taxable": None, "cdnura_igst": None,
        # ── NEW: 10 B2CS Amendments ──────────────────────────────────────────
        "amend_b2cs_taxable": None, "amend_b2cs_igst": None,
        "amend_b2cs_cgst": None,    "amend_b2cs_sgst": None,
        # ── NEW: 11A Advances Received ───────────────────────────────────────
        "adv_recv_taxable": None, "adv_recv_igst": None,
        "adv_recv_cgst": None,    "adv_recv_sgst": None,
        # ── NEW: 11B Advances Adjusted ───────────────────────────────────────
        "adv_adj_taxable": None, "adv_adj_igst": None,
        "adv_adj_cgst": None,    "adv_adj_sgst": None,
        # ── NEW: 13 Documents Issued ─────────────────────────────────────────
        "docs_issued_count": None,
        # ── NEW: 14 E-Commerce u/s 52 ────────────────────────────────────────
        "eco_taxable": None, "eco_igst": None,
        "eco_cgst": None,    "eco_sgst": None,
        # ── NEW: 14A Amendments to Table 14 ─────────────────────────────────
        "eco_amend_taxable": None, "eco_amend_igst": None,
        # ── NEW: 15 Supplies u/s 9(5) ────────────────────────────────────────
        "s95_taxable": None, "s95_igst": None,
        "s95_cgst": None,    "s95_sgst": None,
        # ── NEW: 15A(I) Amendments u/s 9(5) Registered ───────────────────────
        "s95a1_taxable": None, "s95a1_igst": None,
        "s95a1_cgst": None,    "s95a1_sgst": None,
        # ── NEW: 15A(II) Amendments u/s 9(5) Unregistered ────────────────────
        "s95a2_taxable": None, "s95a2_igst": None,
        "_parse_warnings": [],
    }

    logger.info("[GSTR-1] Parsing started. Text length=%d", len(text))

    # ── Table-based pass (PRIMARY — more reliable than text for all PDF formats) ──
    # Run first so reliable grid values are pre-populated; text parser fills gaps.
    _tbl_pre: Dict[str, Any] = {}
    if tables:
        _tbl_pre = _parse_gstr1_tables(tables)
        # Pre-populate data with table results; text parser may refine below
        for _k, _v in _tbl_pre.items():
            if _v is not None and data.get(_k) is None:
                data[_k] = _v
        logger.info("[GSTR-1][table] b2b=%s b2cl=%s cdnr=%s hsn=%s",
                    _tbl_pre.get('b2b_taxable_value'), _tbl_pre.get('b2cl_taxable_value'),
                    _tbl_pre.get('cdnr_taxable'), _tbl_pre.get('total_taxable_value'))

    # ── Production section extraction (B2B, B2CS, HSN) ──────────────────────
    # Uses decimal-only number extraction to prevent HSN code / count contamination.
    # B2CL is handled separately below (DO NOT touch B2CL pair logic).
    sections = extract_gstr1_sections(text)
    print("GSTR1 DEBUG:", sections)

    # ── B2B: map from sections ────────────────────────────────────────────────
    b2b = sections["b2b"]
    if b2b["taxable"] > 0:
        data["b2b_taxable_value"] = b2b["taxable"]
        data["b2b_igst"]          = b2b["igst"]
        data["b2b_cgst"]          = b2b["cgst"]
        data["b2b_sgst"]          = b2b["sgst"]
        logger.info("[GSTR-1] B2B mapped: taxable=%s igst=%s cgst=%s sgst=%s",
                    b2b["taxable"], b2b["igst"], b2b["cgst"], b2b["sgst"])
    else:
        logger.warning("[GSTR-1] B2B section NOT found or zero values")
        data["_parse_warnings"].append("B2B section (4A, 4B, 6B, 6C) not found")

    # ── B2CL Section (5A, 5B) ─────────────────────────────────────────────────
    sec_b2cl = _find_section(
        text,
        r"5A,?\s*5B\s*[-–]\s*B2C.*Large",
        r"B2C.*\(Large\)",
        r"5[AB].*B2C",
        r"B2CL",
        r"5A\s*[-–].*[Ll]arge",
        r"5A\s*[-–].*[Uu]nregistered",
        r"[Ii]nter.?[Ss]tate.*[Uu]nregistered",
        r"5A\s*[-–]",
        # End BEFORE 6A Exports — prevents zero-only export rows from contaminating
        # the Total-row picker (which selects the row with most decimal values).
        end_patterns=[r"6A\s*[-–]", r"6A\b", r"[Ee]xports", r"7\s*[-–]",
                      r"9B\s*[-–]", r"HSN", r"B2CS", r"Others"],
        max_chars=3000,
    )

    if not sec_b2cl:
        print("[B2CL DEBUG] Section NOT FOUND. Searching raw text for '5A':", repr(text[max(0, text.lower().find('5a')-20): text.lower().find('5a')+100]) if '5a' in text.lower() else "NO '5A' IN TEXT")

    if sec_b2cl:
        logger.debug("[GSTR-1] B2CL section found")
        print("[B2CL DEBUG] Section found. First 300 chars:", repr(sec_b2cl[:300]))
        # Use decimal-only extraction (_gstr1_extract_nums) to skip bare-integer
        # invoice counts (9, 11, 12…) — monetary amounts always have .XX decimals.
        norm_b2cl = _norm(sec_b2cl)
        print("[B2CL DEBUG] Norm text:", repr(norm_b2cl[:300]))
        dec_nums  = _gstr1_total_nums(sec_b2cl)           # decimal-only, Total-row preferred
        print("[B2CL DEBUG] dec_nums:", dec_nums)
        if dec_nums:
            # Accept ALL decimal numbers (x.xx format already excludes bare integers
            # like invoice counts — the regex requires a decimal point).
            b2cl_vals = [_gstr1_parse_amount(n) for n in dec_nums]
            if len(b2cl_vals) >= 2:
                data["b2cl_taxable_value"] = b2cl_vals[0]
                data["b2cl_igst"]          = b2cl_vals[1]
            elif len(b2cl_vals) == 1:
                data["b2cl_taxable_value"] = b2cl_vals[0]
            logger.info("[GSTR-1] B2CL: taxable=%s igst=%s",
                        data["b2cl_taxable_value"], data["b2cl_igst"])
        else:
            # Last-resort: all decimal numbers anywhere in the section
            all_dec   = _gstr1_extract_nums(norm_b2cl)
            all_vals  = [_gstr1_parse_amount(n) for n in all_dec]
            if len(all_vals) >= 2:
                data["b2cl_taxable_value"] = all_vals[0]
                data["b2cl_igst"]          = all_vals[1]
            elif len(all_vals) == 1:
                data["b2cl_taxable_value"] = all_vals[0]
            logger.info("[GSTR-1] B2CL (fallback): taxable=%s", data["b2cl_taxable_value"])

    # ── B2CL fallback: line-scanner for summary-table format ─────────────────
    # Monthly GST portal PDFs often render each section as ONE ROW in a summary
    # table (no sub-pages, no "Total" keyword). The entire B2CL data sits on the
    # "5A, 5B" line: "5A, 5B  B2C Large  1,96,52,311.80  19,80,000.00  0.00 ..."
    if not data.get("b2cl_taxable_value"):
        for line in text.split("\n"):
            nl = _norm(line)
            if re.search(r'5[AB].*?(B2C|Large|B2CL)', nl, re.IGNORECASE):
                nums = _gstr1_extract_nums(nl)
                monetary = [n for n in nums if _gstr1_parse_amount(n) >= 100]
                if monetary:
                    data["b2cl_taxable_value"] = _gstr1_parse_amount(monetary[0])
                    data["b2cl_igst"]          = _gstr1_parse_amount(monetary[1]) if len(monetary) >= 2 else 0.0
                    print("[B2CL FALLBACK] line-scanner hit:", nl[:200])
                    print("[B2CL FALLBACK] monetary nums:", monetary)
                    break

    # ── B2CS: map from sections ───────────────────────────────────────────────
    b2cs = sections["b2cs"]
    if b2cs["taxable"] > 0:
        data["b2cs_taxable_value"] = b2cs["taxable"]
        data["b2cs_igst"]          = b2cs["igst"]   # 0.0 for intra-state; non-zero for inter-state B2CS
        data["b2cs_cgst"]          = b2cs["cgst"] if b2cs["cgst"] else None
        data["b2cs_sgst"]          = b2cs["sgst"] if b2cs["sgst"] else None
        # CRITICAL: intra-state CGST == SGST always; mirror if one side missing
        if data["b2cs_cgst"] and not data["b2cs_sgst"]:
            data["b2cs_sgst"] = data["b2cs_cgst"]
            logger.info("[GSTR-1] B2CS SGST mirrored from CGST=%s", data["b2cs_cgst"])
        elif data["b2cs_sgst"] and not data["b2cs_cgst"]:
            data["b2cs_cgst"] = data["b2cs_sgst"]
            logger.info("[GSTR-1] B2CS CGST mirrored from SGST=%s", data["b2cs_sgst"])
        logger.info("[GSTR-1] B2CS mapped: taxable=%s cgst=%s sgst=%s",
                    b2cs["taxable"], data["b2cs_cgst"], data["b2cs_sgst"])

    # ── NIL / EXEMPT / NON-GST: map from sections — always 0.0, never None ──
    nil_sec = sections["nil"]
    data["nil_taxable_value"] = nil_sec["nil_rated"]   # 0.0 when not found
    data["nil_exempt"]        = nil_sec["exempt"]
    data["nil_non_gst"]       = nil_sec["non_gst"]
    logger.info("[GSTR-1] NIL mapped: nil_rated=%s exempt=%s non_gst=%s",
                nil_sec["nil_rated"], nil_sec["exempt"], nil_sec["non_gst"])

    # ── Credit/Debit Notes (9B) ────────────────────────────────────────────────
    sec_cdn = _find_section(
        text,
        r"9B\s*[-–]\s*Credit.*Debit",
        r"Credit.*Debit.*Notes.*Registered",
        r"CDNR|CDN.*Registered",
        end_patterns=[r"10\s*[-–]", r"11\s*[-–]", r"HSN", r"Exports", r"Advance"],
        max_chars=3000,
    )

    # Priority: use section extractor results (CDNR) if available
    cdnr_sec = sections.get("cdnr", {})
    if cdnr_sec.get("taxable", 0.0) != 0.0:   # negative CDN values are valid
        data["cdn_value"]    = cdnr_sec["taxable"]
        data["cdn_igst"]     = cdnr_sec["igst"]
        data["cdn_cgst"]     = cdnr_sec["cgst"]
        data["cdn_sgst"]     = cdnr_sec["sgst"]
        data["cdnr_taxable"] = cdnr_sec["taxable"]
        data["cdnr_igst"]    = cdnr_sec["igst"]
        data["cdnr_cgst"]    = cdnr_sec["cgst"]
        data["cdnr_sgst"]    = cdnr_sec["sgst"]
        logger.info("[GSTR-1] CDNR from sections: taxable=%s igst=%s cgst=%s sgst=%s",
                    cdnr_sec["taxable"], cdnr_sec["igst"], cdnr_sec["cgst"], cdnr_sec["sgst"])
    elif sec_cdn:
        # Fallback to legacy CDN section text parsing
        logger.debug("[GSTR-1] CDN section found (legacy path)")
        total_line = _find_line_with_labels(sec_cdn, r"Total")
        if total_line:
            nums = _numbers_from_line(total_line)
            if len(nums) >= 2:
                # count, taxable_value, IGST, CGST, SGST
                if nums[0] == int(nums[0]) and nums[0] < 100000:
                    data["cdn_count"] = int(nums[0])
                    data["cdn_value"] = nums[1] if len(nums) > 1 else None
                    if len(nums) >= 3: data["cdn_igst"] = nums[2]
                    if len(nums) >= 4: data["cdn_cgst"] = nums[3]
                    if len(nums) >= 5: data["cdn_sgst"] = nums[4]
                else:
                    data["cdn_value"] = nums[0]
                    if len(nums) >= 2: data["cdn_igst"] = nums[1]
                    if len(nums) >= 3: data["cdn_cgst"] = nums[2]
                    if len(nums) >= 4: data["cdn_sgst"] = nums[3]
            elif len(nums) == 1:
                data["cdn_value"] = nums[0]
        # Mirror cdn_* → cdnr_*
        data["cdnr_taxable"] = data["cdn_value"]
        data["cdnr_igst"]    = data["cdn_igst"]
        data["cdnr_cgst"]    = data["cdn_cgst"]
        data["cdnr_sgst"]    = data["cdn_sgst"]
    else:
        logger.warning("[GSTR-1] CDN/CDNR section NOT found")

    # ── CDNUR: map from sections ──────────────────────────────────────────────
    cdnur_sec = sections.get("cdnur", {})
    if cdnur_sec.get("taxable", 0.0) != 0.0:   # negative CDN values are valid
        data["cdnur_taxable"] = cdnur_sec["taxable"]
        data["cdnur_igst"]    = cdnur_sec["igst"]
        data["cdnur_cgst"]    = cdnur_sec["cgst"]
        data["cdnur_sgst"]    = cdnur_sec["sgst"]
        logger.info("[GSTR-1] CDNUR mapped: taxable=%s igst=%s",
                    cdnur_sec["taxable"], cdnur_sec["igst"])

    # ── Enforce 0.0 defaults for all CDN GST fields (never leave None) ───────
    for k in ("cdn_igst", "cdn_cgst", "cdn_sgst",
              "cdnr_taxable", "cdnr_igst", "cdnr_cgst", "cdnr_sgst",
              "cdnur_taxable", "cdnur_igst", "cdnur_cgst", "cdnur_sgst"):
        if data[k] is None:
            data[k] = 0.0

    # ── Helper: grab decimal nums from the first Total/Grand Total line in a section ──
    def _sec_nums(sec):
        return _gstr1_total_nums(sec) if sec else []

    def _sec_first_nums(sec, label_pat):
        """Return decimal nums from first line matching label_pat in sec."""
        if not sec:
            return []
        for ln in sec.split("\n"):
            if re.search(label_pat, ln, re.IGNORECASE):
                ns = _gstr1_extract_nums(_norm(ln))
                if ns:
                    return ns
        return []

    # ── 4B — B2B RCM (Reverse Charge) ────────────────────────────────────────
    sec_4b = _find_section(
        text,
        r"4B\s*[-–].*reverse\s*charge",
        r"4B.*RCM|reverse\s*charge.*4B",
        r"B2B.*Reverse\s*Charge",
        end_patterns=[r"5A\s*[-–]", r"6A\s*[-–]", r"7\s*[-–]", r"9B\s*[-–]", r"HSN"],
        max_chars=2000,
    )
    if sec_4b:
        _nums4b = _sec_nums(sec_4b)
        _cols4b = _gstr1_map_cols(_nums4b)
        if _cols4b["taxable"] > 0:
            data["b2b_rcm_taxable"] = _cols4b["taxable"]
            data["b2b_rcm_igst"]    = _cols4b["igst"]
            data["b2b_rcm_cgst"]    = _cols4b["cgst"]
            data["b2b_rcm_sgst"]    = _cols4b["sgst"]
            logger.info("[GSTR-1] 4B RCM: taxable=%s igst=%s", _cols4b["taxable"], _cols4b["igst"])

    # ── 6A — Exports (EXPWP / EXPWOP) ────────────────────────────────────────
    sec_6a = _find_section(
        text,
        r"6A\s*[-–].*[Ee]xport",
        r"[Ee]xports.*6A",
        r"Zero\s+Rated.*[Ee]xport",
        end_patterns=[r"6B\s*[-–]", r"6C\s*[-–]", r"7\s*[-–]", r"9B\s*[-–]", r"HSN", r"B2CS"],
        max_chars=3000,
    )
    if sec_6a:
        # EXPWP row (with payment of tax)
        _expwp_ns = _sec_first_nums(sec_6a, r"EXPWP|with\s*payment")
        if not _expwp_ns:
            _expwp_ns = _sec_first_nums(sec_6a, r"with.*payment.*tax")
        if _expwp_ns and len(_expwp_ns) >= 1:
            data["exp_expwp_taxable"] = _gstr1_parse_amount(_expwp_ns[0])
            if len(_expwp_ns) >= 2:
                data["exp_expwp_igst"] = _gstr1_parse_amount(_expwp_ns[1])
        # EXPWOP row (without payment)
        _expwop_ns = _sec_first_nums(sec_6a, r"EXPWOP|without\s*payment")
        if not _expwop_ns:
            _expwop_ns = _sec_first_nums(sec_6a, r"without.*payment")
        if _expwop_ns and len(_expwop_ns) >= 1:
            data["exp_expwop_taxable"] = _gstr1_parse_amount(_expwop_ns[0])
        # If no sub-rows found, fall back to total row as EXPWP
        if data["exp_expwp_taxable"] is None:
            _exp_total = _sec_nums(sec_6a)
            _exp_cols  = _gstr1_map_cols(_exp_total)
            if _exp_cols["taxable"] > 0:
                data["exp_expwp_taxable"] = _exp_cols["taxable"]
                data["exp_expwp_igst"]    = _exp_cols["igst"]
        logger.info("[GSTR-1] 6A Exports EXPWP=%s EXPWOP=%s",
                    data["exp_expwp_taxable"], data["exp_expwop_taxable"])
    elif data["export_value"] is not None:
        # Use existing export parse as EXPWP fallback
        data["exp_expwp_taxable"] = data["export_value"]
        data["exp_expwp_igst"]    = data["export_igst"]

    # ── 6B — SEZ (SEZWP / SEZWOP) ────────────────────────────────────────────
    sec_6b = _find_section(
        text,
        r"6B\s*[-–].*SEZ",
        r"SEZ.*6B",
        r"Supply.*SEZ.*payment",
        end_patterns=[r"6C\s*[-–]", r"7\s*[-–]", r"9B\s*[-–]", r"HSN", r"B2CS"],
        max_chars=2000,
    )
    if sec_6b:
        _sezwp_ns = _sec_first_nums(sec_6b, r"SEZWP|with\s*payment")
        if _sezwp_ns and len(_sezwp_ns) >= 1:
            data["sez_sezwp_taxable"] = _gstr1_parse_amount(_sezwp_ns[0])
            if len(_sezwp_ns) >= 2:
                data["sez_sezwp_igst"] = _gstr1_parse_amount(_sezwp_ns[1])
        _sezwop_ns = _sec_first_nums(sec_6b, r"SEZWOP|without\s*payment")
        if _sezwop_ns and len(_sezwop_ns) >= 1:
            data["sez_sezwop_taxable"] = _gstr1_parse_amount(_sezwop_ns[0])
        if data["sez_sezwp_taxable"] is None:
            _sez_total = _sec_nums(sec_6b)
            _sez_cols  = _gstr1_map_cols(_sez_total)
            if _sez_cols["taxable"] > 0:
                data["sez_sezwp_taxable"] = _sez_cols["taxable"]
                data["sez_sezwp_igst"]    = _sez_cols["igst"]
        logger.info("[GSTR-1] 6B SEZ SEZWP=%s SEZWOP=%s",
                    data["sez_sezwp_taxable"], data["sez_sezwop_taxable"])

    # ── 6C — Deemed Exports ───────────────────────────────────────────────────
    sec_6c = _find_section(
        text,
        r"6C\s*[-–].*[Dd]eemed",
        r"[Dd]eemed\s+[Ee]xport",
        end_patterns=[r"7\s*[-–]", r"9B\s*[-–]", r"HSN", r"B2CS"],
        max_chars=2000,
    )
    if sec_6c:
        _de_total = _sec_nums(sec_6c)
        _de_cols  = _gstr1_map_cols(_de_total)
        if _de_cols["taxable"] > 0:
            data["de_taxable"] = _de_cols["taxable"]
            data["de_igst"]    = _de_cols["igst"]
            data["de_cgst"]    = _de_cols["cgst"]
            data["de_sgst"]    = _de_cols["sgst"]
        logger.info("[GSTR-1] 6C DE: taxable=%s", data["de_taxable"])

    # ── 9A — Amendments ───────────────────────────────────────────────────────
    sec_9a = _find_section(
        text,
        r"9A\s*[-–]",
        r"Amended\s+B2B|Amendment.*B2B",
        r"9A\s*[-–].*[Aa]mend",
        end_patterns=[r"9B\s*[-–]", r"10\s*[-–]", r"11\s*[-–]", r"HSN"],
        max_chars=5000,
    )
    if sec_9a:
        # B2B Amended
        _a_b2b = _sec_first_nums(sec_9a, r"B2B|registered.*person")
        if _a_b2b:
            _c = _gstr1_map_cols(_a_b2b)
            data["amend_b2b_taxable"] = _c["taxable"] or None
            data["amend_b2b_igst"]    = _c["igst"]    or None
            data["amend_b2b_cgst"]    = _c["cgst"]    or None
            data["amend_b2b_sgst"]    = _c["sgst"]    or None
        # B2CL Amended
        _a_b2cl = _sec_first_nums(sec_9a, r"B2CL|large.*unregistered")
        if _a_b2cl:
            _c = _gstr1_map_cols(_a_b2cl)
            data["amend_b2cl_taxable"] = _c["taxable"] or None
            data["amend_b2cl_igst"]    = _c["igst"]    or None
        # Exports Amended
        _a_exp = _sec_first_nums(sec_9a, r"[Ee]xport|EXPWP|EXPWOP")
        if _a_exp:
            _c = _gstr1_map_cols(_a_exp)
            data["amend_exp_taxable"] = _c["taxable"] or None
            data["amend_exp_igst"]    = _c["igst"]    or None
        # SEZ Amended
        _a_sez = _sec_first_nums(sec_9a, r"SEZ|SEZWP|SEZWOP")
        if _a_sez:
            _c = _gstr1_map_cols(_a_sez)
            data["amend_sez_taxable"] = _c["taxable"] or None
            data["amend_sez_igst"]    = _c["igst"]    or None
        # DE Amended
        _a_de = _sec_first_nums(sec_9a, r"[Dd]eemed")
        if _a_de:
            _c = _gstr1_map_cols(_a_de)
            data["amend_de_taxable"] = _c["taxable"] or None
            data["amend_de_igst"]    = _c["igst"]    or None
        logger.info("[GSTR-1] 9A Amendments: amend_b2b=%s amend_b2cl=%s",
                    data["amend_b2b_taxable"], data["amend_b2cl_taxable"])

    # ── 9C — CDNRA / CDNURA ───────────────────────────────────────────────────
    sec_9c = _find_section(
        text,
        r"9C\s*[-–].*CDNR",
        r"Amended.*CDN.*Registered",
        r"9C\s*[-–].*[Aa]mend",
        end_patterns=[r"10\s*[-–]", r"11\s*[-–]", r"HSN"],
        max_chars=3000,
    )
    if sec_9c:
        # CDNRA (Registered)
        _cdnra_ns = _sec_first_nums(sec_9c, r"CDNRA|Registered.*[Aa]mend|[Aa]mend.*Registered")
        if not _cdnra_ns:
            _cdnra_ns = _sec_nums(sec_9c)
        if _cdnra_ns:
            _c = _gstr1_map_cdn_cols(_cdnra_ns)
            if _c["taxable"] != 0.0:
                data["cdnra_taxable"] = _c["taxable"]
                data["cdnra_igst"]    = _c["igst"]
                data["cdnra_cgst"]    = _c["cgst"]
                data["cdnra_sgst"]    = _c["sgst"]
        # CDNURA (Unregistered) — may be in same or separate section
        _cdnura_ns = _sec_first_nums(sec_9c, r"CDNURA|Unregistered.*[Aa]mend|[Aa]mend.*Unregistered")
        if _cdnura_ns:
            _c2 = _gstr1_map_cdn_cols(_cdnura_ns)
            if _c2["taxable"] != 0.0:
                data["cdnura_taxable"] = _c2["taxable"]
                data["cdnura_igst"]    = _c2["igst"]
        logger.info("[GSTR-1] 9C CDNRA=%s CDNURA=%s",
                    data["cdnra_taxable"], data["cdnura_taxable"])

    # Also try a separate CDNURA section
    if data["cdnura_taxable"] is None:
        sec_9c2 = _find_section(
            text,
            r"9C\s*[-–].*Unregistered",
            r"CDNURA",
            r"Amended.*CDN.*Unregistered",
            end_patterns=[r"10\s*[-–]", r"11\s*[-–]", r"HSN"],
            max_chars=2000,
        )
        if sec_9c2:
            _ns = _sec_nums(sec_9c2)
            _ns_clean = [n for n in _ns if abs(_gstr1_parse_amount(n)) >= 1000]
            _c3 = _gstr1_map_cdn_cols(_ns_clean or _ns)
            if _c3["taxable"] != 0.0:
                data["cdnura_taxable"] = _c3["taxable"]
                data["cdnura_igst"]    = _c3["igst"]

    # ── 10 — B2CS Amendments ──────────────────────────────────────────────────
    sec_10 = _find_section(
        text,
        r"10\s*[-–].*B2CS|10\s*[-–].*[Aa]mend.*B2C",
        r"B2CS.*[Aa]mend|[Aa]mended.*B2C.*[Oo]ther",
        end_patterns=[r"11\s*[-–]", r"9A\s*[-–]", r"HSN"],
        max_chars=2000,
    )
    if sec_10:
        _ns10 = _sec_nums(sec_10)
        _c10  = _gstr1_map_cols(_ns10)
        if _c10["taxable"] > 0 or abs(_c10["igst"]) > 0:
            data["amend_b2cs_taxable"] = _c10["taxable"] or None
            data["amend_b2cs_igst"]    = _c10["igst"]    or None
            data["amend_b2cs_cgst"]    = _c10["cgst"]    or None
            data["amend_b2cs_sgst"]    = _c10["sgst"]    or None
        logger.info("[GSTR-1] 10 B2CS Amend: taxable=%s", data["amend_b2cs_taxable"])

    # ── 11A — Advance Tax Paid ────────────────────────────────────────────────
    sec_11a = _find_section(
        text,
        r"11[Aa]\s*[-–]",
        r"11A\s*[\(\[]?1[\)\]]?\s*[-–]",
        r"[Aa]dvance.*[Tt]ax.*[Pp]aid|[Tt]ax\s+[Pp]aid.*[Aa]dvance",
        end_patterns=[r"11B\s*[-–]", r"11[Bb]", r"12\s*[-–]", r"HSN"],
        max_chars=2000,
    )
    if sec_11a:
        _ns11a = _sec_nums(sec_11a)
        _c11a  = _gstr1_map_cols(_ns11a)
        if _c11a["taxable"] > 0:
            data["adv_recv_taxable"] = _c11a["taxable"]
            data["adv_recv_igst"]    = _c11a["igst"]    or None
            data["adv_recv_cgst"]    = _c11a["cgst"]    or None
            data["adv_recv_sgst"]    = _c11a["sgst"]    or None
        logger.info("[GSTR-1] 11A Advance Recv: taxable=%s", data["adv_recv_taxable"])

    # ── 11B — Advance Tax Adjusted ────────────────────────────────────────────
    sec_11b = _find_section(
        text,
        r"11[Bb]\s*[-–]",
        r"11B\s*[\(\[]?1[\)\]]?\s*[-–]",
        r"[Aa]dvance.*[Aa]djusted|[Aa]djustment.*[Aa]dvance",
        end_patterns=[r"12\s*[-–]", r"13\s*[-–]", r"HSN"],
        max_chars=2000,
    )
    if sec_11b:
        _ns11b = _sec_nums(sec_11b)
        _c11b  = _gstr1_map_cols(_ns11b)
        if _c11b["taxable"] > 0:
            data["adv_adj_taxable"] = _c11b["taxable"]
            data["adv_adj_igst"]    = _c11b["igst"]    or None
            data["adv_adj_cgst"]    = _c11b["cgst"]    or None
            data["adv_adj_sgst"]    = _c11b["sgst"]    or None
        logger.info("[GSTR-1] 11B Advance Adj: taxable=%s", data["adv_adj_taxable"])

    # ── 13 — Documents Issued ─────────────────────────────────────────────────
    sec_13 = _find_section(
        text,
        r"13\s*[-–].*[Dd]ocument",
        r"[Dd]ocuments?\s+[Ii]ssued",
        end_patterns=[r"14\s*[-–]", r"15\s*[-–]", r"HSN", r"Verification"],
        max_chars=3000,
    )
    if sec_13:
        # Look for the Total row; count of docs is integer so skip decimals filter
        for ln in sec_13.split("\n"):
            if re.search(r"\bTotal\b", ln, re.IGNORECASE):
                bare_ints = re.findall(r"\b(\d+)\b", ln)
                if bare_ints:
                    try:
                        data["docs_issued_count"] = int(bare_ints[-1])
                    except ValueError:
                        pass
                break
        logger.info("[GSTR-1] 13 Docs: count=%s", data["docs_issued_count"])

    # ── 14 — E-Commerce u/s 52 ────────────────────────────────────────────────
    sec_14 = _find_section(
        text,
        r"14\s*[-–].*[Ee]-?[Cc]ommerce",
        r"[Ee]-?[Cc]ommerce.*52|[Ss]ection\s*52",
        end_patterns=[r"14A\s*[-–]", r"15\s*[-–]", r"HSN", r"Verification"],
        max_chars=2000,
    )
    if sec_14:
        _ns14 = _sec_nums(sec_14)
        _c14  = _gstr1_map_cols(_ns14)
        if _c14["taxable"] > 0:
            data["eco_taxable"] = _c14["taxable"]
            data["eco_igst"]    = _c14["igst"]    or None
            data["eco_cgst"]    = _c14["cgst"]    or None
            data["eco_sgst"]    = _c14["sgst"]    or None
        logger.info("[GSTR-1] 14 ECO: taxable=%s", data["eco_taxable"])

    # ── 14A — Amendments to Table 14 ─────────────────────────────────────────
    sec_14a = _find_section(
        text,
        r"14A\s*[-–]",
        r"[Aa]mend.*[Ee]-?[Cc]ommerce|[Ee]-?[Cc]ommerce.*[Aa]mend",
        end_patterns=[r"15\s*[-–]", r"HSN", r"Verification"],
        max_chars=2000,
    )
    if sec_14a:
        _ns14a = _sec_nums(sec_14a)
        _c14a  = _gstr1_map_cols(_ns14a)
        if _c14a["taxable"] > 0 or abs(_c14a["igst"]) > 0:
            data["eco_amend_taxable"] = _c14a["taxable"] or None
            data["eco_amend_igst"]    = _c14a["igst"]    or None
        logger.info("[GSTR-1] 14A ECO Amend: taxable=%s", data["eco_amend_taxable"])

    # ── 15 — Supplies u/s 9(5) ────────────────────────────────────────────────
    sec_15 = _find_section(
        text,
        r"15\s*[-–].*9\s*\(\s*5\s*\)",
        r"[Ss]upplies.*9\s*\(5\)|9\s*\(5\).*[Ss]upplies",
        r"15\s*[-–].*[Ee]-?[Cc]ommerce",
        end_patterns=[r"15A\s*[-–]", r"16\s*[-–]", r"HSN", r"Verification"],
        max_chars=2000,
    )
    if sec_15:
        _ns15 = _sec_nums(sec_15)
        _c15  = _gstr1_map_cols(_ns15)
        if _c15["taxable"] > 0:
            data["s95_taxable"] = _c15["taxable"]
            data["s95_igst"]    = _c15["igst"]    or None
            data["s95_cgst"]    = _c15["cgst"]    or None
            data["s95_sgst"]    = _c15["sgst"]    or None
        logger.info("[GSTR-1] 15 u/s 9(5): taxable=%s", data["s95_taxable"])

    # ── 15A(I) — Amendments u/s 9(5) Registered ──────────────────────────────
    sec_15a1 = _find_section(
        text,
        r"15A\s*[\(\[]?\s*[Ii]\s*[\)\]]?\s*[-–]",
        r"[Aa]mend.*9\s*\(5\).*[Rr]egistered",
        end_patterns=[r"15A\s*[\(\[]?\s*[Ii][Ii]", r"16\s*[-–]", r"HSN", r"Verification"],
        max_chars=2000,
    )
    if sec_15a1:
        _ns15a1 = _sec_nums(sec_15a1)
        _c15a1  = _gstr1_map_cols(_ns15a1)
        if _c15a1["taxable"] > 0 or abs(_c15a1["igst"]) > 0:
            data["s95a1_taxable"] = _c15a1["taxable"] or None
            data["s95a1_igst"]    = _c15a1["igst"]    or None
            data["s95a1_cgst"]    = _c15a1["cgst"]    or None
            data["s95a1_sgst"]    = _c15a1["sgst"]    or None
        logger.info("[GSTR-1] 15A(I): taxable=%s", data["s95a1_taxable"])

    # ── 15A(II) — Amendments u/s 9(5) Unregistered ───────────────────────────
    sec_15a2 = _find_section(
        text,
        r"15A\s*[\(\[]?\s*[Ii][Ii]\s*[\)\]]?\s*[-–]",
        r"[Aa]mend.*9\s*\(5\).*[Uu]nregistered",
        end_patterns=[r"16\s*[-–]", r"HSN", r"Verification"],
        max_chars=2000,
    )
    if sec_15a2:
        _ns15a2 = _sec_nums(sec_15a2)
        _ns15a2_clean = [n for n in _ns15a2 if abs(_gstr1_parse_amount(n)) >= 100]
        _c15a2  = _gstr1_map_cols(_ns15a2_clean or _ns15a2)
        if _c15a2["taxable"] > 0 or abs(_c15a2["igst"]) > 0:
            data["s95a2_taxable"] = _c15a2["taxable"] or None
            data["s95a2_igst"]    = _c15a2["igst"]    or None
        logger.info("[GSTR-1] 15A(II): taxable=%s", data["s95a2_taxable"])

    # ── Schema enforcement: required keys must exist with 0.0 default ────────
    _REQUIRED_KEYS = [
        "b2cs_sgst", "nil_taxable_value", "nil_exempt", "nil_non_gst",
        "cdnr_cgst", "cdnr_sgst", "cdnur_cgst", "cdnur_sgst",
    ]
    for k in _REQUIRED_KEYS:
        if data.get(k) is None:
            print(f"SCHEMA ERROR: missing key '{k}' — defaulting to 0.0")
            data[k] = 0.0

    # ── Exports Section ────────────────────────────────────────────────────────
    sec_exp = _find_section(
        text,
        r"6A.*Exports|Exports.*6A|Export.*Zero.*Rated",
        r"Exports.*supply",
        end_patterns=[r"9B", r"B2CS", r"HSN", r"7\s*[-–]"],
        max_chars=2000,
    )

    if sec_exp:
        total_line = _find_line_with_labels(sec_exp, r"Total")
        if total_line:
            nums = _numbers_from_line(total_line)
            if nums:
                data["export_value"] = nums[0]
                if len(nums) >= 2: data["export_igst"] = nums[1]

    # ── HSN Summary: map from sections (authoritative totals) ────────────────
    hsn = sections["hsn"]
    if hsn["taxable"] != 0:   # negative = net credit-note month (still a valid total)
        data["total_taxable_value"] = hsn["taxable"]
        data["total_igst"]          = hsn["igst"] if hsn["igst"] else None
        data["total_cgst"]          = hsn["cgst"] if hsn["cgst"] else None
        data["total_sgst"]          = hsn["sgst"] if hsn["sgst"] else None
        logger.info("[GSTR-1] HSN totals mapped: taxable=%s igst=%s cgst=%s sgst=%s",
                    data["total_taxable_value"], data["total_igst"],
                    data["total_cgst"], data["total_sgst"])
    else:
        logger.warning("[GSTR-1] HSN Summary NOT found or zero values")
        data["_parse_warnings"].append("HSN-wise summary not found — using computed totals")

    # ── Compute totals from parts if HSN not available ────────────────────────
    def safe_sum(*args: Optional[float]) -> Optional[float]:
        vals = [v for v in args if v is not None]
        return round(sum(vals), 2) if vals else None

    if data["total_taxable_value"] is None:
        # Sum all supply categories: taxable + nil/exempt/non-gst to match HSN total
        data["total_taxable_value"] = safe_sum(
            data["b2b_taxable_value"],
            data["b2cl_taxable_value"],
            data["b2cs_taxable_value"],
            data["export_value"],
            data["nil_taxable_value"],
            data["nil_exempt"],
            data["nil_non_gst"],
        )
        logger.info("[GSTR-1] Computed total_taxable_value=%s from parts", data["total_taxable_value"])

    if data["total_igst"] is None:
        data["total_igst"] = safe_sum(data["b2b_igst"], data["b2cl_igst"], data["export_igst"])
    if data["total_cgst"] is None:
        data["total_cgst"] = safe_sum(data["b2b_cgst"], data["b2cs_cgst"])
    if data["total_sgst"] is None:
        data["total_sgst"] = safe_sum(data["b2b_sgst"], data["b2cs_sgst"])

    # ── Table fallback (legacy path) ──────────────────────────────────────────
    if data["total_taxable_value"] is None and data["b2b_taxable_value"] is None:
        logger.info("[GSTR-1] Running table fallback")
        _gstr1_table_fallback(data, tables)

    # ── Final reconciliation: table values always win for key fields ──────────
    # The text parser may have overwritten table-parsed values with wrong ones
    # (especially for two-column layout PDFs where text is scrambled). Re-apply
    # table results for the 5 most critical fields.
    _CRITICAL = ['b2b_taxable_value', 'b2b_igst', 'b2b_cgst', 'b2b_sgst',
                 'b2cl_taxable_value', 'b2cl_igst',
                 'cdnr_taxable', 'cdn_value',          # cdn_value is fallback for cdnr_taxable
                 'cdnr_igst', 'cdnr_cgst', 'cdnr_sgst',
                 'cdnur_taxable', 'cdnur_igst',
                 'total_taxable_value', 'total_igst',
                 'nil_taxable_value', 'nil_exempt', 'nil_non_gst',
                 'b2cs_taxable_value', 'b2cs_cgst', 'b2cs_sgst']
    # CDN fields: the table extractor returns 0.0 (not None) for the old 2-column
    # layout where it can't read the 9B grid. A table ZERO must NOT clobber a valid
    # non-zero value the section parser already recovered.
    _CDN_FIELDS = {'cdnr_taxable', 'cdn_value', 'cdnr_igst', 'cdnr_cgst', 'cdnr_sgst',
                   'cdnur_taxable', 'cdnur_igst'}
    for _k in _CRITICAL:
        if _k in _tbl_pre and _tbl_pre[_k] is not None:
            tv = _tbl_pre[_k]
            if _k in _CDN_FIELDS and (tv == 0 or tv == 0.0) and data.get(_k):
                continue   # keep section value; table found nothing
            data[_k] = tv

    # ── Positional override for the "Total Invoice value / Note value" layout ──
    # This column layout (annual summary AND QRMP monthly returns) scrambles the
    # generic/text parsers for B2CL, B2CS, CDNR, CDNUR and the section totals.
    # The positional reader is verified to reconcile exactly to the annual, so it
    # is the source of truth for those sections. B2B is EXCLUDED on non-summary
    # files: the positional B2B can fail on QRMP monthlies, and the generic B2B
    # already reconciles there (positional B2B is only trusted in the annual).
    # Fire the positional reader for (a) the old two-column "Total Invoice value"
    # layout used by QRMP monthly returns, and (b) ANY "System generated summary"
    # (annual) — the positional reader is now format-aware (handles both the
    # invoice/taxable and the single-Value layouts) and table-number anchored, so
    # it is robust to watermarks that mangle section labels (e.g. 'B2MB').
    _has_value_col = bool(re.search(r'Total\s+(?:Invoice|Note)\s+[Vv]alue', text))
    if _LEGACY_A_SIG.search(text):
        # OLD compact summary layout (FY≈2020-21/21-22): B2B/SEZ/DE merged, integer
        # and "NA" columns break the decimal-only annual reader. Use the dedicated
        # token-positional reader instead, and flag the merged B2B.
        _lg = _parse_gstr1_legacy_summary(text)
        for _k, _v in _lg.items():
            data[_k] = _v
        data["legacy_combined_b2b"] = True
        logger.info("[GSTR-1] Legacy compact-summary layout parsed "
                    "(merged B2B/SEZ/DE; %d fields)", len(_lg))
    elif _has_value_col or _gstr1_is_annual_summary(text):
        _ann = _parse_gstr1_annual_summary(text)
        _ov = ['b2cl_taxable_value', 'b2cl_igst', 'b2cl_cgst', 'b2cl_sgst',
               'b2cs_taxable_value', 'b2cs_igst', 'b2cs_cgst', 'b2cs_sgst',
               'cdnr_taxable', 'cdn_value', 'cdnr_igst', 'cdnr_cgst', 'cdnr_sgst',
               'cdnur_taxable', 'cdnur_igst', 'cdnur_cgst', 'cdnur_sgst',
               'export_taxable_value', 'de_taxable',
               'nil_taxable_value', 'nil_exempt', 'nil_non_gst',
               'total_taxable_value', 'total_igst', 'total_cgst', 'total_sgst']
        if _gstr1_is_annual_summary(text):
            _ov = ['b2b_taxable_value', 'b2b_igst', 'b2b_cgst', 'b2b_sgst'] + _ov
        for _k in _ov:
            if _ann.get(_k) is not None:
                data[_k] = _ann[_k]
        logger.info("[GSTR-1] Positional (invoice-value layout) override applied")

    # ── Structural Validation Checks ─────────────────────────────────────────
    total_b2b      = parse_amount(data.get("b2b_taxable_value"))
    total_hsn      = parse_amount(data.get("total_taxable_value"))
    b2cs_cgst_v    = parse_amount(data.get("b2cs_cgst"))
    b2cs_sgst_v    = parse_amount(data.get("b2cs_sgst"))
    b2cl_taxable_v = parse_amount(data.get("b2cl_taxable_value"))
    cdnr_igst_v    = parse_amount(data.get("cdnr_igst"))
    cdnr_cgst_v    = parse_amount(data.get("cdnr_cgst"))
    cdnr_sgst_v    = parse_amount(data.get("cdnr_sgst"))
    cdnur_igst_v   = parse_amount(data.get("cdnur_igst"))
    cdnur_cgst_v   = parse_amount(data.get("cdnur_cgst"))
    cdnur_sgst_v   = parse_amount(data.get("cdnur_sgst"))
    nil_v          = parse_amount(data.get("nil_taxable_value"))
    exempt_v       = parse_amount(data.get("nil_exempt"))
    non_gst_v      = parse_amount(data.get("nil_non_gst"))
    nil_sum        = nil_v + exempt_v + non_gst_v

    print("TOTAL B2B:", total_b2b)
    print("TOTAL HSN:", total_hsn)

    # CHECK 1: CGST == SGST for all intra-state rows (B2CS + CDNR + CDNUR)
    b2cs_sym  = abs(b2cs_cgst_v  - b2cs_sgst_v)  < 0.02
    cdnr_sym  = abs(abs(cdnr_cgst_v)  - abs(cdnr_sgst_v))  < 0.02
    cdnur_sym = abs(abs(cdnur_cgst_v) - abs(cdnur_sgst_v)) < 0.02
    print(f"CHECK 1  B2CS  CGST={b2cs_cgst_v:.2f} vs SGST={b2cs_sgst_v:.2f}"
          f"  {'OK' if b2cs_sym else 'MISMATCH'}")
    print(f"CHECK 1  CDNR  CGST={cdnr_cgst_v:.2f} vs SGST={cdnr_sgst_v:.2f}"
          f"  {'OK' if cdnr_sym else 'MISMATCH'}")
    print(f"CHECK 1  CDNUR CGST={cdnur_cgst_v:.2f} vs SGST={cdnur_sgst_v:.2f}"
          f"  {'OK' if cdnur_sym else 'MISMATCH'}")

    # CHECK 2: IGST rows must have CGST=SGST=0 (only applies to pure IGST sections)
    cdnr_igst_pure  = abs(cdnr_igst_v)  > 0 and abs(cdnr_cgst_v)  == 0
    cdnur_igst_pure = abs(cdnur_igst_v) > 0 and abs(cdnur_cgst_v) == 0
    cdnr_mixed      = abs(cdnr_igst_v)  > 0 and abs(cdnr_cgst_v)  > 0
    cdnur_mixed     = abs(cdnur_igst_v) > 0 and abs(cdnur_cgst_v) > 0
    print(f"CHECK 2  CDNR  IGST={cdnr_igst_v:.2f} CGST={cdnr_cgst_v:.2f} SGST={cdnr_sgst_v:.2f}"
          f"  {'MIXED-OK' if cdnr_mixed else ('IGST-PURE' if cdnr_igst_pure else 'CGST-ONLY')}")
    print(f"CHECK 2  CDNUR IGST={cdnur_igst_v:.2f} CGST={cdnur_cgst_v:.2f} SGST={cdnur_sgst_v:.2f}"
          f"  {'MIXED-OK' if cdnur_mixed else ('IGST-PURE' if cdnur_igst_pure else 'CGST-ONLY')}")
    print(f"CHECK 2  B2CL taxable={b2cl_taxable_v}"
          f"  {'OK' if b2cl_taxable_v > 0 else 'WARNING: B2CL extraction failure'}")

    # CHECK 3: NIL + EXEMPT + NON_GST > 0
    print(f"CHECK 3  NIL={nil_v:.2f} EXEMPT={exempt_v:.2f} NON_GST={non_gst_v:.2f}"
          f"  sum={nil_sum:.2f}  {'OK' if nil_sum > 0 else 'ZERO (nil section not extracted)'}")

    # CHECK 4: CDN totals match extracted values
    cdn_gst_total  = cdnr_igst_v  + cdnr_cgst_v  + cdnr_sgst_v
    cdnur_gst_total = cdnur_igst_v + cdnur_cgst_v + cdnur_sgst_v
    print(f"CHECK 4  CDNR  gst_total={cdn_gst_total:.2f}"
          f"  {'OK' if abs(cdn_gst_total) > 0 else 'ZERO — no CDNR GST extracted'}")
    print(f"CHECK 4  CDNUR gst_total={cdnur_gst_total:.2f}"
          f"  {'OK' if abs(cdnur_gst_total) > 0 else 'ZERO — no CDNUR GST extracted'}")

    print("Parsed Row:", {
        "period":          data.get("period"),
        "b2b_taxable":     total_b2b,
        "b2cl_taxable":    parse_amount(data.get("b2cl_taxable_value")),
        "b2cs_taxable":    parse_amount(data.get("b2cs_taxable_value")),
        "b2cs_cgst":       b2cs_cgst_v,
        "b2cs_sgst":       b2cs_sgst_v,
        "nil_rated":       nil_v,
        "exempt":          exempt_v,
        "non_gst":         non_gst_v,
        "cdnr_taxable":    parse_amount(data.get("cdnr_taxable")),
        "cdnr_igst":       cdnr_igst_v,
        "cdnr_cgst":       cdnr_cgst_v,
        "cdnr_sgst":       cdnr_sgst_v,
        "cdnur_taxable":   parse_amount(data.get("cdnur_taxable")),
        "cdnur_igst":      cdnur_igst_v,
        "cdnur_cgst":      cdnur_cgst_v,
        "cdnur_sgst":      cdnur_sgst_v,
        "hsn_taxable":     total_hsn,
    })

    logger.info(
        "[GSTR-1] RESULT: total_taxable=%s total_igst=%s b2b=%s b2cs=%s "
        "nil=%s cdnr=%s cdnur=%s",
        data["total_taxable_value"], data["total_igst"],
        data["b2b_taxable_value"], data["b2cs_taxable_value"],
        data["nil_taxable_value"], data["cdnr_taxable"], data["cdnur_taxable"],
    )
    print("DEBUG FINAL:", {
        "b2b_taxable":    data.get("b2b_taxable_value"),
        "b2b_igst":       data.get("b2b_igst"),
        "b2b_cgst":       data.get("b2b_cgst"),
        "b2b_sgst":       data.get("b2b_sgst"),
        "b2cs_taxable":   data.get("b2cs_taxable_value"),
        "b2cs_igst":      data.get("b2cs_igst"),
        "b2cs_cgst":      data.get("b2cs_cgst"),
        "b2cs_sgst":      data.get("b2cs_sgst"),
        "cdnur_taxable":  data.get("cdnur_taxable"),
        "cdnur_igst":     data.get("cdnur_igst"),
        "cdnur_cgst":     data.get("cdnur_cgst"),
        "cdnur_sgst":     data.get("cdnur_sgst"),
        "nil_rated":      data.get("nil_taxable_value"),
        "nil_exempt":     data.get("nil_exempt"),
        "nil_non_gst":    data.get("nil_non_gst"),
        "total_taxable":  data.get("total_taxable_value"),
        "total_igst":     data.get("total_igst"),
        "total_cgst":     data.get("total_cgst"),
        "total_sgst":     data.get("total_sgst"),
    })
    return data


# ── Standard output builder ────────────────────────────────────────────────────

def build_row(data: Dict[str, Any]) -> Dict[str, float]:
    """
    Convert raw parsed GSTR-1 data dict to the standardised MOM row schema.
    Every field is guaranteed to be float (never None). Safe to pass directly
    to generate_gstr1_mom_from_template() via the export route.
    """
    return {
        "month":          data.get("period") or "",

        "b2b_taxable":    parse_amount(data.get("b2b_taxable_value")),
        "b2b_igst":       parse_amount(data.get("b2b_igst")),
        "b2b_cgst":       parse_amount(data.get("b2b_cgst")),
        "b2b_sgst":       parse_amount(data.get("b2b_sgst")),

        "b2cl_taxable":   parse_amount(data.get("b2cl_taxable_value")),
        "b2cl_igst":      parse_amount(data.get("b2cl_igst")),
        "b2cl_cgst":      parse_amount(data.get("b2cl_cgst")),
        "b2cl_sgst":      parse_amount(data.get("b2cl_sgst")),

        "b2cs_taxable":   parse_amount(data.get("b2cs_taxable_value")),
        "b2cs_igst":      parse_amount(data.get("b2cs_igst")),
        "b2cs_cgst":      parse_amount(data.get("b2cs_cgst")),
        "b2cs_sgst":      parse_amount(data.get("b2cs_sgst")),

        "nil_rated":      parse_amount(data.get("nil_taxable_value")),
        "exempt":         parse_amount(data.get("nil_exempt")),
        "non_gst":        parse_amount(data.get("nil_non_gst")),

        "cdnr_taxable":   parse_amount(data.get("cdnr_taxable") or data.get("cdn_value")),
        "cdnr_igst":      parse_amount(data.get("cdnr_igst")    or data.get("cdn_igst")),
        "cdnr_cgst":      parse_amount(data.get("cdnr_cgst")    or data.get("cdn_cgst")),
        "cdnr_sgst":      parse_amount(data.get("cdnr_sgst")    or data.get("cdn_sgst")),

        "cdnur_taxable":  parse_amount(data.get("cdnur_taxable")),
        "cdnur_igst":     parse_amount(data.get("cdnur_igst")),
        "cdnur_cgst":     parse_amount(data.get("cdnur_cgst")),
        "cdnur_sgst":     parse_amount(data.get("cdnur_sgst")),

        "hsn_taxable":    parse_amount(data.get("total_taxable_value")),
    }


def _gstr1_table_fallback(data: Dict, tables: List) -> None:
    """Table-based fallback for GSTR-1."""
    all_rows: List[List[str]] = []
    for tbl in tables:
        all_rows.extend(_table_to_rows(tbl))

    for row in all_rows:
        row_text = " ".join(row).lower()

        if data["total_taxable_value"] is None:
            if "total" in row_text and "taxable" in row_text:
                nums = _row_numbers(row)
                if len(nums) >= 1:
                    data["total_taxable_value"] = nums[0]
                if len(nums) >= 2:
                    data["total_igst"] = data["total_igst"] or nums[1]
                if len(nums) >= 3:
                    data["total_cgst"] = data["total_cgst"] or nums[2]
                if len(nums) >= 4:
                    data["total_sgst"] = data["total_sgst"] or nums[3]

        if data["b2b_taxable_value"] is None:
            if "b2b" in row_text and "total" in row_text:
                nums = _row_numbers(row)
                if nums:
                    data["b2b_taxable_value"] = nums[-1]

        if data["b2cs_taxable_value"] is None:
            if ("b2cs" in row_text or ("b2c" in row_text and "small" in row_text)):
                nums = _row_numbers(row)
                if nums:
                    data["b2cs_taxable_value"] = nums[0]

        if data["cdn_value"] is None:
            if "credit" in row_text and ("note" in row_text or "cdn" in row_text):
                nums = _row_numbers(row)
                if nums:
                    data["cdn_value"] = nums[0]


# ── GSTR-9 Parser ─────────────────────────────────────────────────────────────

def parse_gstr9(text: str, tables: List[List[List]]) -> Dict[str, Any]:
    """
    Comprehensive GSTR-9 Annual Return parser.

    KEY INSIGHT: GSTR-9 rows use SINGLE-LETTER labels (A, B, C…) within each
    Part section — NOT composite labels like "4A", "4B". Section context is
    required to disambiguate the same letter across Parts 4, 5, 6, 7, 8, 9.
    Numeric rows (10, 11, 12, 13…) in Part V use integer labels.

    Strategy:
      1. Detect Part-section boundaries in all_rows via header keywords.
      2. Within each section, match rows by letter/number label in first cell.
      3. Skip label + description cells when extracting numeric values
         (avoids the label number being captured as a data value).
      4. Fallback to full-row keyword search for the Final Turnover summary row.
    """
    data: Dict[str, Any] = {
        "form_type":      "GSTR-9",
        "gstin":          _extract_gstin(text),
        "legal_name":     _extract_legal_name(text),
        "trade_name":     None,
        "period":         _extract_period(text),
        "arn":            None,
        "date_of_filing": None,
        "_parse_warnings": [],
    }

    # ── Header extras ─────────────────────────────────────────────────────────
    m_arn = re.search(r'\b(A[A-Z]\d{2}[A-Z0-9]{12,})\b', text)
    if m_arn:
        data["arn"] = m_arn.group(1)

    m_date = re.search(
        r'(?:Date\s+of\s+Filing|Date\s+of\s+Submission|Filed\s+on)\s*[:\-]?\s*'
        r'(\d{2}[-/]\d{2}[-/]\d{4})',
        text, re.IGNORECASE,
    )
    if m_date:
        data["date_of_filing"] = m_date.group(1)

    m_trade = re.search(r'Trade\s+[Nn]ame\s*[:\-]\s*([^\n]{3,80})', text)
    data["trade_name"] = m_trade.group(1).strip() if m_trade else data["legal_name"]

    logger.info("[GSTR-9] Parsing started. Text length=%d", len(text))

    # ── Build row list ────────────────────────────────────────────────────────
    all_rows: List[List[str]] = []
    for tbl in tables:
        all_rows.extend(_table_to_rows(tbl))

    # ── Section boundary detection ────────────────────────────────────────────
    # GSTR-9 PDF rows use SINGLE letters (A, B, C…) as labels within each Part.
    # We detect Part section start indices so we can disambiguate duplicate letters.
    _SEC_ORDER = ["part4", "part5", "part6", "part7", "part8", "part9", "partv", "partvi"]
    _sec_idx: Dict[str, int] = {k: len(all_rows) for k in _SEC_ORDER}

    _SEC_PATTERNS = {
        "part4": [r"advances.*inward.*outward.*tax.*payable", r"4\.\s*details of advances"],
        "part5": [r"outward supplies on which tax is not payable", r"5\.\s*details of outward"],
        "part6": [r"details of itc availed during", r"6\.\s*details of itc availed"],
        "part7": [r"itc reversed and ineligible", r"7\.\s*details of itc reversed"],
        "part8": [r"other itc related information", r"8\.\s*other itc"],
        "part9": [r"details of tax paid as declared", r"part\s*[-–]\s*iv", r"9\.\s*details of tax"],
        "partv": [r"particulars of the transactions for the previous", r"part\s*[-–]\s*v\b"],
        "partvi": [r"part\s*[-–]\s*vi\b", r"demands\s+and\s+refunds", r"15\.\s*details of demands"],
    }

    for i, row in enumerate(all_rows):
        rt = " ".join(row).lower()
        for sec, pats in _SEC_PATTERNS.items():
            if _sec_idx[sec] == len(all_rows):   # not yet found
                if any(re.search(p, rt) for p in pats):
                    _sec_idx[sec] = i
                    break

    def _get_sec(name: str) -> List[List[str]]:
        start = _sec_idx[name]
        # End = start of next found section
        end = len(all_rows)
        for k in _SEC_ORDER:
            nk = _sec_idx[k]
            if nk > start:
                end = min(end, nk)
        return all_rows[start:end]

    pt4 = _get_sec("part4")
    pt5 = _get_sec("part5")
    pt6 = _get_sec("part6")
    pt7 = _get_sec("part7")
    pt8 = _get_sec("part8")
    pt9 = _get_sec("part9")
    ptv = _get_sec("partv")
    ptvi = _get_sec("partvi")

    # ── Core helpers ──────────────────────────────────────────────────────────
    def _data_nums(row: List[str], skip: int = 2) -> List[float]:
        """Extract numeric values from a row, skipping the first `skip` cells
        (label + description). Non-numeric cells (NaN, empty, text) are skipped."""
        nums: List[float] = []
        for cell in row[skip:]:
            v = _clean_number(cell)
            if v is not None:
                nums.append(v)
        return nums

    def _find_letter(section: List[List[str]], letter: str, skip: int = 2) -> List[float]:
        """Find the first row whose first cell exactly matches `letter`."""
        lu = letter.strip().upper()
        for row in section:
            if row and row[0].strip().upper() == lu:
                return _data_nums(row, skip)
        return []

    def _find_num_label(section: List[List[str]], label: str, skip: int = 1) -> List[float]:
        """For rows labelled with integers (10, 11, 12, 13…) — skip=1 to drop the
        label cell so the label number is NOT captured as a data value."""
        for row in section:
            if row and row[0].strip() == label:
                return _data_nums(row, skip)
        return []

    def n(nums: List, idx: int) -> Optional[float]:
        return nums[idx] if idx < len(nums) else None

    # ── Part 4: Outward Supplies — [TaxableValue, CGST, SGST, IGST, Cess] ────
    for letter, pfx in [
        ("A", "4A_B2C"),           ("B", "4B_B2B"),
        ("C", "4C_Export_WithTax"),("D", "4D_SEZ_WithTax"),
        ("E", "4E_DeemedExports"), ("F", "4F_Advances"),
        ("G", "4G_RCM_Inward"),    ("H", "4H_SubTotal_AtoG"),
        ("I", "4I_CreditNotes"),   ("J", "4J_DebitNotes"),
        ("K", "4K_Amendments_Plus"),("L","4L_Amendments_Minus"),
        ("M", "4M_SubTotal_ItoL"), ("N", "4N_Net_TaxPayable"),
    ]:
        nums = _find_letter(pt4, letter)
        data[f"{pfx}_TaxableValue"] = n(nums, 0)
        data[f"{pfx}_CGST"]         = n(nums, 1)
        data[f"{pfx}_SGST"]         = n(nums, 2)
        data[f"{pfx}_IGST"]         = n(nums, 3)
        data[f"{pfx}_Cess"]         = n(nums, 4)

    # ── Part 5: Non-Taxable Outward Supplies — TaxableValue only (A-M) ───────
    for letter, key in [
        ("A", "5A_Export_WithoutTax_TaxableValue"),
        ("B", "5B_SEZ_WithoutTax_TaxableValue"),
        ("C", "5C_RCM_Recipient_TaxableValue"),
        ("D", "5D_Exempted_TaxableValue"),
        ("E", "5E_NilRated_TaxableValue"),
        ("F", "5F_NonGST_TaxableValue"),
        ("G", "5G_SubTotal_AtoF_TaxableValue"),
        ("H", "5H_CreditNotes_TaxableValue"),
        ("I", "5I_DebitNotes_TaxableValue"),
        ("J", "5J_Amendments_Plus_TaxableValue"),
        ("K", "5K_Amendments_Minus_TaxableValue"),
        ("L", "5L_SubTotal_HtoK_TaxableValue"),
        ("M", "5M_Turnover_NonTaxable_TaxableValue"),
    ]:
        data[key] = n(_find_letter(pt5, letter), 0)

    # 5N has all 5 components
    nums5n = _find_letter(pt5, "N")
    for i, sfx in enumerate(["TaxableValue", "CGST", "SGST", "IGST", "Cess"]):
        data[f"5N_TotalTurnover_{sfx}"] = n(nums5n, i)

    # ── Part 6: ITC Availed — [CGST, SGST, IGST, Cess] ──────────────────────
    # 6A: single row
    nums6a = _find_letter(pt6, "A")
    data["6A_ITC_GSTR3B_CGST"] = n(nums6a, 0)
    data["6A_ITC_GSTR3B_SGST"] = n(nums6a, 1)
    data["6A_ITC_GSTR3B_IGST"] = n(nums6a, 2)
    data["6A_ITC_GSTR3B_Cess"] = n(nums6a, 3)

    # 6A1: ITC from preceding FY availed in April-September (other than reclaim of reversal)
    nums6a1 = _find_letter(pt6, "A1")
    data["6A1_PrecedingFY_ITC_CGST"] = n(nums6a1, 0)
    data["6A1_PrecedingFY_ITC_SGST"] = n(nums6a1, 1)
    data["6A1_PrecedingFY_ITC_IGST"] = n(nums6a1, 2)
    data["6A1_PrecedingFY_ITC_Cess"] = n(nums6a1, 3)

    # 6A2: Net ITC for current FY (6A − 6A1)
    nums6a2 = _find_letter(pt6, "A2")
    data["6A2_Net_ITC_CGST"] = n(nums6a2, 0)
    data["6A2_Net_ITC_SGST"] = n(nums6a2, 1)
    data["6A2_Net_ITC_IGST"] = n(nums6a2, 2)
    data["6A2_Net_ITC_Cess"] = n(nums6a2, 3)

    # 6B, 6C, 6D: each has 3 sub-rows (Inputs / Cap Goods / Input Services).
    # The main labeled row IS the "Inputs" sub-row; next 2 rows = CapGoods, InputSvcs.
    for main_letter, pfx in [("B", "6B_Inputs"), ("C", "6C_URD_RC"), ("D", "6D_RD_RC")]:
        for i, row in enumerate(pt6):
            if row and row[0].strip().upper() == main_letter:
                for j_off, sfx in enumerate(["Inputs", "CapGoods", "InputSvcs"]):
                    r = pt6[i + j_off] if i + j_off < len(pt6) else []
                    nums = _data_nums(r, skip=2) if r else []
                    data[f"{pfx}_{sfx}_CGST"] = n(nums, 0)
                    data[f"{pfx}_{sfx}_SGST"] = n(nums, 1)
                    data[f"{pfx}_{sfx}_IGST"] = n(nums, 2)
                    data[f"{pfx}_{sfx}_Cess"] = n(nums, 3)
                break

    # 6E: Import of Goods (IGST-only column; n(nums,0) = IGST directly)
    for i, row in enumerate(pt6):
        if row and row[0].strip().upper() == "E":
            for j_off, sfx in enumerate(["Inputs", "CapGoods"]):
                r = pt6[i + j_off] if i + j_off < len(pt6) else []
                nums = _data_nums(r, skip=2) if r else []
                data[f"6E_Import_Goods_{sfx}_IGST"] = n(nums, 0)
                data[f"6E_Import_Goods_{sfx}_Cess"] = n(nums, 1)
            break

    # 6F: Import of Services (IGST-only)
    nums6f = _find_letter(pt6, "F")
    data["6F_Import_Svcs_IGST"] = n(nums6f, 0)
    data["6F_Import_Svcs_Cess"] = n(nums6f, 1)

    # 6G–6J, 6M, 6N, 6O: [CGST, SGST, IGST, Cess]
    for letter, pfx in [
        ("G", "6G_ISD"), ("H", "6H_ITC_Reclaimed"),
        ("I", "6I_SubTotal_BtoH"), ("J", "6J_Difference_IminusA"),
        ("M", "6M_OtherITC"), ("N", "6N_SubTotal_KtoM"), ("O", "6O_TotalITC"),
    ]:
        nums = _find_letter(pt6, letter)
        data[f"{pfx}_CGST"] = n(nums, 0)
        data[f"{pfx}_SGST"] = n(nums, 1)
        data[f"{pfx}_IGST"] = n(nums, 2)
        data[f"{pfx}_Cess"] = n(nums, 3)

    # 6K, 6L: TRAN credits (CGST, SGST only)
    nums6k = _find_letter(pt6, "K")
    data["6K_TRAN1_CGST"] = n(nums6k, 0)
    data["6K_TRAN1_SGST"] = n(nums6k, 1)

    nums6l = _find_letter(pt6, "L")
    data["6L_TRAN2_CGST"] = n(nums6l, 0)
    data["6L_TRAN2_SGST"] = n(nums6l, 1)

    # ── Part 7: ITC Reversed — [CGST, SGST, IGST, Cess] ─────────────────────
    for letter, pfx in [
        ("A",  "7A_Rule37"),          ("A1", "7A1_Rule37A"),
        ("A2", "7A2_Rule38"),         ("B",  "7B_Rule39"),
        ("C",  "7C_Rule42"),          ("D",  "7D_Rule43"),
        ("E",  "7E_Sec17_5"),         ("F",  "7F_TRAN1_Reversal"),
        ("G",  "7G_TRAN2_Reversal"),
        ("I",  "7I_Total_ITC_Reversed"), ("J", "7J_NetITC_Utilizable"),
    ]:
        nums = _find_letter(pt7, letter)
        data[f"{pfx}_CGST"] = n(nums, 0)
        data[f"{pfx}_SGST"] = n(nums, 1)
        data[f"{pfx}_IGST"] = n(nums, 2)
        data[f"{pfx}_Cess"] = n(nums, 3)

    # 7H/7H1: try H1 first (new PDF format), fall back to H (old format)
    nums_7h = _find_letter(pt7, "H1") or _find_letter(pt7, "H")
    data["7H1_OtherReversal_CGST"] = n(nums_7h, 0)
    data["7H1_OtherReversal_SGST"] = n(nums_7h, 1)
    data["7H1_OtherReversal_IGST"] = n(nums_7h, 2)
    data["7H1_OtherReversal_Cess"] = n(nums_7h, 3)

    # ── Part 8: ITC Comparison — [CGST, SGST, IGST, Cess] ───────────────────
    for letter, pfx in [
        ("A",  "8A_GSTR2A_ITC"),           ("B",  "8B_ITC_6B_6H"),
        ("C",  "8C_NextFY_ITC"),            ("D",  "8D_Difference"),
        ("E",  "8E_Available_NotAvailed"),  ("F",  "8F_Available_Ineligible"),
        ("G",  "8G_IGST_Import_Paid"),      ("H",  "8H_IGST_Import_Availed"),
        ("H1", "8H1_IGST_Import_NextFY"),
        ("I",  "8I_Diff_GH"),               ("J",  "8J_NotAvailed_Import"),
        ("K",  "8K_ITC_To_Lapse"),
    ]:
        nums = _find_letter(pt8, letter)
        data[f"{pfx}_CGST"] = n(nums, 0)
        data[f"{pfx}_SGST"] = n(nums, 1)
        data[f"{pfx}_IGST"] = n(nums, 2)
        data[f"{pfx}_Cess"] = n(nums, 3)

    # ── Part 9: Tax Paid — [Payable, Cash, ITC cols…] ────────────────────────
    # Row A (IGST): Payable | Cash | ITC-CGST | ITC-SGST | ITC-IGST | ITC-Cess
    nums9a = _find_letter(pt9, "A")
    data["9A_IGST_Payable"]  = n(nums9a, 0)
    data["9A_IGST_Cash"]     = n(nums9a, 1)
    data["9A_IGST_ITC_CGST"] = n(nums9a, 2)
    data["9A_IGST_ITC_SGST"] = n(nums9a, 3)
    data["9A_IGST_ITC_IGST"] = n(nums9a, 4)
    data["9A_IGST_ITC_Cess"] = n(nums9a, 5)

    # Row B (CGST): Payable | Cash | ITC-CGST | ITC-IGST
    nums9b = _find_letter(pt9, "B")
    data["9B_CGST_Payable"]  = n(nums9b, 0)
    data["9B_CGST_Cash"]     = n(nums9b, 1)
    data["9B_CGST_ITC_CGST"] = n(nums9b, 2)
    data["9B_CGST_ITC_IGST"] = n(nums9b, 3)

    # Row C (SGST): Payable | Cash | ITC-SGST | ITC-IGST
    nums9c = _find_letter(pt9, "C")
    data["9C_SGST_Payable"]  = n(nums9c, 0)
    data["9C_SGST_Cash"]     = n(nums9c, 1)
    data["9C_SGST_ITC_SGST"] = n(nums9c, 2)
    data["9C_SGST_ITC_IGST"] = n(nums9c, 3)

    nums9d = _find_letter(pt9, "D")
    data["9D_Cess_Payable"]  = n(nums9d, 0)
    data["9D_Cess_Cash"]     = n(nums9d, 1)
    data["9D_Cess_ITC_Cess"] = n(nums9d, 2)

    for letter, pfx in [
        ("E", "9E_Interest"), ("F", "9F_LateFee"),
        ("G", "9G_Penalty"),  ("H", "9H_Other"),
    ]:
        nums = _find_letter(pt9, letter)
        data[f"{pfx}_Payable"] = n(nums, 0)
        data[f"{pfx}_Cash"]    = n(nums, 1)

    # ── Part V: Amendments & Previous FY (numeric labels 10–13) ──────────────
    # skip=1: drops the "10"/"11" label cell so it is NOT captured as a data value
    nums10 = _find_num_label(ptv, "10")
    data["10_Amendments_Plus_TaxableValue"] = n(nums10, 0)
    data["10_Amendments_Plus_CGST"]         = n(nums10, 1)
    data["10_Amendments_Plus_SGST"]         = n(nums10, 2)
    data["10_Amendments_Plus_IGST"]         = n(nums10, 3)
    data["10_Amendments_Plus_Cess"]         = n(nums10, 4)

    nums11 = _find_num_label(ptv, "11")
    data["11_Amendments_Minus_TaxableValue"] = n(nums11, 0)
    data["11_Amendments_Minus_CGST"]         = n(nums11, 1)
    data["11_Amendments_Minus_SGST"]         = n(nums11, 2)
    data["11_Amendments_Minus_IGST"]         = n(nums11, 3)
    data["11_Amendments_Minus_Cess"]         = n(nums11, 4)

    for label, pfx in [("12", "12_ITC_Reversal_PrevFY"), ("13", "13_ITC_Availed_PrevFY")]:
        nums = _find_num_label(ptv, label)
        data[f"{pfx}_CGST"] = n(nums, 0)
        data[f"{pfx}_SGST"] = n(nums, 1)
        data[f"{pfx}_IGST"] = n(nums, 2)
        data[f"{pfx}_Cess"] = n(nums, 3)

    # ── Table 14: Differential tax paid on account of Table 10 & 11 declarations ──
    for letter, pfx in [
        ("A", "14A_IGST"), ("B", "14B_CGST"), ("C", "14C_SGST"),
        ("D", "14D_Cess"), ("E", "14E_Interest"),
    ]:
        nums14 = _find_letter(ptv, letter)
        data[f"{pfx}_Payable"] = n(nums14, 0)
        data[f"{pfx}_Cash"]    = n(nums14, 1)

    # ── Final Turnover (5N + 10 − 11) ────────────────────────────────────────
    # Try to find it directly: it's a row with no label (empty first cell)
    # and description containing "total turnover" + "10" or "5n"
    _ft_found = False
    for row in ptv:
        rt = " ".join(row).lower()
        if "total turnover" in rt and ("5n" in rt or "10" in rt):
            ft_nums = _data_nums(row, skip=1)
            data["FinalTurnover_5N_plus10_minus11_TaxableValue"] = n(ft_nums, 0)
            data["FinalTurnover_5N_plus10_minus11_CGST"]         = n(ft_nums, 1)
            data["FinalTurnover_5N_plus10_minus11_SGST"]         = n(ft_nums, 2)
            data["FinalTurnover_5N_plus10_minus11_IGST"]         = n(ft_nums, 3)
            data["FinalTurnover_5N_plus10_minus11_Cess"]         = n(ft_nums, 4)
            _ft_found = True
            break

    if not _ft_found:
        # Compute: 5N + 10 − 11
        def _sa(*vs):
            vals = [v for v in vs if v is not None]
            return round(sum(vals), 2) if vals else None

        def _ss(a, b):
            return round(a - (b or 0), 2) if a is not None else None

        for comp, k5n, k10, k11 in [
            ("TaxableValue", "5N_TotalTurnover_TaxableValue", "10_Amendments_Plus_TaxableValue", "11_Amendments_Minus_TaxableValue"),
            ("CGST",  "5N_TotalTurnover_CGST",  "10_Amendments_Plus_CGST",  "11_Amendments_Minus_CGST"),
            ("SGST",  "5N_TotalTurnover_SGST",  "10_Amendments_Plus_SGST",  "11_Amendments_Minus_SGST"),
            ("IGST",  "5N_TotalTurnover_IGST",  "10_Amendments_Plus_IGST",  "11_Amendments_Minus_IGST"),
            ("Cess",  "5N_TotalTurnover_Cess",  "10_Amendments_Plus_Cess",  "11_Amendments_Minus_Cess"),
        ]:
            data[f"FinalTurnover_5N_plus10_minus11_{comp}"] = _ss(
                _sa(data.get(k5n), data.get(k10)), data.get(k11)
            )

    # ── Part VI: Table 15 — Demands and Refunds [CGST, SGST, IGST, Cess] ──────
    for letter, pfx in [
        ("A", "15A_Tax_Demands"),          ("B", "15B_Tax_Demands_Paid"),
        ("C", "15C_Tax_Demands_Partial"),  ("D", "15D_Refunds_Claimed"),
        ("E", "15E_Refunds_Sanctioned"),   ("F", "15F_Refunds_Rejected"),
        ("G", "15G_Refunds_Pending"),
    ]:
        nums = _find_letter(ptvi, letter)
        data[f"{pfx}_CGST"] = n(nums, 0)
        data[f"{pfx}_SGST"] = n(nums, 1)
        data[f"{pfx}_IGST"] = n(nums, 2)
        data[f"{pfx}_Cess"] = n(nums, 3)

    # ── Part VI: Table 16 — Composition/Job Work/Approval Goods ──────────────
    for letter, pfx in [
        ("A", "16A_Composition_Inward"),
        ("B", "16B_JobWork_DeemedSupply"),
        ("C", "16C_GoodsOnApproval"),
    ]:
        nums = _find_letter(ptvi, letter)
        data[f"{pfx}_TaxableValue"] = n(nums, 0)
        data[f"{pfx}_Tax"]          = n(nums, 1)

    # ── Part VI: Table 19 — Late Fee Payable and Paid ────────────────────────
    for letter, pfx in [
        ("A", "19A_CentralTax_LateFee"),
        ("B", "19B_StateTax_LateFee"),
    ]:
        nums = _find_letter(ptvi, letter)
        data[f"{pfx}_Payable"] = n(nums, 0)
        data[f"{pfx}_Paid"]    = n(nums, 1)

    # ── Backward-compatible aliases (analytics_engine.py uses these) ──────────
    data["total_taxable_outward"] = data.get("4N_Net_TaxPayable_TaxableValue")
    data["taxable_outward_igst"]  = data.get("4N_Net_TaxPayable_IGST")
    data["taxable_outward_cgst"]  = data.get("4N_Net_TaxPayable_CGST")
    data["taxable_outward_sgst"]  = data.get("4N_Net_TaxPayable_SGST")
    data["itc_igst"]              = data.get("6O_TotalITC_IGST")
    data["itc_cgst"]              = data.get("6O_TotalITC_CGST")
    data["itc_sgst"]              = data.get("6O_TotalITC_SGST")
    data["zero_rated_outward"]    = data.get("5A_Export_WithoutTax_TaxableValue")
    data["nil_rated_outward"]     = data.get("5E_NilRated_TaxableValue")
    data["exempt_outward"]        = data.get("5D_Exempted_TaxableValue")

    logger.info(
        "[GSTR-9] Done. sections=%s 4N_Taxable=%s 6O_IGST=%s FinalTV=%s",
        {k: _sec_idx[k] for k in _SEC_ORDER},
        data.get("4N_Net_TaxPayable_TaxableValue"),
        data.get("6O_TotalITC_IGST"),
        data.get("FinalTurnover_5N_plus10_minus11_TaxableValue"),
    )
    return data


# ── GSTR-9C Parser ────────────────────────────────────────────────────────────

def parse_gstr9c(text: str, tables: List[List[List]]) -> Dict[str, Any]:
    """Parse GSTR-9C Reconciliation Statement."""
    data: Dict[str, Any] = {
        "form_type": "GSTR-9C",
        "gstin": _extract_gstin(text),
        "legal_name": _extract_legal_name(text),
        "period": _extract_period(text),
        "turnover_as_per_books": None,
        "turnover_as_per_gstr9": None,
        "turnover_difference": None,
        "reason_for_difference": None,
        "itc_as_per_books": None,
        "itc_as_per_gstr3b": None,
        "itc_difference": None,
        "tax_payable": None,
        "tax_paid": None,
        "tax_difference": None,
        "_parse_warnings": [],
    }

    logger.info("[GSTR-9C] Parsing started. Text length=%d", len(text))

    all_rows: List[List[str]] = []
    for tbl in tables:
        all_rows.extend(_table_to_rows(tbl))

    for row in all_rows:
        row_text = " ".join(row).lower()
        if "turnover" in row_text and "books" in row_text:
            nums = _row_numbers(row)
            if nums:
                data["turnover_as_per_books"] = data["turnover_as_per_books"] or nums[-1]
        if "turnover" in row_text and ("gstr" in row_text or "annual return" in row_text):
            nums = _row_numbers(row)
            if nums:
                data["turnover_as_per_gstr9"] = data["turnover_as_per_gstr9"] or nums[-1]
        if "itc" in row_text and "books" in row_text:
            nums = _row_numbers(row)
            if nums:
                data["itc_as_per_books"] = data["itc_as_per_books"] or nums[-1]
        if "itc" in row_text and ("gstr-3b" in row_text or "3b" in row_text):
            nums = _row_numbers(row)
            if nums:
                data["itc_as_per_gstr3b"] = data["itc_as_per_gstr3b"] or nums[-1]

    # Compute differences
    if data["turnover_as_per_books"] is not None and data["turnover_as_per_gstr9"] is not None:
        data["turnover_difference"] = round(
            data["turnover_as_per_books"] - data["turnover_as_per_gstr9"], 2
        )
    if data["itc_as_per_books"] is not None and data["itc_as_per_gstr3b"] is not None:
        data["itc_difference"] = round(
            data["itc_as_per_books"] - data["itc_as_per_gstr3b"], 2
        )

    logger.info("[GSTR-9C] RESULT: turnover_books=%s turnover_gstr9=%s itc_diff=%s",
                data["turnover_as_per_books"], data["turnover_as_per_gstr9"], data["itc_difference"])
    return data


# ── Main parse function ───────────────────────────────────────────────────────

def _extract_text_pdfminer(file_path: str) -> str:
    """
    Extract full text using pdfminer.six (fallback when pdfplumber fails).
    pdfminer.six is already installed as a pdfplumber dependency.
    """
    try:
        from pdfminer.high_level import extract_text as _miner_extract
        from pdfminer.layout import LAParams
        laparams = LAParams(
            line_overlap=0.5,
            char_margin=2.0,
            line_margin=0.5,
            word_margin=0.1,
        )
        text = _miner_extract(file_path, laparams=laparams) or ""
        logger.info("[pdfminer] Extracted %d chars", len(text))
        return text
    except Exception as exc:
        logger.warning("[pdfminer] Extraction failed: %s", exc)
        return ""


def parse_gst_pdf(file_path: str) -> Dict[str, Any]:
    """
    Entry point: parse any GST PDF file.
    Returns structured extracted data with explicit None for missing fields.

    Strategy:
      1. Try pdfplumber for text + table extraction (per-page exception safety)
      2. If pdfplumber yields no text, fall back to pdfminer.six for text
         (pdfminer can't extract tables, but handles complex page objects better)
      3. Parse the resulting text with the form-specific parser
    """
    result: Dict[str, Any] = {
        "form_type": "UNKNOWN",
        "period": "Period not found",
        "gstin": None,
        "legal_name": None,
        "_parse_success": False,
        "_parse_warnings": [],
        "_page_count": 0,
    }

    full_text    = ""
    all_tables: List[List[List]] = []
    used_pdfminer = False

    # ── Step 1: pdfplumber (text + tables, per-page safe) ─────────────────────
    try:
        with pdfplumber.open(file_path) as pdf:
            result["_page_count"] = len(pdf.pages)
            full_text_parts: List[str] = []

            for page_num, page in enumerate(pdf.pages, start=1):
                try:
                    page_text = page.extract_text() or ""
                except Exception as page_exc:
                    logger.warning("[PDF] Page %d pdfplumber text failed: %s", page_num, page_exc)
                    page_text = ""
                full_text_parts.append(page_text)

                try:
                    page_tables = page.extract_tables() or []
                except Exception as page_exc:
                    logger.warning("[PDF] Page %d pdfplumber tables failed: %s", page_num, page_exc)
                    page_tables = []
                all_tables.extend(page_tables)

            full_text = "\n".join(full_text_parts)
            logger.info("[pdfplumber] %d pages, %d chars, %d tables",
                        result["_page_count"], len(full_text), len(all_tables))

    except Exception as exc:
        logger.warning("[pdfplumber] Open failed: %s", exc)

    # ── Step 2: pdfminer fallback if pdfplumber gave no text ──────────────────
    if not full_text.strip():
        logger.info("[PDF] pdfplumber returned no text → trying pdfminer.six")
        full_text = _extract_text_pdfminer(file_path)
        used_pdfminer = True
        if full_text.strip():
            result["_parse_warnings"].append(
                "Text extracted via pdfminer (pdfplumber incompatible with this PDF). "
                "Table-based fields may be limited."
            )

    if not full_text.strip():
        result["_parse_warnings"].append(
            "No extractable text found. This may be a scanned PDF. "
            "Please use a text-based PDF downloaded from the GST portal."
        )
        return result

    # ── Step 3: detect form type & parse ──────────────────────────────────────
    try:
        gst_type = detect_gst_type(full_text)
        result["form_type"] = gst_type
        logger.info("Detected form type: %s (pdfminer=%s)", gst_type, used_pdfminer)

        parsers = {
            "GSTR-1":  parse_gstr1,
            "GSTR-3B": parse_gstr3b,
            "GSTR-9":  parse_gstr9,
            "GSTR-9C": parse_gstr9c,
        }

        if gst_type in parsers:
            try:
                parsed = parsers[gst_type](full_text, all_tables)
                # Merge warnings instead of overwriting (outer warnings e.g. pdfminer notice)
                outer_warnings = result.get("_parse_warnings", [])
                parser_warnings = parsed.pop("_parse_warnings", [])
                result.update(parsed)
                result["_parse_warnings"] = outer_warnings + parser_warnings
                result["_parse_success"] = True
                logger.info("Parse success: form=%s period=%s gstin=%s",
                            gst_type, result.get("period"), result.get("gstin"))
            except Exception as parse_exc:
                logger.exception("Parser for %s raised: %s", gst_type, parse_exc)
                result["_parse_warnings"].append(f"Parser error: {str(parse_exc)}")
                result["period"]     = _extract_period(full_text)
                result["gstin"]      = _extract_gstin(full_text)
                result["legal_name"] = _extract_legal_name(full_text)
        else:
            result["_parse_warnings"].append(
                "Could not detect GST form type. "
                "Ensure the PDF is GSTR-1, 3B, 9, or 9C from the official GST portal."
            )
            logger.warning("Unknown form type for: %s", file_path)

    except Exception as exc:
        logger.exception("PDF parsing failed: %s", exc)
        result["_parse_warnings"].append(f"Parsing error: {str(exc)}")

    return result
