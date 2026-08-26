"""Linked, auditable Risk-Ratio workbook.

Unlike the old risk export (which wrote hard-coded ratio values), this builds a
workbook where every ratio is a *live Excel formula* that points back to the
exact source cells:

    Sheet "GSTR-1 Data"   — monthly figures + per-FY totals (=SUM of the months)
    Sheet "GSTR-3B Data"  — monthly figures + per-FY totals (=SUM of the months)
    Sheet "Risk Ratios"   — every ratio, one formula column per financial year,
                            each cell = =GSTR-3B Data!H14 / GSTR-1 Data!F8 * 100
    Sheet "Trend"         — the FY x ratio matrix (the on-screen trend table),
                            cells reference the Risk Ratios sheet (single source)

Because the ratio cells are formulas, clicking one (or Trace Precedents) walks
straight to the source GST table cell, and the FY total it lands on is itself a
=SUM() of the 12 monthly cells — full drill-down, nothing hard-coded.

Ratio values are computed as RATIO-OF-FY-SUMS (Σnumerator ÷ Σdenominator), which
is exactly what the on-screen Trend table shows and the only basis expressible
as cell formulas. The DGARM formula text is carried verbatim from the framework
spec so the "how is this derived" question is answerable directly in the sheet.
"""
from datetime import datetime

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from services.risk_engine import (
    _period_to_fy, _fy_sort_key, _period_sort_key, _SUM_FIELDS,
    _framework_manual_stubs, _gstr2b_stubs,
)

S_G1, S_G3B, S_RR, S_TR = "GSTR-1 Data", "GSTR-3B Data", "Risk Ratios", "Trend"
S_MR = "Monthly Ratios"

_MON_ABBR = {
    "january": "Jan", "february": "Feb", "march": "Mar", "april": "Apr",
    "may": "May", "june": "Jun", "july": "Jul", "august": "Aug",
    "september": "Sep", "october": "Oct", "november": "Nov", "december": "Dec",
}


def _mon_label(period):
    p = (period or "").split()
    if len(p) < 2:
        return period or "?"
    return f"{_MON_ABBR.get(p[0].lower(), p[0][:3])}-{p[1][-2:]}"

# ── Source-field catalogs (only fields the parser actually aggregates) ─────────
# Each entry: (field_key, GST-table label). Order = display order on data sheet.
_G1_FIELDS = [
    ("total_taxable_value", "Table 12 — Total Taxable Turnover (HSN)"),
    ("tt_taxable",          "Total Tax — Σ tables − CDN (ratio turnover)"),
    ("b2b_taxable_value",   "Table 4A — B2B Taxable"),
    ("b2cl_taxable_value",  "Table 5A/5B — B2CL Taxable"),
    ("exp_expwp_taxable",   "Table 6A — Exports WP Taxable"),
    ("exp_expwop_taxable",  "Table 6A — Exports WOP Taxable"),
    ("sez_sezwp_taxable",   "Table 6B — SEZ WP Taxable"),
    ("sez_sezwop_taxable",  "Table 6B — SEZ WOP Taxable"),
    ("de_taxable",          "Table 6C — Deemed Exports Taxable"),
    ("nil_non_gst",         "Table 8 — Non-GST Supplies"),
    ("cdnr_taxable",        "Table 9B — CDNR (Credit Notes, Registered)"),
    ("cdnur_taxable",       "Table 9B — CDNUR (Credit Notes, Unregistered)"),
    ("debit_notes_taxable", "Table 9B — Debit Notes Taxable"),
]

_G3B_FIELDS = [
    ("taxable_sales",      "Table 3.1(a) — Taxable Outward Supplies"),
    ("zero_rated_sales",   "Table 3.1(b) — Zero-rated Outward Supplies"),
    ("igst_on_sales",      "Table 3.1(a) — Output Tax IGST"),
    ("cgst_on_sales",      "Table 3.1(a) — Output Tax CGST"),
    ("sgst_on_sales",      "Table 3.1(a) — Output Tax SGST"),
    ("itc_avail_igst",     "Table 4(A) — ITC Availed IGST"),
    ("itc_avail_cgst",     "Table 4(A) — ITC Availed CGST"),
    ("itc_avail_sgst",     "Table 4(A) — ITC Availed SGST"),
    ("itc_reversed_igst",  "Table 4(B) — ITC Reversed IGST"),
    ("itc_reversed_cgst",  "Table 4(B) — ITC Reversed CGST"),
    ("itc_reversed_sgst",  "Table 4(B) — ITC Reversed SGST"),
    ("itc_d1_igst",        "Table 4(D)(1) — ITC Reclaimed IGST"),
    ("itc_d1_cgst",        "Table 4(D)(1) — ITC Reclaimed CGST"),
    ("itc_d1_sgst",        "Table 4(D)(1) — ITC Reclaimed SGST"),
    ("itc_a4_igst",        "Table 4(A)(4) — ISD Credit IGST"),
    ("itc_a4_cgst",        "Table 4(A)(4) — ISD Credit CGST"),
    ("itc_a4_sgst",        "Table 4(A)(4) — ISD Credit SGST"),
    ("itc_temp_reversed",  "Table 4(B)(2) — Temporary ITC Reversal"),
    ("itc_used_igst",      "Table 6.1 — Tax Paid via ITC IGST"),
    ("itc_used_cgst",      "Table 6.1 — Tax Paid via ITC CGST"),
    ("itc_used_sgst",      "Table 6.1 — Tax Paid via ITC SGST"),
    ("cash_paid_igst",     "Table 6.1 — Tax Paid via Cash IGST"),
    ("cash_paid_cgst",     "Table 6.1 — Tax Paid via Cash CGST"),
    ("cash_paid_sgst",     "Table 6.1 — Tax Paid via Cash SGST"),
    ("tax_payable_igst",   "Table 6.1(2) — Tax Payable IGST"),
    ("tax_payable_cgst",   "Table 6.1(2) — Tax Payable CGST"),
    ("tax_payable_sgst",   "Table 6.1(2) — Tax Payable SGST"),
]

# Canonical fallbacks (mirror risk_engine accessors)
_FALLBACK = {
    "cdnr_taxable":    "cdn_value",
    "zero_rated_sales": "s31b_taxable",
}


def _val(ext, key):
    """Monthly source value with the same fallback the ratio accessors use."""
    v = ext.get(key)
    if v is None and key in _FALLBACK:
        v = ext.get(_FALLBACK[key])
    return v


# ── Ratio specs ───────────────────────────────────────────────────────────────
# term = (coef, form, [field_keys]) → coef * (sum of those FY-total cells)
# A "%" ratio = ABS(num expr) / ABS(den expr) * 100.
G1, G3B = "G1", "G3B"

# (sl, category, name, dgarm_formula_text, num_terms, den_terms, abs_flag)
_PCT_RATIOS = [
    (1, "Deemed Exports", "Deemed Export to Total Turnover Ratio",
     "Deemed Exports [Table 6(c), GSTR-1] ÷ Total GST Turnover × 100",
     [(1, G1, ["de_taxable"])], [(1, G1, ["tt_taxable"])], False),
    (5, "Exports", "Zero-Rated (SEZ) Turnover Ratio",
     "SEZ Supplies [Table 6B, GSTR-1] ÷ Total Turnover × 100",
     [(1, G1, ["sez_sezwp_taxable", "sez_sezwop_taxable"])],
     [(1, G1, ["tt_taxable"])], False),
    (30, "Outward", "B2B Credit Note to B2B Sales Ratio",
     "CDNR [Table 9B, GSTR-1] ÷ B2B Sales [Table 4A, GSTR-1] × 100",
     [(1, G1, ["cdnr_taxable"])], [(1, G1, ["b2b_taxable_value"])], True),
    ("30A", "Outward", "Unregistered Credit Note to B2CL Sales Ratio",
     "CDNUR [Table 9B, GSTR-1] ÷ B2CL Sales [Table 5, GSTR-1] × 100",
     [(1, G1, ["cdnur_taxable"])], [(1, G1, ["b2cl_taxable_value"])], True),
    (31, "Outward", "Export Credit Note to Export Turnover Ratio",
     "Export CDNUR [Table 9B, GSTR-1] ÷ Export Turnover [Table 6A/6B, GSTR-1] × 100",
     [(1, G1, ["cdnur_taxable"])],
     [(1, G1, ["exp_expwp_taxable", "exp_expwop_taxable", "sez_sezwp_taxable", "sez_sezwop_taxable"])], True),
    (32, "Outward", "Debit Note to Taxable Turnover Ratio",
     "Debit Notes [Table 9B, GSTR-1] ÷ Total GST Taxable Turnover × 100",
     [(1, G1, ["debit_notes_taxable"])], [(1, G1, ["tt_taxable"])], True),
    (39, "Outward", "Non-GST Supply Ratio",
     "Non-GST Supplies [Table 8, GSTR-1] ÷ Total Turnover [GSTR-1] × 100",
     [(1, G1, ["nil_non_gst"])], [(1, G1, ["tt_taxable"])], False),
    (41, "Outward", "Export Turnover Ratio",
     "Export Turnover [Table 6A/6B, GSTR-1] ÷ Total GST Turnover × 100",
     [(1, G1, ["exp_expwp_taxable", "exp_expwop_taxable", "sez_sezwp_taxable", "sez_sezwop_taxable"])],
     [(1, G1, ["tt_taxable"])], False),
    (11, "Inward", "ISD Credit to Total ITC Ratio",
     "ISD Credit [Table 4(A)(4), GSTR-3B] ÷ Total ITC Availed [Table 4(A)] × 100",
     [(1, G3B, ["itc_a4_igst", "itc_a4_cgst", "itc_a4_sgst"])],
     [(1, G3B, ["itc_avail_igst", "itc_avail_cgst", "itc_avail_sgst"])], False),
    (13, "Inward", "ITC Reversal to ITC Availed Ratio",
     "ITC Reversed [Table 4(B), GSTR-3B] ÷ ITC Availed [Table 4(A), GSTR-3B] × 100",
     [(1, G3B, ["itc_reversed_igst", "itc_reversed_cgst", "itc_reversed_sgst"])],
     [(1, G3B, ["itc_avail_igst", "itc_avail_cgst", "itc_avail_sgst"])], False),
    (18, "Inward", "Temporary ITC Reversal Ratio",
     "ITC Temporarily Reversed [Table 4(B)(2), GSTR-3B] ÷ ITC Availed [Table 4(A), GSTR-3B] × 100",
     [(1, G3B, ["itc_temp_reversed"])],
     [(1, G3B, ["itc_avail_igst", "itc_avail_cgst", "itc_avail_sgst"])], False),
    (20, "Inward", "ITC to Taxable Turnover Ratio",
     "Net ITC [Table 4(A)−4(D)(1), GSTR-3B] ÷ Total Turnover [Table 3.1(a+b), GSTR-3B] × 100",
     [(1, G3B, ["itc_avail_igst", "itc_avail_cgst", "itc_avail_sgst"]),
      (-1, G3B, ["itc_d1_igst", "itc_d1_cgst", "itc_d1_sgst"])],
     [(1, G3B, ["taxable_sales", "zero_rated_sales"])], False),
    (29, "Output-Input", "Output Tax to Net ITC Ratio",
     "Total Tax Liability [Table 3.1(a), GSTR-3B] ÷ Net ITC [Table 4(A)−4(B), GSTR-3B] × 100",
     [(1, G3B, ["igst_on_sales", "cgst_on_sales", "sgst_on_sales"])],
     [(1, G3B, ["itc_avail_igst", "itc_avail_cgst", "itc_avail_sgst"]),
      (-1, G3B, ["itc_reversed_igst", "itc_reversed_cgst", "itc_reversed_sgst"])], False),
    (42, "Payment", "ITC Utilization Ratio (Tax Paid via ITC)",
     "Tax Paid via ITC [Table 6.1, GSTR-3B] ÷ Total Tax Liability [Table 6.1(2)] × 100",
     [(1, G3B, ["itc_used_igst", "itc_used_cgst", "itc_used_sgst"])],
     [(1, G3B, ["tax_payable_igst", "tax_payable_cgst", "tax_payable_sgst"])], False),
    (43, "Payment", "Cash Payment to Total Liability Ratio",
     "Tax Paid via Cash [Table 6.1, GSTR-3B] ÷ Total Tax Liability [Table 6.1(2)] × 100",
     [(1, G3B, ["cash_paid_igst", "cash_paid_cgst", "cash_paid_sgst"])],
     [(1, G3B, ["tax_payable_igst", "tax_payable_cgst", "tax_payable_sgst"])], False),
    (45, "Payment", "Minimum 1% Cash Payment Compliance",
     "Total Cash Paid ÷ Total Tax Payable [Table 6.1, GSTR-3B] × 100",
     [(1, G3B, ["cash_paid_igst", "cash_paid_cgst", "cash_paid_sgst"])],
     [(1, G3B, ["tax_payable_igst", "tax_payable_cgst", "tax_payable_sgst"])], False),
]

# Ratios computed across FYs (single value); built in code referencing FY cells.
# Manual / external-data ratios are appended from risk_engine's catalog.


def _fy_groups(store):
    """Return {fy: [(period, ext), ...]} for GSTR-1 and GSTR-3B, plus sorted FYs.

    Mirrors compute_risk_ratios: excludes annual 'System generated summary'
    files and groups the monthly returns by financial year, month-ordered.
    """
    by_period = {}
    for file_id, file_info in store.files.items():
        ext = store.get_extracted_data(file_id)
        if not ext or ext.get("is_annual_summary"):
            continue
        period = file_info.get("period") or "Unknown Period"
        gtype = file_info.get("gst_type") or "UNKNOWN"
        by_period.setdefault(period, {})[gtype] = ext

    g1, g3b = {}, {}
    for period in sorted(by_period, key=_period_sort_key):
        if period in ("Unknown Period", "Period not found"):
            continue
        fy = _period_to_fy(period)
        tm = by_period[period]
        if "GSTR-1" in tm:
            g1.setdefault(fy, []).append((period, tm["GSTR-1"]))
        if "GSTR-3B" in tm:
            g3b.setdefault(fy, []).append((period, tm["GSTR-3B"]))
    fys = sorted(set(g1) | set(g3b), key=_fy_sort_key)
    return g1, g3b, fys


# ── Styling ───────────────────────────────────────────────────────────────────
def _fill(c):
    return PatternFill("solid", fgColor=c)


def _font(bold=False, italic=False, color="000000", size=9):
    return Font(bold=bold, italic=italic, color=color, size=size, name="Calibri")


_THIN = Side(style="thin", color="D0D7E2")
_BORDER = Border(top=_THIN, bottom=_THIN, left=_THIN, right=_THIN)

C_TITLE = "0A1929"
C_GRP = "1C3557"
C_SUB = "243F63"
C_TOT = "11243A"
C_FIELD = "F2F6FC"


def _write_data_sheet(ws, fields, groups, fys, title):
    """Write a data sheet; return (field_row, fy_total_col, present_keys)."""
    ws.sheet_view.showGridLines = False
    LABEL_W = 42
    ws.column_dimensions["A"].width = LABEL_W

    # Layout columns: per FY → [month cols...] + [FY Total col]
    fy_total_col, fy_month_cols = {}, {}
    col = 2
    for fy in fys:
        months = groups.get(fy, [])
        start = col
        for (period, _ext) in months:
            ws.column_dimensions[get_column_letter(col)].width = 13
            col += 1
        # FY total column (always present, even if no months)
        if not months:
            ws.column_dimensions[get_column_letter(col)].width = 15
        tot = col
        ws.column_dimensions[get_column_letter(tot)].width = 16
        fy_month_cols[fy] = list(range(start, start + len(months)))
        fy_total_col[fy] = tot
        col += 1
    last_col = col - 1

    # Title
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(last_col, 2))
    t = ws.cell(1, 1, title)
    t.fill = _fill(C_TITLE); t.font = _font(bold=True, color="5BA3D9", size=11)
    t.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[1].height = 26

    # Row 2: FY group headers; Row 3: month / FY-Total sub-headers
    a2 = ws.cell(2, 1, "GST Table — Field"); a2.fill = _fill(C_GRP)
    a2.font = _font(bold=True, color="FFFFFF"); a2.alignment = Alignment(vertical="center", indent=1)
    a3 = ws.cell(3, 1, ""); a3.fill = _fill(C_SUB)
    for fy in fys:
        mcols = fy_month_cols[fy]; tot = fy_total_col[fy]
        first = mcols[0] if mcols else tot
        ws.merge_cells(start_row=2, start_column=first, end_row=2, end_column=tot)
        g = ws.cell(2, first, fy); g.fill = _fill(C_GRP)
        g.font = _font(bold=True, color="FFFFFF"); g.alignment = Alignment(horizontal="center", vertical="center")
        for ci, (period, _ext) in zip(mcols, groups.get(fy, [])):
            c = ws.cell(3, ci, _mon_label(period)); c.fill = _fill(C_SUB)
            c.font = _font(bold=True, color="B8D0F0", size=8); c.alignment = Alignment(horizontal="center")
        c = ws.cell(3, tot, "FY Total"); c.fill = _fill(C_SUB)
        c.font = _font(bold=True, color="FFE08A", size=8); c.alignment = Alignment(horizontal="center")
    ws.row_dimensions[2].height = 16; ws.row_dimensions[3].height = 15

    # period → month column index (union across FYs), for the Monthly Ratios sheet.
    period_col = {}
    for fy in fys:
        for ci, (period, _ext) in zip(fy_month_cols[fy], groups.get(fy, [])):
            period_col[period] = ci

    # Field rows
    field_row, present = {}, set()
    r = 4
    for key, label in fields:
        field_row[key] = r
        lc = ws.cell(r, 1, label); lc.fill = _fill(C_FIELD)
        lc.font = _font(size=8, color="33475B"); lc.alignment = Alignment(indent=1, vertical="center")
        lc.border = _BORDER
        for fy in fys:
            mcols = fy_month_cols[fy]
            for ci, (period, ext) in zip(mcols, groups.get(fy, [])):
                v = _val(ext, key)
                if v is not None:
                    present.add(key)
                cell = ws.cell(r, ci, round(float(v), 2) if v is not None else None)
                cell.number_format = '#,##0.00'; cell.font = _font(size=8); cell.border = _BORDER
            tot = fy_total_col[fy]
            if mcols:
                rng = f"{get_column_letter(mcols[0])}{r}:{get_column_letter(mcols[-1])}{r}"
                tcell = ws.cell(r, tot, f"=SUM({rng})")
            else:
                tcell = ws.cell(r, tot, 0)
            tcell.number_format = '#,##0.00'; tcell.font = _font(bold=True, size=8, color="11243A")
            tcell.fill = _fill("FFF8E1"); tcell.border = _BORDER
        ws.row_dimensions[r].height = 14
        r += 1

    ws.freeze_panes = "B4"
    return field_row, fy_total_col, present, period_col


def _expr(terms, fy, fmaps):
    """Build an Excel sub-expression summing cells across terms.

    `fy` is a key into each form's column map (fcol) — a financial year for the
    per-FY sheet, or a period label for the Monthly Ratios sheet. Terms whose
    form has no column for that key are skipped (e.g. a GSTR-3B-only month).
    """
    out = ""
    for coef, form, keys in terms:
        sheet, frow, fcol = fmaps[form]
        if fy not in fcol:
            continue
        col = get_column_letter(fcol[fy])
        cells = [f"'{sheet}'!{col}{frow[k]}" for k in keys if k in frow]
        if not cells:
            continue
        seg = "(" + "+".join(cells) + ")"
        out += (seg if out == "" else "+" + seg) if coef > 0 else ("-" + seg)
    return out or "0"


def _pct_formula(num_terms, den_terms, abs_flag, fy, fmaps):
    num = _expr(num_terms, fy, fmaps)
    den = _expr(den_terms, fy, fmaps)
    if abs_flag:
        num, den = f"ABS({num})", f"ABS({den})"
    return f'=IFERROR(({num})/({den})*100,"N/A")'


def build_linked_workbook(store, out_path):
    g1_groups, g3b_groups, fys = _fy_groups(store)

    wb = openpyxl.Workbook()
    ws_g1 = wb.active; ws_g1.title = S_G1
    fr_g1, tc_g1, pres_g1, pc_g1 = _write_data_sheet(
        ws_g1, _G1_FIELDS, g1_groups, fys, "GSTR-1 — Monthly Source Data & FY Totals")
    ws_g3b = wb.create_sheet(S_G3B)
    fr_g3b, tc_g3b, pres_g3b, pc_g3b = _write_data_sheet(
        ws_g3b, _G3B_FIELDS, g3b_groups, fys, "GSTR-3B — Monthly Source Data & FY Totals")

    fmaps = {G1: (S_G1, fr_g1, tc_g1), G3B: (S_G3B, fr_g3b, tc_g3b)}
    # Month-keyed maps (period → data-sheet column) for the Monthly Ratios sheet.
    fmaps_month = {G1: (S_G1, fr_g1, pc_g1), G3B: (S_G3B, fr_g3b, pc_g3b)}

    # ── Risk Ratios sheet ─────────────────────────────────────────────────────
    ws = wb.create_sheet(S_RR, 0)
    ws.sheet_view.showGridLines = False
    headers = ["Sl", "Category", "Ratio (DGARM Framework)", "Formula"] + fys + ["Risk"]
    widths = [6, 16, 40, 52] + [13] * len(fys) + [10]
    fy_col0 = 5  # first FY column index (1-based): E
    for ci, (h, w) in enumerate(zip(headers, widths), 1):
        ws.column_dimensions[get_column_letter(ci)].width = w
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    t = ws.cell(1, 1, f"GST Risk Intelligence — Linked Ratios  |  Generated: "
                      f"{datetime.now().strftime('%d %b %Y %H:%M')}  |  Values = ratio of FY-sum source cells")
    t.fill = _fill(C_TITLE); t.font = _font(bold=True, color="5BA3D9", size=11)
    t.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[1].height = 26
    for ci, h in enumerate(headers, 1):
        c = ws.cell(2, ci, h); c.fill = _fill(C_GRP)
        c.font = _font(bold=True, color="FFFFFF", size=9)
        c.alignment = Alignment(horizontal="center" if ci >= fy_col0 else "left", vertical="center", indent=1)
    ws.row_dimensions[2].height = 18

    rr_cell = {}   # {sl: {fy: "E4"}}
    r = 3

    def _section(label):
        nonlocal r
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=len(headers))
        c = ws.cell(r, 1, f"  {label}"); c.fill = _fill(C_SUB)
        c.font = _font(bold=True, color="60A5FA"); c.alignment = Alignment(indent=1, vertical="center")
        r += 1

    _section("Computed Ratios (live formulas → GSTR-1 / GSTR-3B source cells)")
    for sl, cat, name, ftext, num_t, den_t, absf in _PCT_RATIOS:
        ws.cell(r, 1, sl).font = _font(size=8)
        ws.cell(r, 2, cat).font = _font(size=8)
        ws.cell(r, 3, name).font = _font(size=8, color="33475B")
        ws.cell(r, 4, ftext).font = _font(size=7, italic=True, color="6B7280")
        rr_cell[sl] = {}
        for i, fy in enumerate(fys):
            ci = fy_col0 + i
            cell = ws.cell(r, ci, _pct_formula(num_t, den_t, absf, fy, fmaps))
            cell.number_format = '0.00"%"'; cell.font = _font(size=8, bold=True, color="11243A")
            cell.alignment = Alignment(horizontal="center")
            rr_cell[sl][fy] = f"{get_column_letter(ci)}{r}"
        for ci in range(1, len(headers) + 1):
            ws.cell(r, ci).border = _BORDER
        r += 1

    # ── Multi-year trend indicators (single value, latest vs first FY) ─────────
    if len(fys) >= 2:
        f0, fL = fys[0], fys[-1]
        last_ci = fy_col0 + len(fys) - 1

        def _delta_row(sl, cat, name, ftext, formula):
            nonlocal r
            ws.cell(r, 1, sl).font = _font(size=8)
            ws.cell(r, 2, cat).font = _font(size=8)
            ws.cell(r, 3, name).font = _font(size=8, color="33475B")
            ws.cell(r, 4, ftext).font = _font(size=7, italic=True, color="6B7280")
            cell = ws.cell(r, last_ci, formula)
            cell.number_format = '0.00'; cell.font = _font(size=8, bold=True, color="7B5800")
            cell.alignment = Alignment(horizontal="center"); cell.fill = _fill("FFF8E1")
            for ci in range(1, len(headers) + 1):
                ws.cell(r, ci).border = _BORDER
            r += 1

        def _g1tot(key, fy):
            return f"'{S_G1}'!{get_column_letter(tc_g1[fy])}{fr_g1[key]}"

        def _g3tot(keys, fy):
            return "(" + "+".join(f"'{S_G3B}'!{get_column_letter(tc_g3b[fy])}{fr_g3b[k]}" for k in keys) + ")"

        _section("Multi-Year Trend Indicators (Δ latest FY vs first FY)")
        _delta_row(2, "Deemed Exports", "YOY Change in Deemed Export Ratio",
                   "Deemed Export Ratio (latest FY − first FY), percentage points",
                   f'=IFERROR({rr_cell[1][fL]}-{rr_cell[1][f0]},"N/A")')
        _delta_row(6, "Exports", "YOY Change in Zero-Rated (SEZ) Ratio",
                   "SEZ Turnover Ratio (latest FY − first FY), percentage points",
                   f'=IFERROR({rr_cell[5][fL]}-{rr_cell[5][f0]},"N/A")')
        _delta_row(12, "Inward", "YOY Change in ISD Credit Ratio",
                   "ISD Credit Ratio (latest FY − first FY), percentage points",
                   f'=IFERROR({rr_cell[11][fL]}-{rr_cell[11][f0]},"N/A")')
        _delta_row(14, "Inward", "YOY Change in ITC Reversal Ratio",
                   "ITC Reversal Ratio (latest FY − first FY), percentage points",
                   f'=IFERROR({rr_cell[13][fL]}-{rr_cell[13][f0]},"N/A")')
        # CDN (CDNR+CDNUR) to total turnover, Δ across FYs
        cdn_L = (f"(ABS('{S_G1}'!{get_column_letter(tc_g1[fL])}{fr_g1['cdnr_taxable']})"
                 f"+ABS('{S_G1}'!{get_column_letter(tc_g1[fL])}{fr_g1['cdnur_taxable']}))"
                 f"/{_g1tot('tt_taxable', fL)}*100")
        cdn_0 = (f"(ABS('{S_G1}'!{get_column_letter(tc_g1[f0])}{fr_g1['cdnr_taxable']})"
                 f"+ABS('{S_G1}'!{get_column_letter(tc_g1[f0])}{fr_g1['cdnur_taxable']}))"
                 f"/{_g1tot('tt_taxable', f0)}*100")
        _delta_row(35, "Outward", "YOY Change in Credit Note to Turnover Ratio",
                   "(CDNR+CDNUR) ÷ Total Turnover (latest FY − first FY), percentage points",
                   f'=IFERROR({cdn_L}-{cdn_0},"N/A")')
        # YoY taxable turnover decline (GSTR-1 total)
        _delta_row(27, "Monthly Ratio", "Taxable Turnover Decline (YOY)",
                   "(First FY Turnover − Latest FY Turnover) ÷ First FY × 100",
                   f'=IFERROR(({_g1tot("tt_taxable", f0)}-{_g1tot("tt_taxable", fL)})'
                   f'/{_g1tot("tt_taxable", f0)}*100,"N/A")')
        # Growth mismatch: turnover growth − liability growth (GSTR-3B)
        turn_g = (f"({_g3tot(['taxable_sales'], fL)}-{_g3tot(['taxable_sales'], f0)})"
                  f"/{_g3tot(['taxable_sales'], f0)}*100")
        liab_g = (f"({_g3tot(['tax_payable_igst','tax_payable_cgst','tax_payable_sgst'], fL)}"
                  f"-{_g3tot(['tax_payable_igst','tax_payable_cgst','tax_payable_sgst'], f0)})"
                  f"/{_g3tot(['tax_payable_igst','tax_payable_cgst','tax_payable_sgst'], f0)}*100")
        _delta_row(34, "Outward", "Growth Mismatch: Turnover vs Tax Liability",
                   "YOY Turnover Growth % − YOY Tax Liability Growth %",
                   f'=IFERROR(({turn_g})-({liab_g}),"N/A")')

    # ── Manual / external-data ratios (no formula — labelled status) ───────────
    _section("Manual / External-Data Ratios (not computable from GSTR-1 / GSTR-3B)")
    for stub in (_gstr2b_stubs() + _framework_manual_stubs()):
        ws.cell(r, 1, stub["sl_no"]).font = _font(size=8)
        ws.cell(r, 2, stub["category"]).font = _font(size=8)
        ws.cell(r, 3, stub["name"]).font = _font(size=8, color="33475B")
        ws.cell(r, 4, stub["formula"]).font = _font(size=7, italic=True, color="6B7280")
        sc = ws.cell(r, fy_col0, stub.get("status") or "N/A")
        sc.font = _font(size=8, italic=True, color="94731A")
        ws.merge_cells(start_row=r, start_column=fy_col0, end_row=r, end_column=fy_col0 + max(len(fys) - 1, 0))
        for ci in range(1, len(headers) + 1):
            ws.cell(r, ci).border = _BORDER
        r += 1

    ws.freeze_panes = "E3"

    # ── Trend sheet (FY × ratio matrix, references Risk Ratios cells) ──────────
    _write_trend_sheet(wb, fys, rr_cell)

    # ── Monthly Ratios sheet (per-month ratio formulas → monthly source cells) ─
    all_periods = sorted(set(pc_g1) | set(pc_g3b), key=_period_sort_key)
    _write_monthly_sheet(wb, all_periods, fmaps_month)

    wb.save(out_path)
    return out_path


def _write_monthly_sheet(wb, periods, fmaps_month):
    """Per-month ratio grid: every % ratio computed for each month directly from
    that month's source cells (numerator month cell ÷ denominator month cell)."""
    ws = wb.create_sheet(S_MR)
    ws.sheet_view.showGridLines = False
    headers = ["Sl", "Category", "Ratio (DGARM Framework)"] + [_mon_label(p) for p in periods]
    widths = [6, 16, 40] + [12] * len(periods)
    mon_col0 = 4
    for ci, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(ci)].width = w
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    t = ws.cell(1, 1, "GST Risk Intelligence — Monthly Ratios  |  each cell = that month's "
                      "numerator ÷ denominator (live formula → the month's source cells)")
    t.fill = _fill(C_TITLE); t.font = _font(bold=True, color="5BA3D9", size=11)
    t.alignment = Alignment(horizontal="left", vertical="center", indent=1); ws.row_dimensions[1].height = 26
    for ci, h in enumerate(headers, 1):
        c = ws.cell(2, ci, h); c.fill = _fill(C_GRP)
        c.font = _font(bold=True, color="FFFFFF", size=9)
        c.alignment = Alignment(horizontal="center" if ci >= mon_col0 else "left", vertical="center", indent=1)
    ws.row_dimensions[2].height = 18

    r = 3
    for sl, cat, name, ftext, num_t, den_t, absf in _PCT_RATIOS:
        ws.cell(r, 1, sl).font = _font(size=8)
        ws.cell(r, 2, cat).font = _font(size=8)
        ws.cell(r, 3, name).font = _font(size=8, color="33475B")
        for i, p in enumerate(periods):
            cell = ws.cell(r, mon_col0 + i, _pct_formula(num_t, den_t, absf, p, fmaps_month))
            cell.number_format = '0.00"%"'; cell.font = _font(size=8, color="11243A")
            cell.alignment = Alignment(horizontal="center")
        for ci in range(1, len(headers) + 1):
            ws.cell(r, ci).border = _BORDER
        r += 1
    ws.freeze_panes = "D3"


# 8 trend ratios shown on screen → (sl, label, direction)
_TREND_VIEW = [
    (20, "ITC to Taxable Turnover", "high_bad"),
    (43, "Cash Payment to Liability", "low_bad"),
    (42, "ITC Utilization", "high_bad"),
    (13, "ITC Reversal Ratio", "high_bad"),
    (30, "B2B Credit Note Ratio", "high_bad"),
    (1,  "Deemed Export Ratio", "high_bad"),
    (41, "Export Turnover Ratio", "neutral"),
    (11, "ISD Credit Ratio", "high_bad"),
]


def _write_trend_sheet(wb, fys, rr_cell):
    ws = wb.create_sheet(S_TR)
    ws.sheet_view.showGridLines = False
    headers = ["Risk Ratio"] + fys + ["Trend"]
    widths = [34] + [13] * len(fys) + [12]
    for ci, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(ci)].width = w
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    t = ws.cell(1, 1, "Risk Trend (per Financial Year) — linked to the Risk Ratios sheet")
    t.fill = _fill(C_TITLE); t.font = _font(bold=True, color="5BA3D9", size=11)
    t.alignment = Alignment(vertical="center", indent=1); ws.row_dimensions[1].height = 26
    for ci, h in enumerate(headers, 1):
        c = ws.cell(2, ci, h); c.fill = _fill(C_GRP)
        c.font = _font(bold=True, color="FFFFFF"); c.alignment = Alignment(horizontal="center", vertical="center")
    r = 3
    for sl, label, _dir in _TREND_VIEW:
        ws.cell(r, 1, label).font = _font(size=9, color="33475B")
        cells = rr_cell.get(sl, {})
        for i, fy in enumerate(fys):
            src = cells.get(fy)
            cell = ws.cell(r, 2 + i, f"='{S_RR}'!{src}" if src else "N/A")
            cell.number_format = '0.00"%"'; cell.font = _font(size=9); cell.alignment = Alignment(horizontal="center")
        # Trend arrow: compare latest vs first FY cell
        if len(fys) >= 2 and cells.get(fys[0]) and cells.get(fys[-1]):
            a = f"'{S_RR}'!{cells[fys[0]]}"; b = f"'{S_RR}'!{cells[fys[-1]]}"
            tcell = ws.cell(r, 2 + len(fys),
                            f'=IFERROR(IF({b}>{a}+1,"Rising",IF({b}<{a}-1,"Falling","Stable")),"—")')
        else:
            tcell = ws.cell(r, 2 + len(fys), "—")
        tcell.font = _font(size=9, italic=True, color="6B7280"); tcell.alignment = Alignment(horizontal="center")
        for ci in range(1, len(headers) + 1):
            ws.cell(r, ci).border = _BORDER
        r += 1
    ws.cell(r + 1, 1, "Each value links to the Risk Ratios sheet, which links to the FY-total "
                      "cells on the GSTR-1 / GSTR-3B Data sheets (themselves =SUM of the monthly cells).").font = \
        _font(size=8, italic=True, color="94A3B8")
    ws.freeze_panes = "B3"
