"""
DGARM Risk Intelligence Engine — v2 (57-ratio framework)
Ratios sourced from the DGARM audit reference document v2.
Computed from GSTR-1 / GSTR-3B extracted data.
Ratios requiring GSTR-2B or manual verification are returned with value=None.

Multi-FY trend analysis: months are grouped into Financial Years (Apr–Mar),
aggregated into FY totals, and key ratios are tracked year-over-year.
"""
import logging

logger = logging.getLogger(__name__)


# ── Basic helpers ─────────────────────────────────────────────────────────────

def _safe_div(num, den):
    try:
        d = float(den or 0)
        if d == 0:
            return None
        return round(float(num or 0) / d, 4)
    except (TypeError, ValueError):
        return None


def _pct(num, den):
    r = _safe_div(num, den)
    return round(r * 100, 2) if r is not None else None


def _level(value, low_ok, high_warn, invert=False):
    """LOW / MEDIUM / HIGH risk."""
    if value is None:
        return "UNKNOWN"
    if invert:
        if value >= high_warn: return "LOW"
        if value >= low_ok:    return "MEDIUM"
        return "HIGH"
    else:
        if value <= low_ok:    return "LOW"
        if value <= high_warn: return "MEDIUM"
        return "HIGH"


def _comp(label, value, table, unit="₹"):
    """A single input component used in a ratio formula."""
    return {"label": label, "value": round(float(value), 2) if value is not None else None, "table": table, "unit": unit}


def _r(sl_no, dgarm_ref, category, name, value, unit, formula, benchmark,
       description, risk_level, anomaly=False, level_params=None, components=None):
    return {
        "sl_no":        sl_no,
        "dgarm_ref":    dgarm_ref,
        "category":     category,
        "name":         name,
        "value":        value,
        "unit":         unit,
        "formula":      formula,
        "benchmark":    benchmark,
        "description":  description,
        "risk_level":   risk_level,
        "anomaly":      anomaly,
        "available":    value is not None,
        "level_params": level_params,
        "components":   components or [],
    }


# ── FY helpers ────────────────────────────────────────────────────────────────

_FY_MONTH_POS = {
    'january': 9, 'february': 10, 'march': 11,
    'april': 0, 'may': 1, 'june': 2, 'july': 3, 'august': 4,
    'september': 5, 'october': 6, 'november': 7, 'december': 8,
}


def _period_to_fy(period: str) -> str:
    """'April 2022' → 'FY 2022-23',  'January 2023' → 'FY 2022-23'"""
    parts = (period or '').strip().split()
    if len(parts) < 2:
        return 'Unknown FY'
    mon = parts[0].lower()
    try:
        yr = int(parts[1])
    except ValueError:
        return 'Unknown FY'
    pos   = _FY_MONTH_POS.get(mon, 0)
    start = yr - 1 if pos >= 9 else yr
    return f"FY {start}-{str(start + 1)[-2:]}"


def _fy_sort_key(fy_label: str) -> int:
    try:
        return int(fy_label.split()[1].split('-')[0])
    except Exception:
        return 9999


# ── FY aggregation ────────────────────────────────────────────────────────────

_SUM_FIELDS = [
    # GSTR-1 fields
    "total_taxable_value", "b2b_taxable_value", "b2cs_taxable_value", "b2cl_taxable_value",
    "nil_taxable_value", "nil_exempt", "nil_non_gst",
    "cdnr_taxable", "cdn_value", "cdnur_taxable",
    "deemed_exports", "deemed_export_value",
    "sez_supplies", "sez_taxable_value",
    "export_taxable_value", "export_value",
    # Canonical export/SEZ/deemed sub-fields (6A/6B/6C) — the fields the MOM shows
    "exp_expwp_taxable", "exp_expwop_taxable", "sez_sezwp_taxable", "sez_sezwop_taxable",
    "de_taxable",
    "debit_notes_taxable",
    "total_igst", "total_cgst", "total_sgst",
    # GSTR-3B output fields
    "taxable_sales", "igst_on_sales", "cgst_on_sales", "sgst_on_sales",
    "zero_rated_sales", "s31b_taxable",
    # GSTR-3B ITC fields (actual parser field names)
    "itc_avail_igst", "itc_avail_cgst", "itc_avail_sgst",
    "itc_igst_available", "itc_cgst_available", "itc_sgst_available",
    "itc_reversed_igst", "itc_reversed_cgst", "itc_reversed_sgst",
    "itc_used_igst", "itc_used_cgst", "itc_used_sgst",
    "itc_d1_igst", "itc_d1_cgst", "itc_d1_sgst",
    "itc_a4_igst", "itc_a4_cgst", "itc_a4_sgst",
    "itc_isd", "itc_temp_reversed", "itc_total",
    # GSTR-3B payment fields
    "cash_paid_igst", "cash_paid_cgst", "cash_paid_sgst",
    "tax_payable_igst", "tax_payable_cgst", "tax_payable_sgst",
    "tax_paid_cash", "tax_paid_itc",
    # RCM
    "s31d_rcm_igst", "rcm_liability", "rcm_igst", "rcm_itc",
    # Export
    "export_turnover",
]


def _sum_fields(ext_list: list) -> dict:
    """Aggregate multiple monthly period extracts into a single FY total dict.

    A field is included only when at least one period had a non-None value
    for it — this preserves genuine zeros (e.g. 0% ITC claimed) while
    keeping fields absent when the parser never extracted them.
    """
    result = {}
    for field in _SUM_FIELDS:
        present = [e.get(field) for e in ext_list if e.get(field) is not None]
        if present:
            result[field] = sum(float(v or 0) for v in present)
    return result


# ── Trend ratio definitions ───────────────────────────────────────────────────
# Each entry: (sl_no, name, unit, risk_direction, compute_fn(g1, g3b))
# risk_direction: "high_bad" = higher value is riskier
#                 "low_bad"  = lower value is riskier
#                 "neutral"  = no inherent direction

def _g3b_sum3(g3b, ik, ck, sk):
    """Sum IGST+CGST+SGST of a GSTR-3B head; None only if all three are absent."""
    i, c, s = g3b.get(ik), g3b.get(ck), g3b.get(sk)
    if i is None and c is None and s is None:
        return None
    return float(i or 0) + float(c or 0) + float(s or 0)


# Canonical GSTR-3B line items — MUST mirror routes/export.py::_build_3b_ext_row.
def _g3b_itc_availed(g3b):
    """Table 4(A) ITC Available — MOM '4(A) Total Avail' columns."""
    return _g3b_sum3(g3b, "itc_avail_igst", "itc_avail_cgst", "itc_avail_sgst")


def _g3b_itc_reversed(g3b):
    """Table 4(B) ITC Reversed — MOM '4(B) Total Rev' columns."""
    return _g3b_sum3(g3b, "itc_reversed_igst", "itc_reversed_cgst", "itc_reversed_sgst")


def _g3b_cash_paid(g3b):
    """Table 6.1 tax paid in cash — MOM 'Cash' columns."""
    return _g3b_sum3(g3b, "cash_paid_igst", "cash_paid_cgst", "cash_paid_sgst")


def _g3b_itc_paid(g3b):
    """Table 6.1 tax paid via ITC — MOM 'ITC' columns."""
    return _g3b_sum3(g3b, "itc_used_igst", "itc_used_cgst", "itc_used_sgst")

def _g3b_total_liab(g3b):
    """Total tax liability per DGARM spec = Table 6.1, Column (2) "Tax payable".

    Prefer the parsed 6.1 Column-(2) values (tax_payable_*). Fall back to
    3.1(a) output tax only when 6.1 Column (2) was not captured (older data).
    """
    tp_i = g3b.get("tax_payable_igst")
    tp_c = g3b.get("tax_payable_cgst")
    tp_s = g3b.get("tax_payable_sgst")
    if tp_i is not None or tp_c is not None or tp_s is not None:
        return float(tp_i or 0) + float(tp_c or 0) + float(tp_s or 0)
    # Fallback: 3.1(a) output tax
    li = g3b.get("igst_on_sales") or g3b.get("total_igst")
    lc = g3b.get("cgst_on_sales") or g3b.get("total_cgst")
    ls = g3b.get("sgst_on_sales") or g3b.get("total_sgst")
    if li is None and lc is None and ls is None:
        return None
    return float(li or 0) + float(lc or 0) + float(ls or 0)


def _g3b_itc_4d1(g3b):
    """ITC reclaimed — Table 4(D)(1), GSTR-3B. None if not parsed."""
    d_i = g3b.get("itc_d1_igst")
    d_c = g3b.get("itc_d1_cgst")
    d_s = g3b.get("itc_d1_sgst")
    if d_i is None and d_c is None and d_s is None:
        return None
    return float(d_i or 0) + float(d_c or 0) + float(d_s or 0)


# ── Canonical GSTR-1 line items ───────────────────────────────────────────────
# SINGLE SOURCE OF TRUTH. These MUST mirror the exact fields the MOM/Excel row
# uses (routes/export.py::_build_ext_row). Every GSTR-1 ratio derives ONLY from
# these accessors — never from parallel/fallback fields — so a ratio can never
# show a number that the MOM table doesn't. (Validated by tests/test_ratio_sources.py)
def g1_total(e):  return e.get("total_taxable_value") or 0          # HSN total (Table 12)
def g1_b2b(e):    return e.get("b2b_taxable_value") or 0            # Table 4A
def g1_b2cl(e):   return e.get("b2cl_taxable_value") or 0           # Table 5A/5B
def g1_b2cs(e):   return e.get("b2cs_taxable_value") or 0           # Table 7
def g1_nongst(e): return e.get("nil_non_gst") or 0                 # Table 8 Non-GST


def g1_cdnr(e):
    """9B CDNR — same precedence as the MOM row (cdn_value fallback)."""
    v = e.get("cdnr_taxable")
    return v if v is not None else (e.get("cdn_value") or 0)


def g1_cdnur(e):  return e.get("cdnur_taxable") or 0               # Table 9B CDNUR
def g1_deemed(e): return e.get("de_taxable") or 0                  # Table 6C Deemed Exports


def g1_sez(e):
    """SEZ supplies (Table 6B) = SEZWP + SEZWOP — the fields the MOM table shows."""
    return (e.get("sez_sezwp_taxable") or 0) + (e.get("sez_sezwop_taxable") or 0)


def _g1_export_turnover(g1):
    """Export turnover (GSTR-1) = Table 6A (EXPWP+EXPWOP) + 6B (SEZWP+SEZWOP).

    Sums ONLY the canonical section sub-fields the MOM table shows. The rolled-up
    `export_taxable_value` field is NOT used — it captures unrelated large values
    on several PDF layouts (e.g. ARSPL FY21-22 it held 77.97cr of garbage).
    """
    return ((g1.get("exp_expwp_taxable") or 0) + (g1.get("exp_expwop_taxable") or 0)
            + (g1.get("sez_sezwp_taxable") or 0) + (g1.get("sez_sezwop_taxable") or 0))


def _g3b_total_turnover_31(g3b):
    """Total Turnover [Table 3.1] = 3.1(a) taxable + 3.1(b) zero-rated."""
    a = g3b.get("taxable_sales") or g3b.get("total_taxable_value") or 0
    b = g3b.get("zero_rated_sales") or g3b.get("s31b_taxable") or 0
    tot = float(a) + float(b)
    return tot or None


def _g3b_isd(g3b):
    """ISD credit — Table 4(A)(4), GSTR-3B (the MOM '4(A)(4) ISD' columns)."""
    v = _g3b_sum3(g3b, "itc_a4_igst", "itc_a4_cgst", "itc_a4_sgst")
    if v is not None:
        return v
    return float(g3b["itc_isd"]) if g3b.get("itc_isd") is not None else None


def _itc_net_trend(g3b):
    """Net ITC for the ITC-to-Turnover ratio (Sl.20) = Table 4(A) − 4(D)(1)."""
    availed = _g3b_itc_availed(g3b)
    if availed is None:
        return None
    return availed - (_g3b_itc_4d1(g3b) or 0)


# _TREND_DEFS format:
# (sl_no, name, unit, direction, compute_fn, low_ok, high_warn, invert, components_fn)
# components_fn(g1, g3b) → list of _comp dicts showing the source numbers for drill-down.
_TREND_DEFS = [
    (20, "ITC to Taxable Turnover", "%", "high_bad",
     lambda g1, g3b: _pct(
         _itc_net_trend(g3b),
         _g3b_total_turnover_31(g3b)),
     60, 80, False,
     lambda g1, g3b: [
         _comp("ITC Availed (4(A) − 4(D)(1))", _itc_net_trend(g3b), "Table 4(A)−4(D)(1), GSTR-3B"),
         _comp("ITC Availed", _g3b_itc_availed(g3b), "Table 4(A), GSTR-3B"),
         _comp("ITC Reclaimed", _g3b_itc_4d1(g3b), "Table 4(D)(1), GSTR-3B"),
         _comp("Total Turnover", _g3b_total_turnover_31(g3b), "Table 3.1 (a+b), GSTR-3B"),
     ]),

    (43, "Cash Payment to Liability", "%", "low_bad",
     lambda g1, g3b: _pct(_g3b_cash_paid(g3b), _g3b_total_liab(g3b)),
     5, 20, True,
     lambda g1, g3b: [
         _comp("Tax Paid via Cash", _g3b_cash_paid(g3b), "Table 6.1, GSTR-3B"),
         _comp("Total Tax Liability", _g3b_total_liab(g3b), "Table 6.1(2), GSTR-3B"),
     ]),

    (42, "ITC Utilization", "%", "high_bad",
     lambda g1, g3b: _pct(_g3b_itc_paid(g3b), _g3b_total_liab(g3b)),
     80, 90, False,
     lambda g1, g3b: [
         _comp("Tax Paid via ITC", _g3b_itc_paid(g3b), "Table 6.1, GSTR-3B"),
         _comp("Total Tax Liability", _g3b_total_liab(g3b), "Table 6.1(2), GSTR-3B"),
     ]),

    (13, "ITC Reversal Ratio", "%", "high_bad",
     lambda g1, g3b: _pct(_g3b_itc_reversed(g3b), _g3b_itc_availed(g3b)),
     5, 15, False,
     lambda g1, g3b: [
         _comp("ITC Reversed", _g3b_itc_reversed(g3b), "Table 4(B), GSTR-3B"),
         _comp("ITC Availed", _g3b_itc_availed(g3b), "Table 4(A), GSTR-3B"),
     ]),

    (30, "B2B Credit Note Ratio", "%", "high_bad",
     lambda g1, g3b: None if g1.get("legacy_combined_b2b") else _pct(
         abs(g1.get("cdnr_taxable") or g1.get("cdn_value") or 0),
         abs(g1.get("b2b_taxable_value") or 0)),
     5, 15, False,
     lambda g1, g3b: [
         _comp("B2B Credit Notes (CDNR)", abs(g1.get("cdnr_taxable") or g1.get("cdn_value") or 0), "Table 9B, GSTR-1"),
         _comp("B2B Sales", abs(g1.get("b2b_taxable_value") or 0), "Table 4A, GSTR-1"),
     ]),

    # Output Tax to Net ITC removed from trend (per user instruction)

    (1,  "Deemed Export Ratio", "%", "high_bad",
     lambda g1, g3b: _pct(g1_deemed(g1), g1_total(g1)),
     10, 30, False,
     lambda g1, g3b: [
         _comp("Deemed Exports", g1_deemed(g1), "Table 6(c), GSTR-1"),
         _comp("Total Taxable Turnover", g1_total(g1), "GSTR-1 Total"),
     ]),

    (41, "Export Turnover Ratio", "%", "neutral",
     lambda g1, g3b: _pct(
         _g1_export_turnover(g1),
         g1.get("total_taxable_value") or 0),
     30, 60, False,
     lambda g1, g3b: [
         _comp("Export Turnover", _g1_export_turnover(g1), "Table 6A/6B, GSTR-1"),
         _comp("Total Taxable Turnover", g1.get("total_taxable_value") or 0, "GSTR-1 Total"),
     ]),

    (11, "ISD Credit Ratio", "%", "high_bad",
     lambda g1, g3b: _pct(_g3b_isd(g3b), _g3b_itc_availed(g3b)),
     15, 30, False,
     lambda g1, g3b: [
         _comp("ISD Credit", _g3b_isd(g3b), "Table 4(A)(4), GSTR-3B"),
         _comp("Total ITC Availed", _g3b_itc_availed(g3b), "Table 4(A), GSTR-3B"),
     ]),
]


def _fy_trend_ratios(fy_g1: dict, fy_g3b: dict, sorted_fys: list) -> dict:
    """
    Compute per-FY ratio values and trend metadata for the trend table.

    Returns:
        {
          "fys":    ["FY 2019-20", "FY 2020-21", ...],
          "ratios": [{sl_no, name, unit, direction, values, trend, trend_risk, trend_risky}, ...]
        }
    """
    rows = []
    for sl, name, unit, direction, fn, low_ok, high_warn, invert, comp_fn in _TREND_DEFS:
        values     = {}
        components = {}   # {fy: [_comp dicts]}
        for fy in sorted_fys:
            g1  = fy_g1.get(fy, {})
            g3b = fy_g3b.get(fy, {})
            try:
                val = fn(g1, g3b)
            except Exception:
                val = None
            if val is not None:
                values[fy] = val
            try:
                components[fy] = comp_fn(g1, g3b)
            except Exception:
                components[fy] = []

        seq = [values[fy] for fy in sorted_fys if fy in values]

        # Trend direction
        trend = "stable"
        if len(seq) >= 2:
            delta = seq[-1] - seq[0]
            if abs(delta) > 1.0:
                trend = "rising" if delta > 0 else "falling"

        # Is the trend moving toward risk?
        trend_risky = (
            (direction == "high_bad" and trend == "rising") or
            (direction == "low_bad"  and trend == "falling")
        )

        # Risk level at the latest FY value using per-ratio thresholds
        last = seq[-1] if seq else None
        trend_risk = _level(last, low_ok, high_warn, invert) if last is not None else "UNKNOWN"

        rows.append({
            "sl_no":       sl,
            "name":        name,
            "unit":        unit,
            "direction":   direction,
            "values":      values,
            "components":  components,
            "trend":       trend,
            "trend_risk":  trend_risk,
            "trend_risky": trend_risky,
        })

    return {"fys": sorted_fys, "ratios": rows}


# ── GSTR-1 ratios (per period) ────────────────────────────────────────────────

def _gstr1_ratios(ext: dict) -> list:
    # Canonical accessors only — identical to the MOM/Excel row source fields.
    total_taxable  = g1_total(ext)
    b2b_taxable    = g1_b2b(ext)
    b2cl_taxable   = g1_b2cl(ext)
    nil_non_gst    = g1_nongst(ext)
    cdnr_taxable   = g1_cdnr(ext)
    cdnur_taxable  = g1_cdnur(ext)
    deemed_exports = g1_deemed(ext)          # Table 6C (was deemed_exports/deemed_export_value)
    sez_supplies   = g1_sez(ext)             # Table 6B (was sez_supplies/sez_taxable_value)
    export_taxable = _g1_export_turnover(ext)
    debit_notes    = ext.get("debit_notes_taxable") or 0

    # Old compact GSTR-1 layout (FY≈2020-21/21-22) merges B2B+SEZ+DE into one row,
    # so b2b_taxable_value is not pure B2B — exclude such years from B2B-denominator
    # ratios (per user decision). Total-turnover ratios still use the correct HSN total.
    legacy_b2b = bool(ext.get("legacy_combined_b2b"))

    r1   = _pct(deemed_exports, total_taxable) if total_taxable else None
    r5   = _pct(sez_supplies, total_taxable)   if total_taxable else None
    # CDN values are stored as negatives (they reduce liability) — use abs()
    r30  = None if legacy_b2b else (_pct(abs(cdnr_taxable), abs(b2b_taxable)) if b2b_taxable else None)
    r30a = _pct(abs(cdnur_taxable), abs(b2cl_taxable))   if b2cl_taxable  else None
    r31  = _pct(abs(cdnur_taxable), abs(export_taxable)) if export_taxable else None
    r32  = _pct(abs(debit_notes),   abs(total_taxable))  if total_taxable  else None
    r39  = _pct(nil_non_gst, total_taxable)    if total_taxable else None
    r41  = _pct(export_taxable, total_taxable) if total_taxable else None

    return [
        _r(1, "DGARM #22", "Deemed Exports",
           "Deemed Export to Total Turnover Ratio", r1, "%",
           "Deemed Exports [Table 6(c), GSTR-1] ÷ Total GST Turnover × 100",
           "Should align with sector norm; sudden spike warrants check",
           "High ratio may indicate over-reporting or misclassification of domestic supplies as deemed exports.",
           _level(r1, 10, 30),
           level_params={"low_ok": 10, "high_warn": 30},
           components=[
               _comp("Deemed Exports", deemed_exports, "Table 6(c), GSTR-1"),
               _comp("Total Taxable Turnover", total_taxable, "GSTR-1 Total"),
           ]),

        _r(5, "DGARM #23", "Exports",
           "Zero-Rated (SEZ) Turnover Ratio", r5, "%",
           "SEZ Supplies [Table 6B, GSTR-1] ÷ Total Turnover × 100",
           "Benchmark varies by sector",
           "Unusually high SEZ supply ratio may indicate diversion of goods or misuse of zero-rating benefits.",
           _level(r5, 20, 50),
           level_params={"low_ok": 20, "high_warn": 50},
           components=[
               _comp("SEZ Supplies", sez_supplies, "Table 6B, GSTR-1"),
               _comp("Total Taxable Turnover", total_taxable, "GSTR-1 Total"),
           ]),

        _r(30, "DGARM #31", "Outward",
           "B2B Credit Note to B2B Sales Ratio", r30, "%",
           "CDNR [Table 9B, GSTR-1] ÷ B2B Sales [Table 4A, GSTR-1] × 100",
           "< 5% normal; > 15% high risk",
           "Excessive credit notes vs B2B sales may indicate deferred billing, cancelled supplies after goods movement, or credit notes issued beyond permissible time.",
           _level(r30, 5, 15),
           anomaly=(r30 is not None and r30 > 15),
           level_params={"low_ok": 5, "high_warn": 15},
           components=[
               _comp("B2B Credit Notes (CDNR)", abs(cdnr_taxable), "Table 9B, GSTR-1"),
               _comp("B2B Sales", abs(b2b_taxable), "Table 4A, GSTR-1"),
           ]),

        _r("30A", "DGARM #31c", "Outward",
           "Unregistered Credit Note to B2CL Sales Ratio", r30a, "%",
           "CDNUR [Table 9B, GSTR-1] ÷ B2CL Sales [Table 5, GSTR-1] × 100",
           "< 5% normal; > 15% high risk",
           "High unregistered credit note ratio vs B2CL sales may indicate inflated sales to unregistered persons subsequently reversed via credit notes.",
           _level(r30a, 5, 15),
           anomaly=(r30a is not None and r30a > 15),
           level_params={"low_ok": 5, "high_warn": 15},
           components=[
               _comp("Unregistered Credit Notes (CDNUR)", abs(cdnur_taxable), "Table 9B, GSTR-1"),
               _comp("B2CL Sales (Unregistered)", abs(b2cl_taxable), "Table 5, GSTR-1"),
           ]),

        _r(31, "DGARM #31b", "Outward",
           "Export Credit Note to Export Turnover Ratio", r31, "%",
           "Export-related CDNUR [Table 9B, GSTR-1] ÷ Export Turnover [Table 6A/6B, GSTR-1] × 100",
           "< 5% normal; drastic change warrants scrutiny",
           "High ratio of export credit notes to export turnover may indicate inflated export values or fake export refund claims.",
           _level(r31, 5, 15),
           anomaly=(r31 is not None and r31 > 15),
           level_params={"low_ok": 5, "high_warn": 15},
           components=[
               _comp("Export Credit Notes (CDNUR)", abs(cdnur_taxable), "Table 9B, GSTR-1"),
               _comp("Export Turnover", abs(export_taxable), "Table 6A/6B, GSTR-1"),
           ]),

        _r(32, "DGARM #32", "Outward",
           "Debit Note to Taxable Turnover Ratio", r32, "%",
           "Debit Notes [Table 9B, GSTR-1] ÷ Total GST Taxable Turnover × 100",
           "< 5% normal",
           "High debit note ratio indicates under-invoicing corrected via debit notes, or inflated subsequent claims.",
           _level(r32, 5, 15),
           level_params={"low_ok": 5, "high_warn": 15},
           components=[
               _comp("Debit Notes", abs(debit_notes), "Table 9B, GSTR-1"),
               _comp("Total Taxable Turnover", abs(total_taxable), "GSTR-1 Total"),
           ]),

        _r(39, "Derived", "Outward",
           "Non-GST Supply Ratio", r39, "%",
           "Non-GST Supplies [Table 8, GSTR-1] ÷ Total Turnover [GSTR-1] × 100",
           "Should be minimal; high ratio triggers taxability review",
           "High Non-GST supply ratio warrants verification of whether correct taxability has been adopted.",
           _level(r39, 5, 15),
           level_params={"low_ok": 5, "high_warn": 15},
           components=[
               _comp("Non-GST Supplies", nil_non_gst, "Table 8, GSTR-1"),
               _comp("Total Taxable Turnover", total_taxable, "GSTR-1 Total"),
           ]),

        _r(41, "DGARM #41", "Outward",
           "Export Turnover Ratio", r41, "%",
           "Export Turnover [Table 6A, GSTR-1] ÷ Total GST Turnover [GSTR-1 excl. Table 8] × 100",
           "Should be consistent with historical export trend",
           "Sudden growth in export ratio without corresponding shipping bill data may indicate fake export refund claims.",
           _level(r41, 30, 60),
           level_params={"low_ok": 30, "high_warn": 60},
           components=[
               _comp("Export Turnover", export_taxable, "Table 6A, GSTR-1"),
               _comp("Total Taxable Turnover", total_taxable, "GSTR-1 Total"),
           ]),
    ]


# ── GSTR-3B ratios (per period) ───────────────────────────────────────────────

def _gstr3b_ratios(ext: dict) -> list:
    # Output tax (Table 3.1)
    taxable   = ext.get("taxable_sales") or ext.get("total_taxable_value") or 0
    igst_liab = ext.get("igst_on_sales") or ext.get("total_igst") or 0
    cgst_liab = ext.get("cgst_on_sales") or ext.get("total_cgst") or 0
    sgst_liab = ext.get("sgst_on_sales") or ext.get("total_sgst") or 0
    total_liab = igst_liab + cgst_liab + sgst_liab

    # ITC availed — Table 4(A) gross available
    itc_igst    = ext.get("itc_avail_igst") or ext.get("itc_igst_available") or ext.get("itc_igst") or 0
    itc_cgst    = ext.get("itc_avail_cgst") or ext.get("itc_cgst_available") or ext.get("itc_cgst") or 0
    itc_sgst    = ext.get("itc_avail_sgst") or ext.get("itc_sgst_available") or ext.get("itc_sgst") or 0
    itc_availed = ext.get("itc_total") or (itc_igst + itc_cgst + itc_sgst)

    # ITC reversed — Table 4(B)
    itc_rev_igst = ext.get("itc_reversed_igst") or 0
    itc_rev_cgst = ext.get("itc_reversed_cgst") or 0
    itc_rev_sgst = ext.get("itc_reversed_sgst") or 0
    itc_reversed = ext.get("itc_reversed") or (itc_rev_igst + itc_rev_cgst + itc_rev_sgst)
    itc_net      = itc_availed - itc_reversed

    # ISD and temporary reversal (may not be present in all GSTR-3B formats)
    itc_isd      = ext.get("itc_isd") or 0
    itc_temp_rev = ext.get("itc_temp_reversed") or 0

    # Payments — Table 6.1
    cash_igst = ext.get("cash_paid_igst") or ext.get("cash_igst") or 0
    cash_cgst = ext.get("cash_paid_cgst") or ext.get("cash_cgst") or 0
    cash_sgst = ext.get("cash_paid_sgst") or ext.get("cash_sgst") or 0
    cash_paid = ext.get("tax_paid_cash") or (cash_igst + cash_cgst + cash_sgst)

    itc_used_igst = ext.get("itc_used_igst") or 0
    itc_used_cgst = ext.get("itc_used_cgst") or 0
    itc_used_sgst = ext.get("itc_used_sgst") or 0
    # itc_paid must NOT fall back to itc_net — ITC used for payment ≠ net ITC in ledger
    _itc_paid_raw = ext.get("tax_paid_itc") or (itc_used_igst + itc_used_cgst + itc_used_sgst) or None
    itc_paid = _itc_paid_raw if _itc_paid_raw is not None else None

    # RCM — Table 3.1(d)
    rcm_liability = ext.get("s31d_rcm_igst") or ext.get("rcm_liability") or ext.get("rcm_igst") or 0
    rcm_itc       = ext.get("rcm_itc") or 0

    # Export turnover (Table 3.1(b)) — not always extracted in GSTR-3B parser
    export_turn = ext.get("export_turnover") or ext.get("export_taxable_value") or 0

    r11  = _pct(itc_isd, itc_availed)     if itc_availed  else None
    r13  = _pct(itc_reversed, itc_availed) if itc_availed  else None
    r16  = _pct(itc_availed, export_turn)  if export_turn  else None
    r18  = _pct(itc_temp_rev, itc_availed) if itc_availed  else None
    r20  = _pct(itc_net, taxable)          if taxable      else None
    r29  = _pct(total_liab, itc_net)       if itc_net      else None
    r42  = _pct(itc_paid, total_liab)      if total_liab   else None
    r43  = _pct(cash_paid, total_liab)     if total_liab   else None
    r45  = _pct(cash_paid, total_liab)     if total_liab   else None
    r48  = round(float(rcm_liability) - float(rcm_itc or 0), 2) if rcm_liability else None

    return [
        _r(11, "DGARM #17", "Inward",
           "ISD Credit to Total ITC Ratio", r11, "%",
           "ISD Credit [Table 4(A)(4), GSTR-3B] ÷ Total ITC Availed [Table 4(A)] × 100",
           "Should align with actual ISD distribution; > 30% warrants check",
           "Disproportionately high ISD credit relative to total ITC may indicate inflated or fabricated ISD transfers.",
           _level(r11, 15, 30),
           level_params={"low_ok": 15, "high_warn": 30},
           components=[
               _comp("ISD Credit", itc_isd, "Table 4(A)(4), GSTR-3B"),
               _comp("Total ITC Availed", itc_availed, "Table 4(A), GSTR-3B"),
           ]),

        _r(13, "DGARM #18", "Inward",
           "ITC Reversal to ITC Availed Ratio", r13, "%",
           "ITC Reversed [Table 4(B), GSTR-3B] ÷ ITC Availed [Table 4(A), GSTR-3B] × 100",
           "< 5% normally; > 15% may indicate incorrect ITC initially claimed",
           "A high reversal rate suggests ineligible ITC was claimed and later reversed. Also check GSTR-9: Table 7 ÷ Table 6.",
           _level(r13, 5, 15),
           level_params={"low_ok": 5, "high_warn": 15},
           components=[
               _comp("ITC Reversed", itc_reversed, "Table 4(B), GSTR-3B"),
               _comp("ITC Availed", itc_availed, "Table 4(A), GSTR-3B"),
           ]),

        _r(16, "DGARM #16", "Inward",
           "ITC to Export Turnover Ratio", r16, "%",
           "ITC Availed [Table 4(A)/(C), GSTR-3B] ÷ Export Turnover [Table 3.1(b), GSTR-3B] × 100",
           "Should align with input content of exports; drastic change indicates fake billing",
           "Drastic change may indicate fake billing to procure export refunds. Note: IMS filers use Table 4(A); non-IMS filers use Table 4(C).",
           _level(r16, 100, 150),
           anomaly=(r16 is not None and r16 > 150),
           level_params={"low_ok": 100, "high_warn": 150},
           components=[
               _comp("ITC Availed", itc_availed, "Table 4(A)/(C), GSTR-3B"),
               _comp("Export Turnover", export_turn, "Table 3.1(b), GSTR-3B"),
           ]),

        _r(18, "Derived", "Inward",
           "Temporary ITC Reversal Ratio", r18, "%",
           "ITC Temporarily Reversed [Table 4(B)(2), GSTR-3B] ÷ ITC Availed [Table 4(A)(5), GSTR-3B] × 100",
           "High ratio indicates recurring short-term reversals that may be reclaimed",
           "A high temporary reversal ratio means large ITC amounts are periodically reversed and reclaimed — the reason for each reversal is important to assess compliance.",
           _level(r18, 5, 15),
           level_params={"low_ok": 5, "high_warn": 15},
           components=[
               _comp("ITC Temporarily Reversed", itc_temp_rev, "Table 4(B)(2), GSTR-3B"),
               _comp("ITC Availed", itc_availed, "Table 4(A)(5), GSTR-3B"),
           ]),

        _r(20, "DGARM #20", "Inward",
           "ITC to Taxable Turnover Ratio", r20, "%",
           "Net ITC [Table 4(A)−4(D)(1), GSTR-3B] ÷ Total Turnover [Table 3.1, GSTR-3B] × 100",
           "< 60% for most sectors; > 80% indicates high purchase-to-sales ratio",
           "Very high ITC to turnover ratio signals low value addition — a strong indicator of fake invoicing or ineligible ITC. Also verify in GSTR-9: Table 6O−6H ÷ Table 5N.",
           _level(r20, 60, 80),
           anomaly=(r20 is not None and r20 > 80),
           level_params={"low_ok": 60, "high_warn": 80},
           components=[
               _comp("Net ITC (Availed − Reversed)", itc_net, "Table 4(A)−4(D)(1), GSTR-3B"),
               _comp("ITC Availed", itc_availed, "Table 4(A), GSTR-3B"),
               _comp("ITC Reversed", itc_reversed, "Table 4(B), GSTR-3B"),
               _comp("Taxable Turnover", taxable, "Table 3.1(a), GSTR-3B"),
           ]),

        _r(29, "DGARM #1", "Output-Input",
           "Output Tax to Net ITC Ratio", r29, "%",
           "Total Tax Liability [Table 3.1(a+b), GSTR-3B] ÷ Net ITC Availed [Table 4A−4D(1), GSTR-3B] × 100",
           "> 100% is normal; < 50% is a risk flag",
           "A low ratio of output tax to ITC indicates higher purchases relative to sales — may signal ITC inflation or fake procurement.",
           _level(r29, 50, 80, invert=True),
           level_params={"low_ok": 50, "high_warn": 80, "invert": True},
           components=[
               _comp("Total Tax Liability (IGST+CGST+SGST)", total_liab, "Table 3.1(a+b), GSTR-3B"),
               _comp("Net ITC (Availed − Reversed)", itc_net, "Table 4A−4D(1), GSTR-3B"),
           ]),

        _r(42, "DGARM #7", "Payment",
           "ITC Utilization Ratio (Tax Paid via ITC)", r42, "%",
           "Tax Paid through ITC [Table 6.1, GSTR-3B] ÷ Total Tax Liability [Table 6.1(2)] × 100",
           "> 90% triggers high risk flag",
           "Very high ITC utilization in high-value-addition sectors may indicate fake ITC claims or circular trading to inflate credit balances.",
           _level(r42, 80, 90),
           level_params={"low_ok": 80, "high_warn": 90},
           components=[
               _comp("Tax Paid via ITC", itc_paid, "Table 6.1, GSTR-3B"),
               _comp("Total Tax Liability", total_liab, "Table 6.1(2), GSTR-3B"),
           ]),

        _r(43, "DGARM #8", "Payment",
           "Cash Payment to Total Liability Ratio", r43, "%",
           "Tax Paid through Cash [Table 6.1, GSTR-3B] ÷ Total Tax Liability [Table 6.1(2)] × 100",
           "< 5% is a risk flag",
           "Very low cash payment ratio suggests almost all liability is offset by ITC — may indicate excess or fake ITC claims.",
           _level(r43, 5, 20, invert=True),
           level_params={"low_ok": 5, "high_warn": 20, "invert": True},
           components=[
               _comp("Tax Paid via Cash", cash_paid, "Table 6.1, GSTR-3B"),
               _comp("Total Tax Liability", total_liab, "Table 6.1(2), GSTR-3B"),
           ]),

        _r(45, "Derived", "Payment",
           "Minimum 1% Cash Payment Compliance", r45, "%",
           "Total Cash Paid ÷ Total Tax Payable [Table 6.1, GSTR-3B] × 100",
           "Minimum 1% of tax liability must be paid in cash each year",
           "Cash payment below 1% of total tax liability may indicate non-compliance with mandatory minimum cash payment rules.",
           "LOW" if (r45 is not None and r45 >= 1.0) else "HIGH",
           anomaly=(r45 is not None and r45 < 1.0),
           level_params=lambda v: "LOW" if (v is not None and v >= 1.0) else "HIGH",
           components=[
               _comp("Tax Paid via Cash", cash_paid, "Table 6.1, GSTR-3B"),
               _comp("Total Tax Liability", total_liab, "Table 6.1(2), GSTR-3B"),
           ]),

        _r(48, "DGARM #16r", "RCM",
           "RCM Liability vs RCM ITC Gap", r48, "₹",
           "RCM Paid [Table 3.1(d), GSTR-3B] − ITC Availed [Table 4(A)(2)+4(A)(3), GSTR-3B]",
           "Should be near zero; positive gap indicates short payment under RCM",
           "A large positive gap between RCM liability and RCM ITC availed indicates under-payment of reverse charge tax.",
           "LOW" if (r48 is None or abs(r48) < 10_000) else ("MEDIUM" if abs(r48) < 1_00_000 else "HIGH"),
           level_params=lambda v: "LOW" if (v is None or abs(v) < 10_000) else ("MEDIUM" if abs(v) < 1_00_000 else "HIGH"),
           components=[
               _comp("RCM Liability", rcm_liability, "Table 3.1(d), GSTR-3B"),
               _comp("RCM ITC Availed", rcm_itc, "Table 4(A)(2)+(3), GSTR-3B"),
           ]),
    ]


# ── GSTR-2B stubs (unavailable until 2B extraction is wired in) ───────────────

def _gstr2b_stubs() -> list:
    def stub(sl, dgarm, cat, name, formula, desc):
        r = _r(sl, dgarm, cat, name, None, "%", formula, "Requires GSTR-2B data", desc, "UNKNOWN")
        r["status"] = "Requires GSTR-2B"
        return r

    return [
        stub(9,  "DGARM #14", "Inward",
             "GSTR-2B vs GSTR-3B ITC Gap",
             "ITC [Table 4(A)(5)−4(D)(1), GSTR-3B] − ITC as per GSTR-2B",
             "Positive gap indicates ITC claimed in GSTR-3B exceeds what suppliers reported — direct indicator of excess or fake ITC."),
        stub(10, "DGARM #15", "Inward",
             "Import ITC vs IGST Paid to Customs",
             "ITC on Import of Goods [Table 4(A)(1), GSTR-3B] − IGST Paid to Customs [IMPG, GSTR-2B]",
             "Positive difference means ITC claimed on imports exceeds IGST paid to customs — direct indicator of inflated import ITC."),
        stub(17, "Derived",   "Inward",
             "GSTR-2B to GSTR-3B ITC Ratio",
             "ITC as per GSTR-2B ÷ ITC Availed [Table 4(A)(5)−4(D)(1), GSTR-3B] × 100",
             "Ratio below 100% indicates ITC availed exceeds GSTR-2B reflected credit — strong indicator of fake or ineligible ITC."),
        stub(49, "Derived",   "RCM",
             "RCM Liability: GSTR-2B vs GSTR-3B",
             "RCM Liability as per GSTR-2B ÷ RCM Paid [Table 3.1(d), GSTR-3B] × 100",
             "Ratio above 100% indicates RCM liability in GSTR-2B exceeds what was paid in GSTR-3B — potential under-payment of reverse charge tax."),
    ]


# ── Framework completeness: manual / external-data ratios ─────────────────────
# The DGARM v2 framework defines 57 ratios. ~30 are auto-computable from the
# GSTR-1/GSTR-3B PDFs (the sections above) and 4 more become live once GSTR-2B
# is uploaded (_gstr2b_stubs). The remaining ratios below require data that is
# simply not present in a GSTR-1 or GSTR-3B return (ITR, ITC-04, customs/
# shipping-bill data, refund records, DGARM red-flag reports) or call for manual
# document sampling. They are emitted with value=None and a clear `status` so the
# report maps 1:1 to the full 57-ratio framework instead of silently dropping them.

def _framework_manual_stubs() -> list:
    def stub(sl, dgarm, cat, name, formula, status, desc):
        r = _r(sl, dgarm, cat, name, None, "", formula, status, desc, "UNKNOWN")
        r["status"] = status
        return r

    REQ_CUSTOMS = "Requires Customs/ICEGATE data"
    REQ_ITR     = "Requires Income-Tax Return"
    REQ_ITC04   = "Requires ITC-04 return"
    REQ_REFUND  = "Requires refund (RFD) data"
    REQ_DGARM   = "Requires DGARM red-flag report"
    REQ_EXT     = "Requires external/portal data"
    MANUAL      = "Manual verification"

    return [
        stub(4,  "DGARM #20", "Exports", "Export (Goods) Taxable vs Shipping Bill IGST",
             "Export taxable value [Table 6A, GSTR-1] vs IGST value in shipping-bill data",
             REQ_CUSTOMS, "Compares declared export value against customs shipping-bill data."),
        stub(7,  "DGARM #2", "Import", "Import IGST Paid vs ITC Availed",
             "IGST paid at import vs ITC availed on import of goods",
             REQ_CUSTOMS, "Flags ITC on imports exceeding IGST actually paid at customs."),
        stub(8,  "DGARM #13", "Input Output", "SEZ & Non-SEZ Input-Output Ratio",
             "SEZ vs Non-SEZ input-output ratio (verified separately)",
             MANUAL, "Detects diversion of duty-free inputs to DTA units; needs unit-wise input data."),
        stub(15, "DGARM #19", "Inward", "ITC Reversal for Nil/Exempt Supplies",
             "Proper ITC reversal / non-availment for Nil/Exempt supplies",
             MANUAL, "Verifies Rule 42/43 reversal against exempt turnover via document sampling."),
        stub(19, "Derived", "Inward", "Common ITC Reversal Ratio (Rules 42/43)",
             "Common ITC reversed (Rules 42 & 43) ÷ Total ITC availed",
             MANUAL, "Abnormally low common-credit reversal vs exempt supplies warrants review."),
        stub(21, "Derived", "Inward", "High ITC from Risky Suppliers",
             "% of ITC availed from newly-registered / flagged / cancelled suppliers",
             REQ_EXT, "Needs supplier risk-profile data from the portal/DGARM."),
        stub(22, "Derived", "Inward", "Delayed Filings with High ITC",
             "Pattern of late filing in periods with large ITC claims",
             REQ_EXT, "Needs return filing-date metadata."),
        stub(23, "DGARM #34", "IT Returns", "Negligible Income Tax vs GSTR-3B Turnover",
             "Income-tax paid (ITR) vs turnover declared in GSTR-3B",
             REQ_ITR, "Substantial GST turnover with negligible income tax warrants check."),
        stub(24, "DGARM #29", "ITC-04", "ITC-04 Job-work Turnover vs GSTR-3B Turnover",
             "Taxable turnover [Table 4, ITC-04] ÷ Total taxable turnover [GSTR-3B]",
             REQ_ITC04, "Needs the ITC-04 job-work return."),
        stub(25, "DGARM #11", "Late Fee & Interest", "Late Fee & Interest on Late Filing",
             "Penalty/late-fee and interest for late-filed returns",
             MANUAL, "Verify late-fee and interest discharge for delayed returns."),
        stub(26, "DGARM #12", "Late Fee & Interest", "Liability/Penalty for Non-filed Periods",
             "Correct liability + penalty + interest for non-filed periods",
             MANUAL, "Assess liability for periods where returns were not filed."),
        stub(28, "DGARM #3", "NIL/Exempt", "NIL/Exempt Supply Correctness",
             "Correctness of conditions for NIL/Exempt supplies",
             MANUAL, "Sample contracts / supply orders to confirm exemption eligibility."),
        stub(33, "DGARM #33", "IT Returns", "GSTR-3B Turnover vs ITR Turnover",
             "Turnover in GSTR-3B vs turnover in ITR for the same period",
             REQ_ITR, "Reconcile GST turnover against income-tax return turnover."),
        stub(36, "Derived", "Outward", "TDS Credits Accumulation",
             "Comparison of accumulation of TDS credits",
             REQ_EXT, "Needs TDS credit ledger data."),
        stub(37, "Derived", "Outward", "HSN/SAC Volatility Analysis",
             "Consistency of HSN/SAC codes reported for outward supplies",
             MANUAL, "Frequent HSN/SAC changes may indicate deliberate misclassification."),
        stub(38, "Derived", "Outward", "Frequency of Amendments",
             "Number & value of amendments made in GSTR-1",
             REQ_EXT, "High amendment frequency reducing liability is a risk indicator."),
        stub(40, "Derived", "Outward", "Circular Transactions",
             "Outward and inward both reported with the same counter-party",
             REQ_EXT, "Indicates fake billing or shifting of liability."),
        stub(46, "DGARM #5", "RCM", "Total Inward Supplies Liable to RCM (Correctness)",
             "Correctness of total inward supplies liable to reverse charge",
             MANUAL, "Sample high-value invoices for RCM applicability."),
        stub(48, "DGARM #16", "RCM", "Low RCM Payment 3.1(d) vs Import-Services ITC",
             "RCM paid [Table 3.1(d), GSTR-3B] vs ITC on import of services / other RCM",
             MANUAL, "Low RCM payment relative to RCM ITC taken warrants review."),
        stub(50, "DGARM #25", "Refund", "IGST Refund (Risky Exporters)",
             "Amount of IGST refund claimed",
             REQ_REFUND, "High-value IGST refund claims by risky exporters."),
        stub(51, "DGARM #10", "NIL/Exempt", "Non-GST Supply Invoice Verification",
             "Sample Non-GST supply invoices not liable to GST",
             MANUAL, "Confirm high-value Non-GST purchases are genuinely outside GST."),
        stub(52, "DGARM #21", "Exports", "SEZ Supplies Correctness",
             "Correctness of zero-rated supplies made to SEZ",
             MANUAL, "Higher-than-trend SEZ clearance needs verification."),
        stub(53, "DGARM #24", "IT Returns", "Linked GSTINs of Same PAN",
             "Risk from multiple GSTINs registered under the same PAN",
             REQ_EXT, "Check supply/purchase transactions across linked GSTINs."),
        stub(54, "DGARM #26", "Exports", "LUT Export Refund (Risky Exporters)",
             "Amount of LUT export refund claimed",
             REQ_REFUND, "High-value LUT-export refund claims by risky exporters."),
        stub(55, "DGARM #27", "Exports", "Inverted Duty Refund (Risky Exporters)",
             "Refund claimed due to inverted duty structure",
             REQ_REFUND, "Inverted-duty refunds flagged for risky exporters."),
        stub(56, "DGARM #28", "Others", "Risky Taxpayer in DGARM Red Flag Report",
             "Presence in DGARM Red Flag Report Nos. 2,3,4 & 5",
             REQ_DGARM, "Cross-check against DGARM red-flag reports."),
        stub(57, "DGARM #30", "Others", "Repeat Risk Selection (Prior Year)",
             "Whether the taxpayer was selected on risk criteria last year",
             MANUAL, "Re-examine the same risk in the current audit period."),
    ]


# ── Cross-form ratios ─────────────────────────────────────────────────────────

def _cross_form_ratios(gstr1: dict, gstr3b: dict) -> list:
    g1_taxable  = gstr1.get("total_taxable_value") or 0
    g3b_taxable = gstr3b.get("total_taxable_value") or gstr3b.get("taxable_sales") or 0

    tv_var = None
    if g1_taxable and g3b_taxable:
        tv_var = _pct(abs(g1_taxable - g3b_taxable), max(g1_taxable, g3b_taxable))

    return [
        _r(33, "DGARM #33", "Outward",
           "Turnover Mismatch: GSTR-1 vs GSTR-3B", tv_var, "%",
           "|GSTR-1 Taxable − GSTR-3B Taxable| ÷ max(both) × 100",
           "< 2% after adjustments is acceptable",
           "GSTR-1 reports outward supply details; GSTR-3B is the summary return. A mismatch (especially GSTR-3B < GSTR-1) indicates under-declaration of liability.",
           _level(tv_var, 2, 10),
           anomaly=(tv_var is not None and tv_var > 10),
           level_params={"low_ok": 2, "high_warn": 10},
           components=[
               _comp("Taxable Turnover (GSTR-1)", g1_taxable, "GSTR-1 Total"),
               _comp("Taxable Turnover (GSTR-3B)", g3b_taxable, "Table 3.1(a), GSTR-3B"),
               _comp("Absolute Difference", abs(g1_taxable - g3b_taxable) if g1_taxable and g3b_taxable else None, "Computed"),
           ]),
    ]


# ── Multi-period ratios (YOY within an upload batch) ─────────────────────────

def _multiperiod_ratios(gstr1_list: list, gstr3b_list: list) -> list:
    ratios = []

    if len(gstr1_list) >= 2:
        total_list  = [g1_total(e)  for e in gstr1_list]
        deemed_list = [g1_deemed(e) for e in gstr1_list]
        sez_list    = [g1_sez(e)    for e in gstr1_list]
        cdn_list    = [g1_cdnr(e) + g1_cdnur(e) for e in gstr1_list]

        valid_t = [t for t in total_list if t > 0]

        # Sl.27 — Average Monthly Taxable Turnover Decline (#9)
        if len(valid_t) >= 2:
            first, last = valid_t[0], valid_t[-1]
            decline = _pct(first - last, first) if first else None
            ratios.append(_r(27, "DGARM #9", "Monthly Ratio",
                "Average Monthly Taxable Turnover Decline", decline, "%",
                "(First Period Turnover − Last Period Turnover) ÷ First Period × 100",
                "Positive = declining trend; > 20% warrants enquiry",
                "A significant and sustained decline in monthly taxable turnover may indicate business contraction, evasion, or unreported supplies.",
                _level(decline, 10, 25) if decline and decline > 0 else "LOW",
                level_params={"low_ok": 10, "high_warn": 25}))

        def _yoy_change(values, totals):
            pairs = [(v, t) for v, t in zip(values, totals) if t > 0]
            if len(pairs) < 2:
                return None
            r0 = _pct(pairs[0][0], pairs[0][1])
            r1 = _pct(pairs[-1][0], pairs[-1][1])
            return round(r1 - r0, 2) if r0 is not None and r1 is not None else None

        yoy_deemed = _yoy_change(deemed_list, total_list)
        ratios.append(_r(2, "DGARM #22b", "Deemed Exports",
            "YOY Change in Deemed Export Ratio", yoy_deemed, "%pts",
            "(Current Period Deemed Export Ratio − Prior Period Ratio) in percentage points",
            "Significant increase warrants scrutiny",
            "A large increase in the deemed export ratio may indicate diversion of taxable domestic supplies to the deemed export category.",
            _level(abs(yoy_deemed) if yoy_deemed is not None else None, 20, 50),
            level_params={"low_ok": 20, "high_warn": 50}))

        yoy_sez = _yoy_change(sez_list, total_list)
        ratios.append(_r(6, "DGARM #23b", "Exports",
            "YOY Change in Zero-Rated (SEZ) Supply Ratio", yoy_sez, "%pts",
            "(Current Period SEZ Ratio − Prior Period SEZ Ratio) in percentage points",
            "Stable trend expected; large spike warrants check",
            "A sudden increase in the SEZ supply ratio may indicate misuse of zero-rating benefits or diversion to SEZ for refund claims.",
            _level(abs(yoy_sez) if yoy_sez is not None else None, 20, 50),
            level_params={"low_ok": 20, "high_warn": 50}))

        yoy_cdn = _yoy_change(cdn_list, total_list)
        ratios.append(_r(35, "Derived", "Outward",
            "YOY Change in Credit Note to Turnover Ratio", yoy_cdn, "%pts",
            "(Current Period CN Ratio − Prior Period CN Ratio) in percentage points",
            "Stable trend expected; drastic change raises red flags",
            "A drastic change in the credit note ratio may indicate deferred billing, backdated credit notes, or an attempt to reduce output tax liability.",
            _level(abs(yoy_cdn) if yoy_cdn is not None else None, 20, 50),
            level_params={"low_ok": 20, "high_warn": 50}))

    if len(gstr3b_list) >= 2:
        isd_list     = [e.get("itc_isd") or 0 for e in gstr3b_list]
        itc_list     = [_g3b_itc_availed(e) or 0 for e in gstr3b_list]
        rev_list     = [_g3b_itc_reversed(e) or 0 for e in gstr3b_list]
        liab_list    = [_g3b_total_liab(e) or 0 for e in gstr3b_list]
        taxable_list = [e.get("total_taxable_value") or e.get("taxable_sales") or 0 for e in gstr3b_list]

        def _yoy_abs(a_vals, b_vals):
            pairs = [(a, b) for a, b in zip(a_vals, b_vals) if b > 0]
            if len(pairs) < 2:
                return None
            r0 = _pct(pairs[0][0], pairs[0][1])
            r1 = _pct(pairs[-1][0], pairs[-1][1])
            return round(r1 - r0, 2) if r0 is not None and r1 is not None else None

        yoy_isd = _yoy_abs(isd_list, itc_list)
        ratios.append(_r(12, "DGARM #17b", "Inward",
            "YOY Change in ISD Credit Ratio", yoy_isd, "%pts",
            "(Current Period ISD/ITC Ratio − Prior Period Ratio) in percentage points",
            "Stable trend expected; large increase warrants ISD distribution review",
            "A significant increase in the ISD credit ratio may indicate inflated or incorrectly distributed ISD credits.",
            _level(abs(yoy_isd) if yoy_isd is not None else None, 20, 50),
            level_params={"low_ok": 20, "high_warn": 50}))

        yoy_rev = _yoy_abs(rev_list, itc_list)
        ratios.append(_r(14, "DGARM #18b", "Inward",
            "YOY Change in ITC Reversal Ratio", yoy_rev, "%pts",
            "(Current Period Reversal/ITC Ratio − Prior Period Ratio) in percentage points",
            "Consistent trend expected; large change may indicate systemic ITC compliance issues",
            "A significant change in the ITC reversal ratio may indicate changes in exempt/taxable supply mix or compliance issues.",
            _level(abs(yoy_rev) if yoy_rev is not None else None, 20, 50),
            level_params={"low_ok": 20, "high_warn": 50}))

        liab_growth = _pct(liab_list[-1] - liab_list[0], abs(liab_list[0])) if liab_list[0] else None
        turn_growth = _pct(taxable_list[-1] - taxable_list[0], abs(taxable_list[0])) if taxable_list[0] else None
        mismatch = round(turn_growth - liab_growth, 2) if (liab_growth is not None and turn_growth is not None) else None
        ratios.append(_r(34, "Derived", "Outward",
            "Growth Mismatch: Turnover vs Tax Liability", mismatch, "%pts",
            "YOY Turnover Growth % − YOY Tax Liability Growth % [Table 3.1(a), GSTR-3B]",
            "Should be near zero; > 10 percentage points warrants scrutiny",
            "High turnover growth without corresponding tax liability growth may indicate misclassification of supplies or use of incorrect lower tax rates.",
            _level(mismatch, 10, 25) if mismatch and mismatch > 0 else "LOW",
            level_params={"low_ok": 10, "high_warn": 25}))

    return ratios


# ── Master compute function ────────────────────────────────────────────────────

_PERIOD_MONTH_ORDER = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
    'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
}

def _period_sort_key(period: str):
    parts = (period or '').lower().split()
    if len(parts) < 2:
        return (9999, 0)
    try:
        return (int(parts[1]), _PERIOD_MONTH_ORDER.get(parts[0], 0))
    except ValueError:
        return (9999, 0)


def compute_risk_ratios(store) -> dict:
    """Compute all DGARM risk ratios and multi-FY trend data from the session store."""
    # Build the period→type map ourselves, EXCLUDING annual/consolidated
    # "System generated summary" reference files BEFORE grouping. This matters
    # because an annual file is often named for the last month of the period
    # (e.g. ..._032021 → "March 2021") and would otherwise overwrite the real
    # monthly file in that slot — dropping that month from the totals. Excluding
    # by file (not by period) keeps every monthly return intact.
    by_period: dict = {}
    for file_id, file_info in store.files.items():
        ext = store.get_extracted_data(file_id)
        if ext and ext.get("is_annual_summary"):
            continue  # skip the annual reference PDF only
        period   = file_info.get("period") or "Unknown Period"
        gst_type = file_info.get("gst_type") or "UNKNOWN"
        by_period.setdefault(period, {})[gst_type] = {**file_info, "id": file_id}

    gstr1_ratios_all   = []
    gstr3b_ratios_all  = []
    cross_ratios_all   = []
    gstr1_monthly_ext  = []
    gstr3b_monthly_ext = []
    gstr1_periods_used = []
    gstr3b_periods_used = []

    # FY buckets for trend analysis
    fy_g1_buckets  = {}   # {fy_label: [ext, ...]}
    fy_g3b_buckets = {}

    for period, type_map in sorted(by_period.items(), key=lambda x: _period_sort_key(x[0])):
        if period in ("Unknown Period", "Period not found"):
            continue

        fy = _period_to_fy(period)
        gstr1_info  = type_map.get("GSTR-1")
        gstr3b_info = type_map.get("GSTR-3B")

        if gstr1_info:
            ext = store.get_extracted_data(gstr1_info["id"])
            # Skip the annual/consolidated "System generated summary" reference file —
            # its figures equal the sum of the 12 monthly returns, so including it
            # would double-count every FY total and ratio.
            if ext and not ext.get("is_annual_summary"):
                gstr1_periods_used.append(period)
                for r in _gstr1_ratios(ext):
                    r["_period"] = period          # tag for period breakdown
                    gstr1_ratios_all.append(r)
                gstr1_monthly_ext.append(ext)
                fy_g1_buckets.setdefault(fy, []).append(ext)

        if gstr3b_info:
            ext = store.get_extracted_data(gstr3b_info["id"])
            if ext and not ext.get("is_annual_summary"):
                gstr3b_periods_used.append(period)
                for r in _gstr3b_ratios(ext):
                    r["_period"] = period
                    gstr3b_ratios_all.append(r)
                gstr3b_monthly_ext.append(ext)
                fy_g3b_buckets.setdefault(fy, []).append(ext)

        if gstr1_info and gstr3b_info:
            ext1 = store.get_extracted_data(gstr1_info["id"])
            ext3 = store.get_extracted_data(gstr3b_info["id"])
            if ext1 and ext3 and not ext1.get("is_annual_summary") and not ext3.get("is_annual_summary"):
                for r in _cross_form_ratios(ext1, ext3):
                    r["_period"] = period
                    cross_ratios_all.append(r)

    # Multi-period (within-batch) ratios
    monthly_ratios = _multiperiod_ratios(gstr1_monthly_ext, gstr3b_monthly_ext)

    # FY-level aggregation → trend ratios
    fy_g1_agg  = {}
    for fy, exts in fy_g1_buckets.items():
        agg = _sum_fields(exts)
        if any(e.get("legacy_combined_b2b") for e in exts):
            agg["legacy_combined_b2b"] = True   # merged B2B/SEZ/DE → skip B2B ratio
        fy_g1_agg[fy] = agg
    fy_g3b_agg = {fy: _sum_fields(exts) for fy, exts in fy_g3b_buckets.items()}
    sorted_fys = sorted(
        set(fy_g1_agg) | set(fy_g3b_agg),
        key=_fy_sort_key
    )
    trend_data = _fy_trend_ratios(fy_g1_agg, fy_g3b_agg, sorted_fys)

    _RISK_ORDER = {"UNKNOWN": -1, "LOW": 0, "MEDIUM": 1, "HIGH": 2}

    def _avg_ratios(ratio_list):
        if not ratio_list:
            return []
        by_name = {}
        for r in ratio_list:
            n = r["name"]
            if n not in by_name:
                by_name[n] = []
            by_name[n].append(r)
        result = []
        for name, rs in by_name.items():
            vals = [r["value"] for r in rs if r["value"] is not None]
            avg  = round(sum(vals) / len(vals), 2) if vals else None
            base = rs[0].copy()
            base["value"]     = avg
            base["available"] = avg is not None
            base["anomaly"]   = any(r.get("anomaly") for r in rs)
            # Recompute risk_level from the averaged value using stored thresholds.
            # This prevents one bad month from permanently flagging the average as HIGH.
            lp = base.get("level_params")
            if callable(lp):
                base["risk_level"] = lp(avg)
            elif lp is not None and avg is not None:
                base["risk_level"] = _level(
                    avg, lp["low_ok"], lp["high_warn"], lp.get("invert", False)
                )
            else:
                base["risk_level"] = rs[0].get("risk_level", "UNKNOWN")

            # Average component values so the drill-down reflects the averaged data
            if rs[0].get("components"):
                averaged_comps = []
                for comp in rs[0]["components"]:
                    lbl = comp["label"]
                    cvals = [
                        c["value"] for r in rs
                        for c in (r.get("components") or [])
                        if c["label"] == lbl and c["value"] is not None
                    ]
                    averaged_comps.append({
                        **comp,
                        "value": round(sum(cvals) / len(cvals), 2) if cvals else None,
                    })
                base["components"] = averaged_comps

            # Per-period breakdown — lets the UI show which specific month/year
            # is driving the risk without losing the averaged view
            lp = base.get("level_params")
            def _rl_for(v):
                if lp is None:        return rs[0].get("risk_level", "UNKNOWN")
                if callable(lp):      return lp(v)
                if v is None:         return "UNKNOWN"
                return _level(v, lp["low_ok"], lp["high_warn"], lp.get("invert", False))

            base["period_values"] = [
                {
                    "period":     r.get("_period", "?"),
                    "value":      r["value"],
                    "risk_level": _rl_for(r["value"]),
                    "anomaly":    r.get("anomaly", False),
                }
                for r in rs
            ]
            base.pop("_period", None)

            result.append(base)
        return result

    def _strip(ratio_list):
        """Remove internal-only fields before JSON serialisation."""
        for r in ratio_list:
            r.pop("level_params", None)
        return ratio_list

    return {
        "gstr1":            _strip(_avg_ratios(gstr1_ratios_all)),
        "gstr3b":           _strip(_avg_ratios(gstr3b_ratios_all)),
        "cross":            _strip(_avg_ratios(cross_ratios_all)),
        "multiperiod":      _strip(monthly_ratios),
        "gstr2b":           _strip(_gstr2b_stubs()),
        "framework_manual": _strip(_framework_manual_stubs()),
        "trend":            trend_data,
        "periods_gstr1":    gstr1_periods_used,
        "periods_gstr3b":   gstr3b_periods_used,
        "has_cross":        len(cross_ratios_all) > 0,
        "has_multiperiod":  len(monthly_ratios) > 0,
        "has_trend":        len(sorted_fys) >= 1,
        "total_ratios":     57,
        "source":           "DGARM Risk Ratio Framework v2",
    }
