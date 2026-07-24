"""Export route — Flask blueprint."""
import os
import logging
from datetime import datetime
from flask import Blueprint, request, send_file, jsonify
import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from store import store
from services.export_service import export_excel, export_pdf_report
from services.risk_engine import compute_risk_ratios

export_bp = Blueprint("export", __name__)
logger    = logging.getLogger(__name__)

# ── Financial-Year sort helper ────────────────────────────────────────────────
# FY order: Apr=0, May=1 … Dec=8, Jan=9, Feb=10, Mar=11
# Handles both full names ("January") and abbreviated ("Jan")
_FY_MONTH_POS = {
    'april':9-9,'may':1,'june':2,'july':3,'august':4,'september':5,
    'october':6,'november':7,'december':8,'january':9,'february':10,'march':11,
    'apr':0,'may':1,'jun':2,'jul':3,'aug':4,'sep':5,
    'oct':6,'nov':7,'dec':8,'jan':9,'feb':10,'mar':11,
}

def _fy_sort_key(row: dict) -> tuple:
    """Return (fy_start_year, fy_month_pos) for a row dict with a 'period' key."""
    period = (row.get("period") or "").strip()
    parts  = period.split()
    if len(parts) < 2:
        return (9999, 99)
    mon = parts[0].lower()
    try:
        yr = int(parts[1])
    except ValueError:
        return (9999, 99)
    pos      = _FY_MONTH_POS.get(mon, 99)
    fy_start = yr - 1 if pos >= 9 else yr   # Jan/Feb/Mar belong to prior FY
    return (fy_start, pos)


def _get_ctx(file_id):
    extracted = store.get_extracted_data(file_id)
    analytics = store.get_analytics(file_id)
    if extracted is None or analytics is None:
        return None, None
    return extracted, analytics


@export_bp.get("/export/excel/<file_id>")
def dl_excel(file_id):
    extracted, analytics = _get_ctx(file_id)
    if extracted is None:
        return jsonify(error="File not found"), 404
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = os.path.join("output", f"GST_Report_{file_id[:8]}_{ts}.xlsx")
    try:
        export_excel(extracted, analytics, out)
    except Exception as exc:
        logger.exception(exc)
        return jsonify(error=str(exc)), 500
    return send_file(out, as_attachment=True,
                     download_name=os.path.basename(out),
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@export_bp.get("/export/pdf/<file_id>")
def dl_pdf(file_id):
    extracted, analytics = _get_ctx(file_id)
    if extracted is None:
        return jsonify(error="File not found"), 404
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = os.path.join("output", f"GST_CA_Report_{file_id[:8]}_{ts}.pdf")
    try:
        export_pdf_report(extracted, analytics, out)
    except Exception as exc:
        logger.exception(exc)
        return jsonify(error=str(exc)), 500
    return send_file(out, as_attachment=True,
                     download_name=os.path.basename(out),
                     mimetype="application/pdf")


@export_bp.get("/export/active/excel")
def active_excel():
    fid = store.active_file_id
    if not fid:
        return jsonify(error="No active file"), 400
    return dl_excel(fid)


@export_bp.get("/export/active/pdf")
def active_pdf():
    fid = store.active_file_id
    if not fid:
        return jsonify(error="No active file"), 400
    return dl_pdf(fid)


def _build_ext_row(file_info, ext):
    """Extract all MOM fields from a file's extracted_data dict."""
    period = file_info.get("period") or ext.get("period") or ""
    return {
        "period":        period,
        "gst_type":      file_info.get("gst_type") or "GSTR-1",
        # 4A B2B Regular
        "b2b_taxable":   ext.get("b2b_taxable_value") or 0,
        "b2b_igst":      ext.get("b2b_igst")          or 0,
        "b2b_cgst":      ext.get("b2b_cgst")          or 0,
        "b2b_sgst":      ext.get("b2b_sgst")          or 0,
        # 4B B2B RCM
        "b2b_rcm_taxable": ext.get("b2b_rcm_taxable") or 0,
        "b2b_rcm_igst":    ext.get("b2b_rcm_igst")    or 0,
        "b2b_rcm_cgst":    ext.get("b2b_rcm_cgst")    or 0,
        "b2b_rcm_sgst":    ext.get("b2b_rcm_sgst")    or 0,
        # 5A/5B B2CL
        "b2cl_taxable":  ext.get("b2cl_taxable_value") or 0,
        "b2cl_igst":     ext.get("b2cl_igst")          or 0,
        # 7 B2CS
        "b2cs_taxable":  ext.get("b2cs_taxable_value") or 0,
        "b2cs_igst":     ext.get("b2cs_igst")          or 0,
        "b2cs_cgst":     ext.get("b2cs_cgst")          or 0,
        "b2cs_sgst":     ext.get("b2cs_sgst")          or 0,
        # 8 Nil/Exempt/Non-GST
        "nil_rated":     ext.get("nil_taxable_value")  or 0,
        "exempt":        ext.get("nil_exempt")         or 0,
        "non_gst":       ext.get("nil_non_gst")        or 0,
        # 6A Exports EXPWP / EXPWOP
        "exp_expwp_taxable":  ext.get("exp_expwp_taxable")  or 0,
        "exp_expwp_igst":     ext.get("exp_expwp_igst")     or 0,
        "exp_expwop_taxable": ext.get("exp_expwop_taxable") or 0,
        # 6B SEZ SEZWP / SEZWOP
        "sez_sezwp_taxable":  ext.get("sez_sezwp_taxable")  or 0,
        "sez_sezwp_igst":     ext.get("sez_sezwp_igst")     or 0,
        "sez_sezwop_taxable": ext.get("sez_sezwop_taxable") or 0,
        # 6C Deemed Exports
        "de_taxable": ext.get("de_taxable") or 0,
        "de_igst":    ext.get("de_igst")    or 0,
        "de_cgst":    ext.get("de_cgst")    or 0,
        "de_sgst":    ext.get("de_sgst")    or 0,
        # 9B CDN Registered
        "cdnr_taxable":  ext.get("cdnr_taxable") if ext.get("cdnr_taxable") is not None else (ext.get("cdn_value") or 0),
        "cdnr_igst":     ext.get("cdnr_igst")    if ext.get("cdnr_igst")    is not None else (ext.get("cdn_igst")  or 0),
        "cdnr_cgst":     ext.get("cdnr_cgst")    if ext.get("cdnr_cgst")    is not None else (ext.get("cdn_cgst")  or 0),
        "cdnr_sgst":     ext.get("cdnr_sgst")    if ext.get("cdnr_sgst")    is not None else (ext.get("cdn_sgst")  or 0),
        # 9B CDN Unregistered
        "cdnur_taxable": ext.get("cdnur_taxable") or 0,
        "cdnur_igst":    ext.get("cdnur_igst")    or 0,
        "cdnur_cgst":    ext.get("cdnur_cgst")    or 0,
        "cdnur_sgst":    ext.get("cdnur_sgst")    or 0,
        # 9C CDNRA (Amended CDN Registered)
        "cdnra_taxable": ext.get("cdnra_taxable") or 0,
        "cdnra_igst":    ext.get("cdnra_igst")    or 0,
        "cdnra_cgst":    ext.get("cdnra_cgst")    or 0,
        "cdnra_sgst":    ext.get("cdnra_sgst")    or 0,
        # 9C CDNURA (Amended CDN Unregistered)
        "cdnura_taxable": ext.get("cdnura_taxable") or 0,
        "cdnura_igst":    ext.get("cdnura_igst")    or 0,
        # 9A Amendments — B2B
        "amend_b2b_taxable": ext.get("amend_b2b_taxable") or 0,
        "amend_b2b_igst":    ext.get("amend_b2b_igst")    or 0,
        "amend_b2b_cgst":    ext.get("amend_b2b_cgst")    or 0,
        "amend_b2b_sgst":    ext.get("amend_b2b_sgst")    or 0,
        # 9A Amendments — B2CL
        "amend_b2cl_taxable": ext.get("amend_b2cl_taxable") or 0,
        "amend_b2cl_igst":    ext.get("amend_b2cl_igst")    or 0,
        # 9A Amendments — Exports
        "amend_exp_taxable": ext.get("amend_exp_taxable") or 0,
        "amend_exp_igst":    ext.get("amend_exp_igst")    or 0,
        # 9A Amendments — SEZ
        "amend_sez_taxable": ext.get("amend_sez_taxable") or 0,
        "amend_sez_igst":    ext.get("amend_sez_igst")    or 0,
        # 9A Amendments — DE
        "amend_de_taxable": ext.get("amend_de_taxable") or 0,
        "amend_de_igst":    ext.get("amend_de_igst")    or 0,
        # 10 B2CS Amendments
        "amend_b2cs_taxable": ext.get("amend_b2cs_taxable") or 0,
        "amend_b2cs_igst":    ext.get("amend_b2cs_igst")    or 0,
        "amend_b2cs_cgst":    ext.get("amend_b2cs_cgst")    or 0,
        "amend_b2cs_sgst":    ext.get("amend_b2cs_sgst")    or 0,
        # 11A Advances Received
        "adv_recv_taxable": ext.get("adv_recv_taxable") or 0,
        "adv_recv_igst":    ext.get("adv_recv_igst")    or 0,
        "adv_recv_cgst":    ext.get("adv_recv_cgst")    or 0,
        "adv_recv_sgst":    ext.get("adv_recv_sgst")    or 0,
        # 11B Advances Adjusted
        "adv_adj_taxable": ext.get("adv_adj_taxable") or 0,
        "adv_adj_igst":    ext.get("adv_adj_igst")    or 0,
        "adv_adj_cgst":    ext.get("adv_adj_cgst")    or 0,
        "adv_adj_sgst":    ext.get("adv_adj_sgst")    or 0,
        # 14 E-Commerce u/s 52
        "eco_taxable": ext.get("eco_taxable") or 0,
        "eco_igst":    ext.get("eco_igst")    or 0,
        "eco_cgst":    ext.get("eco_cgst")    or 0,
        "eco_sgst":    ext.get("eco_sgst")    or 0,
        # 15 Supplies u/s 9(5)
        "s95_taxable": ext.get("s95_taxable") or 0,
        "s95_igst":    ext.get("s95_igst")    or 0,
        "s95_cgst":    ext.get("s95_cgst")    or 0,
        "s95_sgst":    ext.get("s95_sgst")    or 0,
        # HSN authoritative totals (also used as Total Tax columns)
        "hsn_taxable":   ext.get("total_taxable_value") or 0,
        "hsn_igst":      ext.get("total_igst")          or 0,
        "hsn_cgst":      ext.get("total_cgst")          or 0,
        "hsn_sgst":      ext.get("total_sgst")          or 0,
    }


# Column schema: (row_key, group_label, sub_label)
# Period (col 1) and Type (col 2) are handled separately.
# Data columns start at Excel column 3.
# Col layout (1-based): B2B=3-6, 4B RCM=7-10, B2CL=11-12, B2CS=13-16,
#   NIL=17-19, 6A EXPWP=20-21, 6A EXPWOP=22, 6B SEZWP=23-24, 6B SEZWOP=25,
#   6C DE=26-29, CDNR=30-33, CDNUR=34-37, CDNRA=38-41, CDNURA=42-43,
#   9A B2B=44-47, 9A B2CL=48-49, 9A Exp=50-51, 9A SEZ=52-53, 9A DE=54-55,
#   10 B2CS Amend=56-59, 11A Adv=60-63, 11B Adj=64-67,
#   14 ECO=68-71, 15 9(5)=72-75, HSN=76-79, Total=80-83
_MOM_COLS = [
    # 4A B2B Regular
    ("b2b_taxable",        "4A - B2B Regular",    "Taxable"),
    ("b2b_igst",           "4A - B2B Regular",    "IGST"),
    ("b2b_cgst",           "4A - B2B Regular",    "CGST"),
    ("b2b_sgst",           "4A - B2B Regular",    "SGST"),
    # 4B B2B RCM
    ("b2b_rcm_taxable",    "4B - B2B RCM",        "Taxable"),
    ("b2b_rcm_igst",       "4B - B2B RCM",        "IGST"),
    ("b2b_rcm_cgst",       "4B - B2B RCM",        "CGST"),
    ("b2b_rcm_sgst",       "4B - B2B RCM",        "SGST"),
    # 5A/5B B2CL
    ("b2cl_taxable",       "5A/5B - B2CL",        "Taxable"),
    ("b2cl_igst",          "5A/5B - B2CL",        "IGST"),
    # 7 B2CS
    ("b2cs_taxable",       "7 - B2CS",            "Taxable"),
    ("b2cs_igst",          "7 - B2CS",            "IGST"),
    ("b2cs_cgst",          "7 - B2CS",            "CGST"),
    ("b2cs_sgst",          "7 - B2CS",            "SGST"),
    # 8 NIL / Exempt
    ("nil_rated",          "8 - NIL / Exempt",    "NIL Rated"),
    ("exempt",             "8 - NIL / Exempt",    "Exempt"),
    ("non_gst",            "8 - NIL / Exempt",    "Non-GST"),
    # 6A Exports
    ("exp_expwp_taxable",  "6A - Exports EXPWP",  "Taxable"),
    ("exp_expwp_igst",     "6A - Exports EXPWP",  "IGST"),
    ("exp_expwop_taxable", "6A - Exports EXPWOP", "Taxable"),
    # 6B SEZ
    ("sez_sezwp_taxable",  "6B - SEZ SEZWP",      "Taxable"),
    ("sez_sezwp_igst",     "6B - SEZ SEZWP",      "IGST"),
    ("sez_sezwop_taxable", "6B - SEZ SEZWOP",     "Taxable"),
    # 6C Deemed Exports
    ("de_taxable",         "6C - Deemed Exports", "Taxable"),
    ("de_igst",            "6C - Deemed Exports", "IGST"),
    ("de_cgst",            "6C - Deemed Exports", "CGST"),
    ("de_sgst",            "6C - Deemed Exports", "SGST"),
    # 9B CDN Registered
    ("cdnr_taxable",       "9B - CDN Reg.",       "Taxable"),
    ("cdnr_igst",          "9B - CDN Reg.",       "IGST"),
    ("cdnr_cgst",          "9B - CDN Reg.",       "CGST"),
    ("cdnr_sgst",          "9B - CDN Reg.",       "SGST"),
    # 9B CDN Unregistered
    ("cdnur_taxable",      "9B - CDN Unreg.",     "Taxable"),
    ("cdnur_igst",         "9B - CDN Unreg.",     "IGST"),
    ("cdnur_cgst",         "9B - CDN Unreg.",     "CGST"),
    ("cdnur_sgst",         "9B - CDN Unreg.",     "SGST"),
    # 9C CDNRA
    ("cdnra_taxable",      "9C - CDNRA",          "Taxable"),
    ("cdnra_igst",         "9C - CDNRA",          "IGST"),
    ("cdnra_cgst",         "9C - CDNRA",          "CGST"),
    ("cdnra_sgst",         "9C - CDNRA",          "SGST"),
    # 9C CDNURA
    ("cdnura_taxable",     "9C - CDNURA",         "Taxable"),
    ("cdnura_igst",        "9C - CDNURA",         "IGST"),
    # 9A Amendments — B2B
    ("amend_b2b_taxable",  "9A - Amend B2B",      "Taxable"),
    ("amend_b2b_igst",     "9A - Amend B2B",      "IGST"),
    ("amend_b2b_cgst",     "9A - Amend B2B",      "CGST"),
    ("amend_b2b_sgst",     "9A - Amend B2B",      "SGST"),
    # 9A Amendments — B2CL
    ("amend_b2cl_taxable", "9A - Amend B2CL",     "Taxable"),
    ("amend_b2cl_igst",    "9A - Amend B2CL",     "IGST"),
    # 9A Amendments — Exports
    ("amend_exp_taxable",  "9A - Amend Exp",      "Taxable"),
    ("amend_exp_igst",     "9A - Amend Exp",      "IGST"),
    # 9A Amendments — SEZ
    ("amend_sez_taxable",  "9A - Amend SEZ",      "Taxable"),
    ("amend_sez_igst",     "9A - Amend SEZ",      "IGST"),
    # 9A Amendments — DE
    ("amend_de_taxable",   "9A - Amend DE",       "Taxable"),
    ("amend_de_igst",      "9A - Amend DE",       "IGST"),
    # 10 B2CS Amendments
    ("amend_b2cs_taxable", "10 - B2CS Amend",     "Taxable"),
    ("amend_b2cs_igst",    "10 - B2CS Amend",     "IGST"),
    ("amend_b2cs_cgst",    "10 - B2CS Amend",     "CGST"),
    ("amend_b2cs_sgst",    "10 - B2CS Amend",     "SGST"),
    # 11A Advances Received
    ("adv_recv_taxable",   "11A - Adv Received",  "Taxable"),
    ("adv_recv_igst",      "11A - Adv Received",  "IGST"),
    ("adv_recv_cgst",      "11A - Adv Received",  "CGST"),
    ("adv_recv_sgst",      "11A - Adv Received",  "SGST"),
    # 11B Advances Adjusted
    ("adv_adj_taxable",    "11B - Adv Adjusted",  "Taxable"),
    ("adv_adj_igst",       "11B - Adv Adjusted",  "IGST"),
    ("adv_adj_cgst",       "11B - Adv Adjusted",  "CGST"),
    ("adv_adj_sgst",       "11B - Adv Adjusted",  "SGST"),
    # 14 E-Commerce u/s 52
    ("eco_taxable",        "14 - E-Commerce",     "Taxable"),
    ("eco_igst",           "14 - E-Commerce",     "IGST"),
    ("eco_cgst",           "14 - E-Commerce",     "CGST"),
    ("eco_sgst",           "14 - E-Commerce",     "SGST"),
    # 15 Supplies u/s 9(5)
    ("s95_taxable",        "15 - u/s 9(5)",       "Taxable"),
    ("s95_igst",           "15 - u/s 9(5)",       "IGST"),
    ("s95_cgst",           "15 - u/s 9(5)",       "CGST"),
    ("s95_sgst",           "15 - u/s 9(5)",       "SGST"),
    # HSN Summary (authoritative)
    ("hsn_taxable",        "12 - HSN Summary",    "Taxable"),
    ("hsn_igst",           "12 - HSN Summary",    "IGST"),
    ("hsn_cgst",           "12 - HSN Summary",    "CGST"),
    ("hsn_sgst",           "12 - HSN Summary",    "SGST"),
    # Total Tax
    ("hsn_taxable",        "Total Tax",           "Taxable"),
    ("hsn_igst",           "Total Tax",           "IGST"),
    ("hsn_cgst",           "Total Tax",           "CGST"),
    ("hsn_sgst",           "Total Tax",           "SGST"),
]


def _generate_mom_excel(rows, annual_row, fmt, gstin, output_path):
    """
    Generate the MOM Excel workbook with openpyxl, matching the screen table exactly.

    rows        — list of monthly data dicts (from _build_ext_row)
    annual_row  — dict or None  (Annual PDF reference row)
    fmt         — 'raw' | 'l' | 'cr'
    gstin       — GSTIN string for sheet header
    output_path — where to write the .xlsx file
    """
    # ── Divisor and number format ─────────────────────────────────────────────
    if fmt == "l":
        divisor  = 1e5
        num_fmt  = '#,##0.00'
        fmt_note = "Values in Lakhs (÷ 1,00,000)"
    elif fmt == "cr":
        divisor  = 1e7
        num_fmt  = '#,##0.00'
        fmt_note = "Values in Crores (÷ 1,00,00,000)"
    else:
        divisor  = 1.0
        num_fmt  = '#,##0.00'
        fmt_note = "Values in Rupees (₹)"

    def _v(val):
        """Scale a value by divisor; return None for None."""
        if val is None:
            return None
        try:
            return round(float(val) / divisor, 2)
        except (TypeError, ValueError):
            return None

    def _sum_col(key):
        return sum(float(r.get(key) or 0) for r in rows)

    # ── Styles ────────────────────────────────────────────────────────────────
    def _fill(hex_color):
        return PatternFill("solid", fgColor=hex_color)

    def _font(bold=False, italic=False, color="000000", size=9):
        return Font(bold=bold, italic=italic, color=color, size=size, name="Calibri")

    def _border(top=None, bottom=None, left=None, right=None):
        def _s(c): return Side(style="thin", color=c) if c else None
        def _m(c): return Side(style="medium", color=c) if c else None
        return Border(
            top=_m(top) if top else None,
            bottom=_m(bottom) if bottom else None,
            left=_s(left) if left else None,
            right=_s(right) if right else None,
        )

    # Colour palette (dark professional theme)
    C_GRP_BG   = "1C3557"   # group header bg
    C_GRP_FG   = "FFFFFF"   # group header text
    C_SUB_BG   = "243F63"   # sub-header bg
    C_SUB_FG   = "B8D0F0"   # sub-header text
    C_META_BG  = "0F2030"   # Period/Type header bg
    C_META_FG  = "7A9EBF"   # Period/Type header text
    C_EVEN_BG  = "FFFFFF"   # even data row
    C_ODD_BG   = "F2F6FC"   # odd data row
    C_TYPE_BG  = "EBF3FF"   # type badge bg
    C_TYPE_FG  = "1A56C4"   # type badge text
    C_TOT_BG   = "11243A"   # TOTAL row bg
    C_TOT_FG   = "FFFFFF"   # TOTAL row text
    C_ANN_BG   = "FFF8E1"   # Annual row bg
    C_ANN_FG   = "7B5800"   # Annual row text
    C_DIFF_BG  = "F9FAFB"   # Difference row bg
    C_NIL_FG   = "1A7A3A"   # Nil cell text (green)
    C_POS_FG   = "856404"   # positive diff (amber)
    C_NEG_FG   = "B91C1C"   # negative diff (red)
    C_DIFF_LBL = "6B7280"   # Difference label text

    # ── Workbook / sheet ──────────────────────────────────────────────────────
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "GSTR-1 MOM"
    ws.sheet_view.showGridLines = False

    PERIOD_COL = 1
    TYPE_COL   = 2
    DATA_START = 3          # data columns start at col 3
    N_DATA     = len(_MOM_COLS)   # 29 data columns → total cols = 31

    # ── Title row (row 1) ─────────────────────────────────────────────────────
    title_text = f"GSTR-1 Month-over-Month Analysis  |  GSTIN: {gstin}  |  {fmt_note}"
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=DATA_START + N_DATA - 1)
    tc = ws.cell(1, 1, title_text)
    tc.fill      = _fill("0A1929")
    tc.font      = _font(bold=True, color="5BA3D9", size=10)
    tc.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[1].height = 26

    # ── Group header row (row 2) ──────────────────────────────────────────────
    ROW_GRP  = 2
    ROW_SUB  = 3
    ROW_DATA = 4   # data rows start here

    # Period (merge rows 2-3)
    ws.merge_cells(start_row=ROW_GRP, start_column=PERIOD_COL,
                   end_row=ROW_SUB,   end_column=PERIOD_COL)
    pc = ws.cell(ROW_GRP, PERIOD_COL, "PERIOD")
    pc.fill      = _fill(C_META_BG)
    pc.font      = _font(bold=True, color=C_META_FG, size=8)
    pc.alignment = Alignment(horizontal="center", vertical="bottom")

    # Type (merge rows 2-3)
    ws.merge_cells(start_row=ROW_GRP, start_column=TYPE_COL,
                   end_row=ROW_SUB,   end_column=TYPE_COL)
    tyc = ws.cell(ROW_GRP, TYPE_COL, "TYPE")
    tyc.fill      = _fill(C_META_BG)
    tyc.font      = _font(bold=True, color=C_META_FG, size=8)
    tyc.alignment = Alignment(horizontal="center", vertical="bottom")

    # Group spans (col indices are 1-based, DATA_START=3)
    # 4A B2B=3-6, 4B RCM=7-10, B2CL=11-12, B2CS=13-16, NIL=17-19,
    # 6A EXPWP=20-21, 6A EXPWOP=22, 6B SEZWP=23-24, 6B SEZWOP=25,
    # 6C DE=26-29, CDNR=30-33, CDNUR=34-37, CDNRA=38-41, CDNURA=42-43,
    # 9A B2B=44-47, 9A B2CL=48-49, 9A Exp=50-51, 9A SEZ=52-53, 9A DE=54-55,
    # 10=56-59, 11A=60-63, 11B=64-67, 14=68-71, 15=72-75, HSN=76-79, Total=80-83
    _groups = [
        ("4A - B2B Regular",    3,  6),
        ("4B - B2B RCM",        7,  10),
        ("5A/5B - B2CL",        11, 12),
        ("7 - B2CS",            13, 16),
        ("8 - NIL / Exempt",    17, 19),
        ("6A - Exports EXPWP",  20, 21),
        ("6A - Exports EXPWOP", 22, 22),
        ("6B - SEZ SEZWP",      23, 24),
        ("6B - SEZ SEZWOP",     25, 25),
        ("6C - Deemed Exports", 26, 29),
        ("9B - CDN Reg.",       30, 33),
        ("9B - CDN Unreg.",     34, 37),
        ("9C - CDNRA",          38, 41),
        ("9C - CDNURA",         42, 43),
        ("9A - Amend B2B",      44, 47),
        ("9A - Amend B2CL",     48, 49),
        ("9A - Amend Exports",  50, 51),
        ("9A - Amend SEZ",      52, 53),
        ("9A - Amend DE",       54, 55),
        ("10 - B2CS Amend",     56, 59),
        ("11A - Adv Received",  60, 63),
        ("11B - Adv Adjusted",  64, 67),
        ("14 - E-Commerce",     68, 71),
        ("15 - u/s 9(5)",       72, 75),
        ("12 - HSN Summary",    76, 79),
        ("Total Tax",           80, 83),
    ]
    for grp_name, cs, ce in _groups:
        ws.merge_cells(start_row=ROW_GRP, start_column=cs,
                       end_row=ROW_GRP,   end_column=ce)
        gc = ws.cell(ROW_GRP, cs, grp_name)
        gc.fill      = _fill(C_GRP_BG)
        gc.font      = _font(bold=True, color=C_GRP_FG, size=9)
        gc.alignment = Alignment(horizontal="center", vertical="center")
        # Fill merged cells in the same row
        for col in range(cs + 1, ce + 1):
            ws.cell(ROW_GRP, col).fill = _fill(C_GRP_BG)

    ws.row_dimensions[ROW_GRP].height = 22

    # ── Sub-column header row (row 3) ─────────────────────────────────────────
    ws.cell(ROW_SUB, PERIOD_COL).fill = _fill(C_META_BG)
    ws.cell(ROW_SUB, TYPE_COL).fill   = _fill(C_META_BG)
    for j, (key, grp, sub) in enumerate(_MOM_COLS):
        col = DATA_START + j
        sc = ws.cell(ROW_SUB, col, sub)
        sc.fill      = _fill(C_SUB_BG)
        sc.font      = _font(bold=True, color=C_SUB_FG, size=8)
        sc.alignment = Alignment(horizontal="right", vertical="center")
    ws.row_dimensions[ROW_SUB].height = 16

    # ── Data rows ─────────────────────────────────────────────────────────────
    for i, row in enumerate(rows):
        er = ROW_DATA + i
        bg = C_ODD_BG if i % 2 else C_EVEN_BG

        # Period
        pc = ws.cell(er, PERIOD_COL, row.get("period", ""))
        pc.fill      = _fill(bg)
        pc.font      = _font(color="1E293B", size=9)
        pc.alignment = Alignment(horizontal="left", vertical="center", indent=1)

        # Type
        tc2 = ws.cell(er, TYPE_COL, row.get("gst_type", "GSTR-1"))
        tc2.fill      = _fill(C_TYPE_BG)
        tc2.font      = _font(bold=True, color=C_TYPE_FG, size=8)
        tc2.alignment = Alignment(horizontal="center", vertical="center")

        for j, (key, grp, sub) in enumerate(_MOM_COLS):
            col = DATA_START + j
            val = _v(row.get(key))
            dc = ws.cell(er, col, val)
            dc.fill          = _fill(bg)
            dc.font          = _font(color="334155", size=8)
            dc.alignment     = Alignment(horizontal="right", vertical="center")
            dc.number_format = num_fmt

        ws.row_dimensions[er].height = 17

    # ── TOTAL row ─────────────────────────────────────────────────────────────
    total_r = ROW_DATA + len(rows)
    top_border = _border(top="374151")

    tc3 = ws.cell(total_r, PERIOD_COL, "TOTAL")
    tc3.fill      = _fill(C_TOT_BG)
    tc3.font      = _font(bold=True, color=C_TOT_FG, size=9)
    tc3.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    tc3.border    = top_border

    ws.cell(total_r, TYPE_COL).fill   = _fill(C_TOT_BG)
    ws.cell(total_r, TYPE_COL).border = top_border

    for j, (key, grp, sub) in enumerate(_MOM_COLS):
        col  = DATA_START + j
        tval = _v(_sum_col(key))
        tvc  = ws.cell(total_r, col, tval)
        tvc.fill          = _fill(C_TOT_BG)
        tvc.font          = _font(bold=True, color=C_TOT_FG, size=9)
        tvc.alignment     = Alignment(horizontal="right", vertical="center")
        tvc.number_format = num_fmt
        tvc.border        = top_border

    ws.row_dimensions[total_r].height = 20
    next_r = total_r + 1

    # ── Annual row ────────────────────────────────────────────────────────────
    if annual_row:
        ann_lbl = f"Annual (PDF)  ·  {annual_row.get('period', '')}"
        ac = ws.cell(next_r, PERIOD_COL, ann_lbl)
        ac.fill      = _fill(C_ANN_BG)
        ac.font      = _font(bold=True, color=C_ANN_FG, size=9)
        ac.alignment = Alignment(horizontal="left", vertical="center", indent=1)

        atc = ws.cell(next_r, TYPE_COL, annual_row.get("gst_type", "GSTR-1"))
        atc.fill      = _fill(C_ANN_BG)
        atc.font      = _font(bold=True, color=C_ANN_FG, size=8)
        atc.alignment = Alignment(horizontal="center", vertical="center")

        for j, (key, grp, sub) in enumerate(_MOM_COLS):
            col = DATA_START + j
            avc = ws.cell(next_r, col, _v(annual_row.get(key)))
            avc.fill          = _fill(C_ANN_BG)
            avc.font          = _font(bold=True, color=C_ANN_FG, size=9)
            avc.alignment     = Alignment(horizontal="right", vertical="center")
            avc.number_format = num_fmt

        ws.row_dimensions[next_r].height = 20
        next_r += 1

        # ── Difference row  (Annual − MOM Total) ─────────────────────────────
        dc_lbl = ws.cell(next_r, PERIOD_COL, "Difference  (Annual − Total)")
        dc_lbl.fill      = _fill(C_DIFF_BG)
        dc_lbl.font      = _font(bold=True, italic=True, color=C_DIFF_LBL, size=9)
        dc_lbl.alignment = Alignment(horizontal="left", vertical="center", indent=1)

        ws.cell(next_r, TYPE_COL).fill = _fill(C_DIFF_BG)

        for j, (key, grp, sub) in enumerate(_MOM_COLS):
            col     = DATA_START + j
            ann_v   = float(annual_row.get(key) or 0)
            tot_v   = _sum_col(key)
            delta   = ann_v - tot_v

            if abs(delta) < 0.01:
                dfc = ws.cell(next_r, col, "Nil")
                dfc.fill      = _fill(C_DIFF_BG)
                dfc.font      = _font(italic=True, color=C_NIL_FG, size=8)
                dfc.alignment = Alignment(horizontal="right", vertical="center")
            else:
                dfc = ws.cell(next_r, col, _v(delta))
                dfc.fill          = _fill(C_DIFF_BG)
                dfc.font          = _font(bold=True, color=C_POS_FG if delta > 0 else C_NEG_FG, size=8)
                dfc.alignment     = Alignment(horizontal="right", vertical="center")
                dfc.number_format = num_fmt

        ws.row_dimensions[next_r].height = 19

    # ── Column widths ─────────────────────────────────────────────────────────
    ws.column_dimensions[get_column_letter(PERIOD_COL)].width = 18
    ws.column_dimensions[get_column_letter(TYPE_COL)].width   = 10
    for j in range(N_DATA):
        ws.column_dimensions[get_column_letter(DATA_START + j)].width = 15

    # ── Freeze header rows and Period/Type columns ────────────────────────────
    ws.freeze_panes = ws.cell(ROW_DATA, DATA_START)

    # ── Auto-filter on data rows ──────────────────────────────────────────────
    last_col = get_column_letter(DATA_START + N_DATA - 1)
    ws.auto_filter.ref = f"A{ROW_DATA}:{last_col}{ROW_DATA + len(rows) - 1}"

    wb.save(output_path)
    logger.info("[MOM Export] Saved to %s", output_path)


@export_bp.get("/export/mom/excel")
def mom_excel():
    """
    Generate GSTR-1 MOM Excel matching the screen table exactly.

    Query params:
        format          — 'raw' | 'l' | 'cr'  (default: 'raw')
        annual_file_id  — file_id of the annual reference PDF (optional)
    """
    fmt            = request.args.get("format", "raw")
    annual_file_id = request.args.get("annual_file_id", "").strip()
    if fmt not in ("raw", "l", "cr"):
        fmt = "raw"

    # ── Collect monthly GSTR-1 rows (exclude annual if provided) ─────────────
    monthly_rows = []
    annual_row   = None
    gstin_found  = ""

    for file_id, file_info in store.files.items():
        if file_info.get("gst_type") != "GSTR-1":
            continue
        ext = store.get_extracted_data(file_id)
        if not ext:
            continue
        if not gstin_found:
            gstin_found = ext.get("gstin") or ""

        row = _build_ext_row(file_info, ext)

        if file_id == annual_file_id:
            annual_row = row   # annual reference — shown separately
        else:
            monthly_rows.append(row)

    logger.info("[MOM Export] monthly=%d  annual=%s", len(monthly_rows),
                "yes" if annual_row else "no")

    if not monthly_rows:
        return jsonify(error="No GSTR-1 files found in session"), 404

    monthly_rows.sort(key=_fy_sort_key)

    # ── Output path ───────────────────────────────────────────────────────────
    ts            = datetime.now().strftime("%Y%m%d_%H%M%S")
    gstin_part    = (gstin_found or "UNKNOWN").replace(" ", "")
    download_name = f"GSTR1_{gstin_part}_MOM_{ts}.xlsx"
    out_path      = os.path.join("output", download_name)

    try:
        _generate_mom_excel(
            rows        = monthly_rows,
            annual_row  = annual_row,
            fmt         = fmt,
            gstin       = gstin_found,
            output_path = out_path,
        )
    except Exception as exc:
        logger.exception("[MOM Export] Generation failed: %s", exc)
        return jsonify(success=False, error=str(exc)), 500

    return send_file(
        out_path,
        as_attachment=True,
        download_name=download_name,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ── GSTR-3B MOM column schema (52 data columns, matches reference Excel) ──────
_MOM_3B_COLS = [
    # 3.1(a) Outward Taxable — 5 cols
    ("s31a_taxable",        "3.1(a) Taxable",     "Taxable"),
    ("s31a_igst",           "3.1(a) Taxable",     "IGST"),
    ("s31a_cgst",           "3.1(a) Taxable",     "CGST"),
    ("s31a_sgst",           "3.1(a) Taxable",     "SGST"),
    ("s31a_cess",           "3.1(a) Taxable",     "Cess"),
    # 3.1(b) Zero Rated — 4 cols
    ("s31b_taxable",        "3.1(b) Zero Rated",  "Taxable"),
    ("s31b_igst",           "3.1(b) Zero Rated",  "IGST"),
    ("s31b_cgst",           "3.1(b) Zero Rated",  "CGST"),
    ("s31b_sgst",           "3.1(b) Zero Rated",  "SGST"),
    # 3.1(c) Nil/Exempt — 1 col
    ("s31c_taxable",        "3.1(c) Nil/Exempt",  "Taxable"),
    # 3.1(d) RCM — 4 cols
    ("s31d_rcm_taxable",    "3.1(d) RCM",         "Taxable"),
    ("s31d_rcm_igst",       "3.1(d) RCM",         "IGST"),
    ("s31d_rcm_cgst",       "3.1(d) RCM",         "CGST"),
    ("s31d_rcm_sgst",       "3.1(d) RCM",         "SGST"),
    # 3.1(e) Non-GST — 1 col
    ("s31e_taxable",        "3.1(e) Non-GST",     "Taxable"),
    # 3.1.1(i) ECO Operator pays tax u/s 9(5) — 5 cols
    ("s311i_taxable",       "3.1.1(i) ECO-9(5)",  "Taxable"),
    ("s311i_igst",          "3.1.1(i) ECO-9(5)",  "IGST"),
    ("s311i_cgst",          "3.1.1(i) ECO-9(5)",  "CGST"),
    ("s311i_sgst",          "3.1.1(i) ECO-9(5)",  "SGST"),
    ("s311i_cess",          "3.1.1(i) ECO-9(5)",  "Cess"),
    # 3.1.1(ii) Reg person through ECO — 1 col (taxable only)
    ("s311ii_taxable",      "3.1.1(ii) Reg-ECO",  "Taxable"),
    # 3.2 Interstate — 4 cols
    ("s32_unreg_taxable",   "3.2 Interstate",     "Unreg Tax"),
    ("s32_unreg_igst",      "3.2 Interstate",     "Unreg IGST"),
    ("s32_comp_taxable",    "3.2 Interstate",     "Comp Tax"),
    ("s32_uin_taxable",     "3.2 Interstate",     "UIN Tax"),
    # 4(A)(1) Import of Goods — 4 cols
    ("itc_a1_igst",         "4(A)(1) Imp Goods",  "IGST"),
    ("itc_a1_cgst",         "4(A)(1) Imp Goods",  "CGST"),
    ("itc_a1_sgst",         "4(A)(1) Imp Goods",  "SGST"),
    ("itc_a1_cess",         "4(A)(1) Imp Goods",  "Cess"),
    # 4(A)(2) Import of Services — 4 cols
    ("itc_a2_igst",         "4(A)(2) Imp Svcs",   "IGST"),
    ("itc_a2_cgst",         "4(A)(2) Imp Svcs",   "CGST"),
    ("itc_a2_sgst",         "4(A)(2) Imp Svcs",   "SGST"),
    ("itc_a2_cess",         "4(A)(2) Imp Svcs",   "Cess"),
    # 4(A)(3) Inward RCM — 4 cols
    ("itc_a3_igst",         "4(A)(3) RCM Inward", "IGST"),
    ("itc_a3_cgst",         "4(A)(3) RCM Inward", "CGST"),
    ("itc_a3_sgst",         "4(A)(3) RCM Inward", "SGST"),
    ("itc_a3_cess",         "4(A)(3) RCM Inward", "Cess"),
    # 4(A)(4) ISD — 4 cols
    ("itc_a4_igst",         "4(A)(4) ISD",        "IGST"),
    ("itc_a4_cgst",         "4(A)(4) ISD",        "CGST"),
    ("itc_a4_sgst",         "4(A)(4) ISD",        "SGST"),
    ("itc_a4_cess",         "4(A)(4) ISD",        "Cess"),
    # 4(A)(5) All Other ITC — 4 cols
    ("itc_a5_igst",         "4(A)(5) Other ITC",  "IGST"),
    ("itc_a5_cgst",         "4(A)(5) Other ITC",  "CGST"),
    ("itc_a5_sgst",         "4(A)(5) Other ITC",  "SGST"),
    ("itc_a5_cess",         "4(A)(5) Other ITC",  "Cess"),
    # 4(A) Total Available — 4 cols
    ("itc_avail_igst",      "4(A) Total Avail",   "IGST"),
    ("itc_avail_cgst",      "4(A) Total Avail",   "CGST"),
    ("itc_avail_sgst",      "4(A) Total Avail",   "SGST"),
    ("itc_avail_cess",      "4(A) Total Avail",   "Cess"),
    # 4(B)(1) Rules 38,42,43 & s17(5) — 4 cols
    ("itc_b1_igst",         "4(B)(1) Rules",      "IGST"),
    ("itc_b1_cgst",         "4(B)(1) Rules",      "CGST"),
    ("itc_b1_sgst",         "4(B)(1) Rules",      "SGST"),
    ("itc_b1_cess",         "4(B)(1) Rules",      "Cess"),
    # 4(B)(2) Others — 4 cols
    ("itc_b2_igst",         "4(B)(2) Others",     "IGST"),
    ("itc_b2_cgst",         "4(B)(2) Others",     "CGST"),
    ("itc_b2_sgst",         "4(B)(2) Others",     "SGST"),
    ("itc_b2_cess",         "4(B)(2) Others",     "Cess"),
    # 4(B) Total Reversed — 4 cols
    ("itc_rev_igst",        "4(B) Total Rev",     "IGST"),
    ("itc_rev_cgst",        "4(B) Total Rev",     "CGST"),
    ("itc_rev_sgst",        "4(B) Total Rev",     "SGST"),
    ("itc_rev_cess",        "4(B) Total Rev",     "Cess"),
    # 4(C) Net ITC — 4 cols
    ("itc_net_igst",        "4(C) Net ITC",       "IGST"),
    ("itc_net_cgst",        "4(C) Net ITC",       "CGST"),
    ("itc_net_sgst",        "4(C) Net ITC",       "SGST"),
    ("itc_net_cess",        "4(C) Net ITC",       "Cess"),
    # 4(D)(1) ITC reclaimed reversed u/T 4(B)(2) — 4 cols
    ("itc_d1_igst",         "4(D)(1) Reclaimed",  "IGST"),
    ("itc_d1_cgst",         "4(D)(1) Reclaimed",  "CGST"),
    ("itc_d1_sgst",         "4(D)(1) Reclaimed",  "SGST"),
    ("itc_d1_cess",         "4(D)(1) Reclaimed",  "Cess"),
    # 4(D)(2) Ineligible ITC u/s 16(4) & PoS — 4 cols
    ("itc_d2_igst",         "4(D)(2) Ineligible", "IGST"),
    ("itc_d2_cgst",         "4(D)(2) Ineligible", "CGST"),
    ("itc_d2_sgst",         "4(D)(2) Ineligible", "SGST"),
    ("itc_d2_cess",         "4(D)(2) Ineligible", "Cess"),
    # Sec 5 Nil/Exempt — 3 cols
    ("s5_nil_interstate",   "Sec 5 - Nil/Exempt", "Inter-State"),
    ("s5_nil_intrastate",   "Sec 5 - Nil/Exempt", "Intra-State"),
    ("s5_nil_total",        "Sec 5 - Nil/Exempt", "Total"),
    # Sec 5 Non-GST — 3 cols
    ("s5_nongst_interstate","Sec 5 - Non-GST",    "Inter-State"),
    ("s5_nongst_intrastate","Sec 5 - Non-GST",    "Intra-State"),
    ("s5_nongst_total",     "Sec 5 - Non-GST",    "Total"),
    # 5.1 Interest — 4 cols
    ("s51_int_igst",        "5.1 Interest",       "IGST"),
    ("s51_int_cgst",        "5.1 Interest",       "CGST"),
    ("s51_int_sgst",        "5.1 Interest",       "SGST"),
    ("s51_int_cess",        "5.1 Interest",       "Cess"),
    # 5.1 Late Fee — 3 cols
    ("s51_latefee_cgst",    "5.1 Late Fee",       "CGST"),
    ("s51_latefee_sgst",    "5.1 Late Fee",       "SGST"),
    ("s51_latefee_total",   "5.1 Late Fee",       "Total"),
    # Payment (6.1) — 9 cols
    ("pay_total_igst",      "Payment (6.1)",      "Total IGST"),
    ("pay_total_cgst",      "Payment (6.1)",      "Total CGST"),
    ("pay_total_sgst",      "Payment (6.1)",      "Total SGST"),
    ("pay_itc_igst",        "Payment (6.1)",      "ITC IGST"),
    ("pay_itc_cgst",        "Payment (6.1)",      "ITC CGST"),
    ("pay_itc_sgst",        "Payment (6.1)",      "ITC SGST"),
    ("pay_cash_igst",       "Payment (6.1)",      "Cash IGST"),
    ("pay_cash_cgst",       "Payment (6.1)",      "Cash CGST"),
    ("pay_cash_sgst",       "Payment (6.1)",      "Cash SGST"),
]

# Group spans for row-2 header (col indices 1-based, DATA_START = 3)
# 3.1(a)=3-7 | 3.1(b)=8-11 | 3.1(c)=12 | 3.1(d)=13-16 | 3.1(e)=17
# 3.1.1(i)=18-22 | 3.1.1(ii)=23 | 3.2=24-27
# ITC: A1=28-31, A2=32-35, A3=36-39, A4=40-43, A5=44-47, A-Total=48-51
#       B1=52-55, B2=56-59, B-Total=60-63, C=64-67, D1=68-71, D2=72-75
# Sec5Nil=76-78 | Sec5NonGST=79-81 | Int=82-85 | LateFee=86-88 | Pay=89-97
_3B_GROUPS = [
    ("3.1(a) Taxable",          3,   7),
    ("3.1(b) Zero Rated",       8,  11),
    ("3.1(c) Nil/Exempt",      12,  12),
    ("3.1(d) RCM",             13,  16),
    ("3.1(e) Non-GST",         17,  17),
    ("3.1.1(i) ECO-9(5)",      18,  22),
    ("3.1.1(ii) Reg-ECO",      23,  23),
    ("3.2 Interstate",         24,  27),
    ("4(A)(1) Imp Goods",      28,  31),
    ("4(A)(2) Imp Svcs",       32,  35),
    ("4(A)(3) RCM Inward",     36,  39),
    ("4(A)(4) ISD",            40,  43),
    ("4(A)(5) Other ITC",      44,  47),
    ("4(A) Total Avail",       48,  51),
    ("4(B)(1) Rules",          52,  55),
    ("4(B)(2) Others",         56,  59),
    ("4(B) Total Rev",         60,  63),
    ("4(C) Net ITC",           64,  67),
    ("4(D)(1) Reclaimed",      68,  71),
    ("4(D)(2) Ineligible",     72,  75),
    ("Sec 5 - Nil/Exempt",     76,  78),
    ("Sec 5 - Non-GST",        79,  81),
    ("5.1 Interest",           82,  85),
    ("5.1 Late Fee",           86,  88),
    ("Payment (6.1)",          89,  97),
]


def _build_3b_ext_row(file_info, ext):
    """Map GSTR-3B extracted_data to the 52-column MOM schema."""
    period = file_info.get("period") or ext.get("period") or ""

    # Computed totals
    itc_igst = ext.get("itc_used_igst") or 0
    itc_cgst = ext.get("itc_used_cgst") or 0
    itc_sgst = ext.get("itc_used_sgst") or 0
    cash_igst = ext.get("cash_paid_igst") or 0
    cash_cgst = ext.get("cash_paid_cgst") or 0
    cash_sgst = ext.get("cash_paid_sgst") or 0

    pay_total_igst = (itc_igst + cash_igst) or None
    pay_total_cgst = (itc_cgst + cash_cgst) or None
    pay_total_sgst = (itc_sgst + cash_sgst) or None

    nil_inter  = ext.get("s5_nil_interstate") or 0
    nil_intra  = ext.get("s5_nil_intrastate") or 0
    ng_inter   = ext.get("s5_nongst_interstate") or 0
    ng_intra   = ext.get("s5_nongst_intrastate") or 0

    lf_cgst = ext.get("s51_latefee_cgst") or 0
    lf_sgst = ext.get("s51_latefee_sgst") or 0

    return {
        "period":               period,
        "gst_type":             "GSTR-3B",
        # 3.1(a)
        "s31a_taxable":         ext.get("taxable_sales"),
        "s31a_igst":            ext.get("igst_on_sales"),
        "s31a_cgst":            ext.get("cgst_on_sales"),
        "s31a_sgst":            ext.get("sgst_on_sales"),
        "s31a_cess":            ext.get("cess_on_sales"),
        # 3.1(b)
        "s31b_taxable":         ext.get("zero_rated_sales"),
        "s31b_igst":            ext.get("s31b_igst"),
        "s31b_cgst":            None,   # zero-rated has no CGST/SGST
        "s31b_sgst":            None,
        # 3.1(c)
        "s31c_taxable":         ext.get("nil_rated_sales"),
        # 3.1(d)
        "s31d_rcm_taxable":     ext.get("s31d_rcm_taxable"),
        "s31d_rcm_igst":        ext.get("s31d_rcm_igst"),
        "s31d_rcm_cgst":        ext.get("s31d_rcm_cgst"),
        "s31d_rcm_sgst":        ext.get("s31d_rcm_sgst"),
        # 3.1(e)
        "s31e_taxable":         ext.get("non_gst_sales"),
        # 3.1.1(i) — ECO operator pays tax u/s 9(5)
        "s311i_taxable":        ext.get("s311i_taxable"),
        "s311i_igst":           ext.get("s311i_igst"),
        "s311i_cgst":           ext.get("s311i_cgst"),
        "s311i_sgst":           ext.get("s311i_sgst"),
        "s311i_cess":           ext.get("s311i_cess"),
        # 3.1.1(ii) — Registered person through ECO
        "s311ii_taxable":       ext.get("s311ii_taxable"),
        # 3.2
        "s32_unreg_taxable":    ext.get("s32_unreg_taxable"),
        "s32_unreg_igst":       ext.get("s32_unreg_igst"),
        "s32_comp_taxable":     ext.get("s32_comp_taxable"),
        "s32_uin_taxable":      ext.get("s32_uin_taxable"),
        # 4(A)(1)–(5) individual sub-items
        "itc_a1_igst":          ext.get("itc_a1_igst"),
        "itc_a1_cgst":          ext.get("itc_a1_cgst"),
        "itc_a1_sgst":          ext.get("itc_a1_sgst"),
        "itc_a1_cess":          ext.get("itc_a1_cess"),
        "itc_a2_igst":          ext.get("itc_a2_igst"),
        "itc_a2_cgst":          ext.get("itc_a2_cgst"),
        "itc_a2_sgst":          ext.get("itc_a2_sgst"),
        "itc_a2_cess":          ext.get("itc_a2_cess"),
        "itc_a3_igst":          ext.get("itc_a3_igst"),
        "itc_a3_cgst":          ext.get("itc_a3_cgst"),
        "itc_a3_sgst":          ext.get("itc_a3_sgst"),
        "itc_a3_cess":          ext.get("itc_a3_cess"),
        "itc_a4_igst":          ext.get("itc_a4_igst"),
        "itc_a4_cgst":          ext.get("itc_a4_cgst"),
        "itc_a4_sgst":          ext.get("itc_a4_sgst"),
        "itc_a4_cess":          ext.get("itc_a4_cess"),
        "itc_a5_igst":          ext.get("itc_a5_igst"),
        "itc_a5_cgst":          ext.get("itc_a5_cgst"),
        "itc_a5_sgst":          ext.get("itc_a5_sgst"),
        "itc_a5_cess":          ext.get("itc_a5_cess"),
        # 4(A) Total Available
        "itc_avail_igst":       ext.get("itc_avail_igst"),
        "itc_avail_cgst":       ext.get("itc_avail_cgst"),
        "itc_avail_sgst":       ext.get("itc_avail_sgst"),
        "itc_avail_cess":       ext.get("itc_avail_cess"),
        # 4(B)(1)–(2) individual sub-items
        "itc_b1_igst":          ext.get("itc_b1_igst"),
        "itc_b1_cgst":          ext.get("itc_b1_cgst"),
        "itc_b1_sgst":          ext.get("itc_b1_sgst"),
        "itc_b1_cess":          ext.get("itc_b1_cess"),
        "itc_b2_igst":          ext.get("itc_b2_igst"),
        "itc_b2_cgst":          ext.get("itc_b2_cgst"),
        "itc_b2_sgst":          ext.get("itc_b2_sgst"),
        "itc_b2_cess":          ext.get("itc_b2_cess"),
        # 4(B) Total Reversed
        "itc_rev_igst":         ext.get("itc_reversed_igst"),
        "itc_rev_cgst":         ext.get("itc_reversed_cgst"),
        "itc_rev_sgst":         ext.get("itc_reversed_sgst"),
        "itc_rev_cess":         ext.get("itc_rev_cess"),
        # 4(C) Net ITC
        "itc_net_igst":         ext.get("itc_igst_available"),
        "itc_net_cgst":         ext.get("itc_cgst_available"),
        "itc_net_sgst":         ext.get("itc_sgst_available"),
        "itc_net_cess":         ext.get("itc_net_cess"),
        # ITC 4(D)(1) — reclaimed reversed under 4(B)(2)
        "itc_d1_igst":          ext.get("itc_d1_igst"),
        "itc_d1_cgst":          ext.get("itc_d1_cgst"),
        "itc_d1_sgst":          ext.get("itc_d1_sgst"),
        "itc_d1_cess":          ext.get("itc_d1_cess"),
        # ITC 4(D)(2) — ineligible u/s 16(4) & PoS rules
        "itc_d2_igst":          ext.get("itc_d2_igst"),
        "itc_d2_cgst":          ext.get("itc_d2_cgst"),
        "itc_d2_sgst":          ext.get("itc_d2_sgst"),
        "itc_d2_cess":          ext.get("itc_d2_cess"),
        # Sec 5
        "s5_nil_interstate":    ext.get("s5_nil_interstate"),
        "s5_nil_intrastate":    ext.get("s5_nil_intrastate"),
        "s5_nil_total":         (nil_inter + nil_intra) or None,
        "s5_nongst_interstate": ext.get("s5_nongst_interstate"),
        "s5_nongst_intrastate": ext.get("s5_nongst_intrastate"),
        "s5_nongst_total":      (ng_inter + ng_intra) or None,
        # 5.1 Interest
        "s51_int_igst":         ext.get("s51_int_igst"),
        "s51_int_cgst":         ext.get("s51_int_cgst"),
        "s51_int_sgst":         ext.get("s51_int_sgst"),
        "s51_int_cess":         ext.get("s51_int_cess"),
        # 5.1 Late Fee
        "s51_latefee_cgst":     ext.get("s51_latefee_cgst"),
        "s51_latefee_sgst":     ext.get("s51_latefee_sgst"),
        "s51_latefee_total":    (lf_cgst + lf_sgst) or ext.get("late_fee_paid") or None,
        # Payment
        "pay_total_igst":       pay_total_igst,
        "pay_total_cgst":       pay_total_cgst,
        "pay_total_sgst":       pay_total_sgst,
        "pay_itc_igst":         ext.get("itc_used_igst"),
        "pay_itc_cgst":         ext.get("itc_used_cgst"),
        "pay_itc_sgst":         ext.get("itc_used_sgst"),
        "pay_cash_igst":        ext.get("cash_paid_igst"),
        "pay_cash_cgst":        ext.get("cash_paid_cgst"),
        "pay_cash_sgst":        ext.get("cash_paid_sgst"),
    }


def _generate_3b_mom_excel(rows, fmt, gstin, output_path, annual_row=None):
    """
    Generate GSTR-3B MOM Excel matching the reference format exactly.
    52 data columns, professional dark-blue header theme.
    """
    if fmt == "l":
        divisor  = 1e5;  num_fmt = '#,##0.00'; fmt_note = "Values in Lakhs (÷ 1,00,000)"
    elif fmt == "cr":
        divisor  = 1e7;  num_fmt = '#,##0.00'; fmt_note = "Values in Crores (÷ 1,00,00,000)"
    else:
        divisor  = 1.0;  num_fmt = '#,##0.00'; fmt_note = "Values in Rupees (₹)"

    def _v(val):
        if val is None: return None
        try: return round(float(val) / divisor, 2)
        except (TypeError, ValueError): return None

    def _sum_col(key):
        return sum(float(r.get(key) or 0) for r in rows)

    def _fill(hex_c): return PatternFill("solid", fgColor=hex_c)
    def _font(bold=False, italic=False, color="000000", size=9):
        return Font(bold=bold, italic=italic, color=color, size=size, name="Calibri")

    C_GRP_BG  = "1C3557"; C_GRP_FG  = "FFFFFF"
    C_SUB_BG  = "243F63"; C_SUB_FG  = "B8D0F0"
    C_META_BG = "0F2030"; C_META_FG = "7A9EBF"
    C_EVEN_BG = "FFFFFF"; C_ODD_BG  = "F2F6FC"
    C_TYPE_BG = "EBF3FF"; C_TYPE_FG = "1A56C4"
    C_TOT_BG  = "11243A"; C_TOT_FG  = "FFFFFF"
    C_DIFF_BG = "F9FAFB"; C_NIL_FG  = "1A7A3A"
    C_POS_FG  = "856404"; C_NEG_FG  = "B91C1C"

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "GSTR-3B MOM"
    ws.sheet_view.showGridLines = False

    PERIOD_COL = 1; TYPE_COL = 2; DATA_START = 3
    N_DATA = len(_MOM_3B_COLS)   # 52 data columns → total cols = 54

    # ── Row 1: Title ─────────────────────────────────────────────────────────
    title_text = (f"GSTR-3B Month-over-Month  |  GSTIN: {gstin}  |  {fmt_note}")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=DATA_START + N_DATA - 1)
    tc = ws.cell(1, 1, title_text)
    tc.fill      = _fill("0A1929")
    tc.font      = _font(bold=True, color="5BA3D9", size=10)
    tc.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[1].height = 26

    ROW_GRP = 2; ROW_SUB = 3; ROW_DATA = 4

    # ── Row 2: PERIOD / TYPE (merged rows 2-3) ───────────────────────────────
    for col, label in [(PERIOD_COL, "PERIOD"), (TYPE_COL, "TYPE")]:
        ws.merge_cells(start_row=ROW_GRP, start_column=col, end_row=ROW_SUB, end_column=col)
        c = ws.cell(ROW_GRP, col, label)
        c.fill = _fill(C_META_BG); c.font = _font(bold=True, color=C_META_FG, size=8)
        c.alignment = Alignment(horizontal="center", vertical="bottom")

    # ── Row 2: Group headers ─────────────────────────────────────────────────
    for grp_name, cs, ce in _3B_GROUPS:
        ws.merge_cells(start_row=ROW_GRP, start_column=cs, end_row=ROW_GRP, end_column=ce)
        gc = ws.cell(ROW_GRP, cs, grp_name)
        gc.fill = _fill(C_GRP_BG); gc.font = _font(bold=True, color=C_GRP_FG, size=9)
        gc.alignment = Alignment(horizontal="center", vertical="center")
        for col in range(cs + 1, ce + 1):
            ws.cell(ROW_GRP, col).fill = _fill(C_GRP_BG)
    ws.row_dimensions[ROW_GRP].height = 22

    # ── Row 3: Sub-column headers ────────────────────────────────────────────
    ws.cell(ROW_SUB, PERIOD_COL).fill = _fill(C_META_BG)
    ws.cell(ROW_SUB, TYPE_COL).fill   = _fill(C_META_BG)
    for j, (key, grp, sub) in enumerate(_MOM_3B_COLS):
        col = DATA_START + j
        sc = ws.cell(ROW_SUB, col, sub)
        sc.fill = _fill(C_SUB_BG); sc.font = _font(bold=True, color=C_SUB_FG, size=8)
        sc.alignment = Alignment(horizontal="right", vertical="center")
    ws.row_dimensions[ROW_SUB].height = 16

    # ── Data rows ────────────────────────────────────────────────────────────
    for i, row in enumerate(rows):
        er = ROW_DATA + i
        bg = C_ODD_BG if i % 2 else C_EVEN_BG

        pc = ws.cell(er, PERIOD_COL, row.get("period", ""))
        pc.fill = _fill(bg); pc.font = _font(color="1E293B", size=9)
        pc.alignment = Alignment(horizontal="left", vertical="center", indent=1)

        tc2 = ws.cell(er, TYPE_COL, "GSTR-3B")
        tc2.fill = _fill(C_TYPE_BG); tc2.font = _font(bold=True, color=C_TYPE_FG, size=8)
        tc2.alignment = Alignment(horizontal="center", vertical="center")

        for j, (key, grp, sub) in enumerate(_MOM_3B_COLS):
            col = DATA_START + j
            val = _v(row.get(key))
            dc = ws.cell(er, col, val)
            dc.fill = _fill(bg); dc.font = _font(color="334155", size=8)
            dc.alignment = Alignment(horizontal="right", vertical="center")
            if val is not None:
                dc.number_format = num_fmt

        ws.row_dimensions[er].height = 17

    # ── TOTAL row ────────────────────────────────────────────────────────────
    total_r = ROW_DATA + len(rows)
    tc3 = ws.cell(total_r, PERIOD_COL, "TOTAL")
    tc3.fill = _fill(C_TOT_BG); tc3.font = _font(bold=True, color=C_TOT_FG, size=9)
    tc3.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.cell(total_r, TYPE_COL).fill = _fill(C_TOT_BG)

    for j, (key, grp, sub) in enumerate(_MOM_3B_COLS):
        col = DATA_START + j
        tval = _v(_sum_col(key))
        tvc = ws.cell(total_r, col, tval)
        tvc.fill = _fill(C_TOT_BG); tvc.font = _font(bold=True, color=C_TOT_FG, size=9)
        tvc.alignment = Alignment(horizontal="right", vertical="center")
        if tval is not None:
            tvc.number_format = num_fmt
    ws.row_dimensions[total_r].height = 20
    next_r = total_r + 1

    # ── Annual row ────────────────────────────────────────────────────────────
    if annual_row:
        C_ANN_BG  = "FFF8E1"; C_ANN_FG  = "7B5800"
        C_DIFF_BG = "F9FAFB"; C_NIL_FG  = "1A7A3A"
        C_POS_FG  = "856404"; C_NEG_FG  = "B91C1C"
        C_DIFF_LBL= "6B7280"

        ann_lbl = f"Annual (PDF)  ·  {annual_row.get('period', '')}"
        ac = ws.cell(next_r, PERIOD_COL, ann_lbl)
        ac.fill = _fill(C_ANN_BG); ac.font = _font(bold=True, color=C_ANN_FG, size=9)
        ac.alignment = Alignment(horizontal="left", vertical="center", indent=1)

        atc = ws.cell(next_r, TYPE_COL, annual_row.get("gst_type", "GSTR-3B"))
        atc.fill = _fill(C_ANN_BG); atc.font = _font(bold=True, color=C_ANN_FG, size=8)
        atc.alignment = Alignment(horizontal="center", vertical="center")

        for j, (key, grp, sub) in enumerate(_MOM_3B_COLS):
            col = DATA_START + j
            avc = ws.cell(next_r, col, _v(annual_row.get(key)))
            avc.fill = _fill(C_ANN_BG); avc.font = _font(bold=True, color=C_ANN_FG, size=9)
            avc.alignment = Alignment(horizontal="right", vertical="center")
            avc.number_format = num_fmt

        ws.row_dimensions[next_r].height = 20
        next_r += 1

        # ── Difference row (Annual − MOM Total) ──────────────────────────────
        dc_lbl = ws.cell(next_r, PERIOD_COL, "Difference  (Annual − Total)")
        dc_lbl.fill = _fill(C_DIFF_BG); dc_lbl.font = _font(bold=True, italic=True, color=C_DIFF_LBL, size=9)
        dc_lbl.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        ws.cell(next_r, TYPE_COL).fill = _fill(C_DIFF_BG)

        for j, (key, grp, sub) in enumerate(_MOM_3B_COLS):
            col   = DATA_START + j
            ann_v = float(annual_row.get(key) or 0)
            tot_v = _sum_col(key)
            delta = ann_v - tot_v

            if abs(delta) < 0.01:
                dfc = ws.cell(next_r, col, "Nil")
                dfc.fill = _fill(C_DIFF_BG); dfc.font = _font(italic=True, color=C_NIL_FG, size=8)
                dfc.alignment = Alignment(horizontal="right", vertical="center")
            else:
                dfc = ws.cell(next_r, col, _v(delta))
                dfc.fill = _fill(C_DIFF_BG)
                dfc.font = _font(bold=True, color=C_POS_FG if delta > 0 else C_NEG_FG, size=8)
                dfc.alignment = Alignment(horizontal="right", vertical="center")
                dfc.number_format = num_fmt

        ws.row_dimensions[next_r].height = 19

    # ── Column widths ────────────────────────────────────────────────────────
    ws.column_dimensions[get_column_letter(PERIOD_COL)].width = 18
    ws.column_dimensions[get_column_letter(TYPE_COL)].width   = 10
    for j in range(N_DATA):
        ws.column_dimensions[get_column_letter(DATA_START + j)].width = 14

    ws.freeze_panes = ws.cell(ROW_DATA, DATA_START)
    last_col = get_column_letter(DATA_START + N_DATA - 1)
    ws.auto_filter.ref = f"A{ROW_DATA}:{last_col}{ROW_DATA + len(rows) - 1}"

    wb.save(output_path)
    logger.info("[3B MOM Export] Saved → %s", output_path)


@export_bp.get("/export/mom-3b/excel")
def mom_3b_excel():
    """Generate GSTR-3B MOM Excel with 52-column schema matching the reference format."""
    fmt            = request.args.get("format", "raw")
    annual_file_id = request.args.get("annual_file_id", "").strip()
    if fmt not in ("raw", "l", "cr"):
        fmt = "raw"

    monthly_rows = []
    annual_row   = None
    gstin_found  = ""

    for file_id, file_info in store.files.items():
        if file_info.get("gst_type") != "GSTR-3B":
            continue
        ext = store.get_extracted_data(file_id)
        if not ext:
            continue
        if not gstin_found:
            gstin_found = ext.get("gstin") or ""

        row = _build_3b_ext_row(file_info, ext)

        if file_id == annual_file_id:
            annual_row = row
        else:
            monthly_rows.append(row)

    logger.info("[3B MOM Export] monthly=%d  annual=%s", len(monthly_rows),
                "yes" if annual_row else "no")

    if not monthly_rows:
        return jsonify(error="No GSTR-3B files found in session"), 404

    monthly_rows.sort(key=_fy_sort_key)

    ts            = datetime.now().strftime("%Y%m%d_%H%M%S")
    gstin_part    = (gstin_found or "UNKNOWN").replace(" ", "")
    download_name = f"GSTR3B_{gstin_part}_MOM_{ts}.xlsx"
    out_path      = os.path.join("output", download_name)

    try:
        _generate_3b_mom_excel(
            rows        = monthly_rows,
            annual_row  = annual_row,
            fmt         = fmt,
            gstin       = gstin_found,
            output_path = out_path,
        )
    except Exception as exc:
        logger.exception("[3B MOM Export] Generation failed: %s", exc)
        return jsonify(success=False, error=str(exc)), 500

    return send_file(
        out_path,
        as_attachment=True,
        download_name=download_name,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _generate_9_excel(all_files_data, fmt, output_path):
    """
    Generate GSTR-9 Excel workbook matching the reference format EXACTLY.
    all_files_data: list of (file_info, extracted_data) tuples.
    Creates one sheet per GSTR-9 file.
    """
    if fmt == "l":
        divisor  = 1e5
        fmt_note = "Lakhs (÷ 1,00,000)"
    elif fmt == "cr":
        divisor  = 1e7
        fmt_note = "Crores (÷ 1,00,00,000)"
    else:
        divisor  = 1.0
        fmt_note = "Raw (₹)"

    def _v(raw):
        if raw is None: return None
        try: return round(float(raw) / divisor, 2)
        except: return None

    def gv(d, key):
        return _v(d.get(key))

    # ── Colour palette (exact hex from reference) ────────────────────────────
    C_TITLE_BG = "0F172A";  C_HEADER_BG  = "0D1B2A"
    C_PART_BG  = "1E293B";  C_SEC_BG     = "263145"
    C_DATA_BG  = "0B1526";  C_ITC_BG     = "172032"
    C_SUB_BG   = "1C2B3A";  C_TOT_BG     = "14532D"
    C_P4_HDR   = "1E3A5F";  C_P4_DATA    = "0F2337"
    C_FOOT_BG  = "0A0F1A"
    C_WHITE    = "FFFFFF";  C_SLATE      = "94A3B8"
    C_LSLATE   = "CBD5E1";  C_AMBER      = "FCD34D"
    C_BLUE     = "93C5FD";  C_VIOLET     = "C4B5FD"
    C_GHDR     = "6EE7B7";  C_RED        = "F87171"
    C_GVAL     = "4ADE80";  C_FOOT_FG    = "475569"
    C_BORDER   = "334155"

    def fill(c):  return PatternFill("solid", fgColor=c)
    def fnt(bold=False, italic=False, color=C_WHITE, size=9):
        return Font(name="Calibri", bold=bold, italic=italic, color=color, size=size)
    def aln(h="left", v="center", wrap=False):
        return Alignment(horizontal=h, vertical=v, wrap_text=wrap)
    def bdr():
        s = Side(style="thin", color=C_BORDER)
        return Border(left=s, right=s, top=s, bottom=s)
    NUM = "#,##0.00"

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    for file_info, d in all_files_data:
        period     = file_info.get("period") or "Annual"
        sheet_name = f"GSTR-9 {period}"[:31]
        ws         = wb.create_sheet(sheet_name)
        ws.sheet_view.showGridLines = False

        # Column widths
        for col_letter, w in [("A",6),("B",52),("C",16),("D",18),("E",16),("F",16),("G",16),("H",14),("I",14)]:
            ws.column_dimensions[col_letter].width = w

        # ── Cell helpers (capture ws via closure) ────────────────────────────
        def _set(r, c, val, bg, bold=False, italic=False, color=C_WHITE,
                 size=9, h="left", v="center", wrap=False, num_fmt=None, is_red=False, is_green=False):
            cell          = ws.cell(r, c, val)
            cell.fill     = fill(bg)
            fc            = C_RED if is_red else (C_GVAL if is_green else color)
            cell.font     = fnt(bold=bold, italic=italic, color=fc, size=size)
            cell.alignment= aln(h, v, wrap)
            cell.border   = bdr()
            if num_fmt and val is not None:
                cell.number_format = num_fmt
            return cell

        def _merge_row(r, text, bg, bold=True, color=C_WHITE, size=9, height=15.0, wrap=False):
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=9)
            _set(r, 1, text, bg, bold=bold, color=color, size=size, h="left", v="center", wrap=wrap)
            ws.row_dimensions[r].height = height
            for c in range(2, 10):
                ws.cell(r, c).fill   = fill(bg)
                ws.cell(r, c).border = bdr()

        def _part_hdr(r, text):
            _merge_row(r, text, C_PART_BG, bold=True,  color=C_WHITE,  height=15.0)

        def _sec_hdr(r, text):
            _merge_row(r, text, C_SEC_BG,  bold=False, color=C_SLATE,  height=13.95, wrap=True)

        def _data_row(r, sr, desc, type_lbl, v5, bg=C_DATA_BG,
                      is_sub=False, is_tot=False, is_red=False):
            """5-value row: (taxable, cgst, sgst, igst, cess)."""
            ws.row_dimensions[r].height = 13.05
            use_bg  = C_TOT_BG if is_tot else (C_SUB_BG if is_sub else bg)
            bold    = is_tot or is_sub
            sr_col  = C_WHITE if bold else C_SLATE
            desc_col= C_WHITE if bold else C_LSLATE
            v_col   = C_RED if is_red else C_WHITE
            _set(r,1,sr,       use_bg,bold=bold,color=sr_col,  h="left")
            _set(r,2,desc,     use_bg,bold=bold,color=desc_col, h="left",  wrap=True)
            _set(r,3,type_lbl or None, use_bg,color=C_SLATE,   h="center")
            col_colors = [C_AMBER,C_BLUE,C_VIOLET,C_GHDR,C_SLATE]
            for ci,(val,cc) in enumerate(zip(v5,col_colors),start=4):
                cell = _set(r,ci,val,use_bg,bold=bold,color=v_col if not bold else C_WHITE,
                            h="right", num_fmt=NUM if val is not None else None)

        def _itc_row(r, sr, desc, type_lbl, v4, bg=C_DATA_BG,
                     is_sub=False, is_tot=False, red_idx=None, grn_idx=None):
            """ITC row: D=blank, E-H=(cgst,sgst,igst,cess)."""
            ws.row_dimensions[r].height = 13.05
            use_bg  = C_TOT_BG if is_tot else (C_SUB_BG if is_sub else bg)
            bold    = is_tot or is_sub
            _set(r,1,sr,  use_bg,bold=bold,color=C_WHITE if bold else C_SLATE,h="left")
            _set(r,2,desc,use_bg,bold=bold,color=C_WHITE if bold else C_LSLATE,h="left",wrap=True)
            _set(r,3,type_lbl or None,use_bg,color=C_SLATE,h="center")
            _set(r,4,None,use_bg)   # D col blank for ITC rows
            for ci,(val,idx) in enumerate(zip(v4,range(4)),start=5):
                is_r = (not bold) and red_idx and idx in red_idx
                is_g = (not bold) and grn_idx and idx in grn_idx
                _set(r,ci,val,use_bg,bold=bold,color=C_WHITE,
                     h="right",num_fmt=NUM if val is not None else None,
                     is_red=is_r,is_green=is_g)

        def _p4_row(r, sr, desc, v6, bg=C_P4_DATA):
            """Part IV row: (payable, cash, itc_cgst, itc_sgst, itc_igst, itc_cess)."""
            ws.row_dimensions[r].height = 13.05
            _set(r,1,sr,  bg,bold=True, color=C_SLATE, h="left")
            _set(r,2,desc,bg,bold=False,color=C_WHITE, h="left")
            _set(r,3,None,bg)
            col_colors=[C_AMBER,C_BLUE,C_VIOLET,C_GHDR,C_WHITE,C_SLATE]
            for ci,(val,cc) in enumerate(zip(v6,col_colors),start=4):
                _set(r,ci,val,bg,color=C_WHITE,h="right",num_fmt=NUM if val is not None else None)

        # ── Row 1: Title ─────────────────────────────────────────────────────
        row = 1
        _merge_row(row, f"GSTR-9 Annual Return · {period}  [{fmt_note}]",
                   C_TITLE_BG, bold=True, color=C_WHITE, size=11, height=22.05)
        row += 1

        # ── Row 2: Column header ─────────────────────────────────────────────
        ws.row_dimensions[row].height = 16.05
        for ci,(label,color,align_h) in enumerate([
            ("Sr",             C_SLATE,  "left"),
            ("Description",    C_SLATE,  "left"),
            ("Type",           C_SLATE,  "left"),
            ("Taxable Value",  C_AMBER,  "right"),
            ("Central Tax",    C_BLUE,   "right"),
            ("State/UT Tax",   C_VIOLET, "right"),
            ("Integrated Tax", C_GHDR,   "right"),
            ("Cess",           C_SLATE,  "right"),
            ("",               C_SLATE,  "right"),  # col I — used by Part IV only
        ], start=1):
            _set(row,ci,label,C_HEADER_BG,bold=True,color=color,h=align_h)
        row += 1

        # ── PART II ──────────────────────────────────────────────────────────
        _part_hdr(row, "Part II — Details of Outward & Inward Supplies"); row += 1
        _sec_hdr(row,  "4. Details of advances, inward & outward supplies on which tax is payable"); row += 1

        SEC4 = [
            ("A","B2C Supplies (Unregistered persons)",                              "4A_B2C",             False,False,False),
            ("B","B2B Supplies (Registered persons)",                                "4B_B2B",             False,False,False),
            ("C","Zero rated supply (Export) with payment of tax",                   "4C_Export_WithTax",  False,False,False),
            ("D","Supply to SEZs with payment of tax",                               "4D_SEZ_WithTax",     False,False,False),
            ("E","Deemed Exports",                                                    "4E_DeemedExports",   False,False,False),
            ("F","Advances on which tax has been paid but invoice not issued",       "4F_Advances",        False,False,False),
            ("G","Inward supplies liable to reverse charge (RCM)",                  "4G_RCM_Inward",      False,False,False),
            ("H","Sub-total (A to G above)",                                         "4H_SubTotal_AtoG",   True, False,False),
            ("I","Credit Notes issued in respect of B to E above (−)",              "4I_CreditNotes",     False,False,True),
            ("J","Debit Notes issued in respect of B to E above (+)",               "4J_DebitNotes",      False,False,False),
            ("K","Supplies / tax declared through Amendments (+)",                  "4K_Amendments_Plus", False,False,False),
            ("L","Supplies / tax reduced through Amendments (−)",                   "4L_Amendments_Minus",False,False,True),
            ("M","Sub-total (I to L above)",                                         "4M_SubTotal_ItoL",   True, False,False),
            ("N","Supplies and advances on which tax is to be paid (H + M above)", "4N_Net_TaxPayable",  False,True, False),
        ]
        for sr,desc,pfx,is_sub,is_tot,is_red in SEC4:
            v5 = (gv(d,f"{pfx}_TaxableValue"),gv(d,f"{pfx}_CGST"),
                  gv(d,f"{pfx}_SGST"),gv(d,f"{pfx}_IGST"),gv(d,f"{pfx}_Cess"))
            _data_row(row,sr,desc,"",v5,is_sub=is_sub,is_tot=is_tot,is_red=is_red)
            row += 1

        _sec_hdr(row, "5. Details of Outward Supplies on which tax is not payable"); row += 1

        for sr,desc,pfx in [
            ("A","Zero rated supply (Export) without payment of tax",    "5A_Export_WithoutTax"),
            ("B","Supply to SEZs without payment of tax",                "5B_SEZ_WithoutTax"),
            ("C","Supplies on which tax to be paid by recipient (RCM)", "5C_RCM_Recipient"),
            ("D","Exempted",                                              "5D_Exempted"),
            ("E","Nil Rated",                                             "5E_NilRated"),
            ("F","Non-GST supply",                                        "5F_NonGST"),
        ]:
            _data_row(row,sr,desc,"",(gv(d,f"{pfx}_TaxableValue"),None,None,None,None)); row += 1

        # 5G sub-total A–F
        _data_row(row,"G","Sub-total (A to F above)","",
                  (gv(d,"5G_SubTotal_AtoF_TaxableValue"),None,None,None,None),is_sub=True); row += 1

        # 5H–5L: new rows added in updated GSTR-9 format
        for sr,desc,pfx in [
            ("H","Credit Notes issued in respect of A to F above (−)",       "5H_CreditNotes"),
            ("I","Debit Notes issued in respect of A to F above (+)",         "5I_DebitNotes"),
            ("J","Supplies / tax declared through Amendments (+)",            "5J_Amendments_Plus"),
            ("K","Supplies / tax reduced through Amendments (−)",             "5K_Amendments_Minus"),
            ("L","Sub-total (H to K above)",                                  "5L_SubTotal_HtoK"),
        ]:
            _data_row(row,sr,desc,"",(gv(d,f"{pfx}_TaxableValue"),None,None,None,None)); row += 1

        # 5M total non-taxable turnover
        _data_row(row,"M","Total Non-Taxable Turnover (G + L above)","",
                  (gv(d,"5M_Turnover_NonTaxable_TaxableValue"),None,None,None,None),is_sub=True); row += 1

        # 5N total turnover (green row, all 5 cols)
        _data_row(row,"N","Total Turnover (including advances) (4N + 5M − 4G above)","",
                  (gv(d,"5N_TotalTurnover_TaxableValue"),gv(d,"5N_TotalTurnover_CGST"),
                   gv(d,"5N_TotalTurnover_SGST"),gv(d,"5N_TotalTurnover_IGST"),gv(d,"5N_TotalTurnover_Cess")),
                  is_tot=True)
        row += 1

        # ── PART III ─────────────────────────────────────────────────────────
        _part_hdr(row, "Part III — Details of ITC for the Financial Year"); row += 1
        _sec_hdr(row,  "6. Details of ITC availed during the financial year"); row += 1

        # 6A
        _itc_row(row,"A","Total ITC availed through FORM GSTR-3B (sum of Table 4A of GSTR-3B)","",
                 (gv(d,"6A_ITC_GSTR3B_CGST"),gv(d,"6A_ITC_GSTR3B_SGST"),
                  gv(d,"6A_ITC_GSTR3B_IGST"),gv(d,"6A_ITC_GSTR3B_Cess")))
        row += 1
        # 6A1: ITC from preceding FY availed in April–September
        _itc_row(row,"A1","ITC from preceding FY availed in April–September (other than reclaim of reversal)","",
                 (gv(d,"6A1_PrecedingFY_ITC_CGST"),gv(d,"6A1_PrecedingFY_ITC_SGST"),
                  gv(d,"6A1_PrecedingFY_ITC_IGST"),gv(d,"6A1_PrecedingFY_ITC_Cess")),bg=C_ITC_BG)
        row += 1
        # 6A2: Net ITC for current FY (A − A1)
        _itc_row(row,"A2","Net ITC availed for current financial year (A − A1)","",
                 (gv(d,"6A2_Net_ITC_CGST"),gv(d,"6A2_Net_ITC_SGST"),
                  gv(d,"6A2_Net_ITC_IGST"),gv(d,"6A2_Net_ITC_Cess")),bg=C_ITC_BG)
        row += 1

        # 6B — 3 sub-rows
        for i,(tl,sfx) in enumerate([("Inputs","6B_Inputs_Inputs"),("Capital Goods","6B_Inputs_CapGoods"),("Input Services","6B_Inputs_InputSvcs")]):
            sr_lbl   = "B" if i==0 else ""
            desc_lbl = "Inward supplies (other than imports, incl. services from SEZs)" if i==0 else ""
            _itc_row(row,sr_lbl,desc_lbl,tl,
                     (gv(d,f"{sfx}_CGST"),gv(d,f"{sfx}_SGST"),gv(d,f"{sfx}_IGST"),gv(d,f"{sfx}_Cess")),
                     bg=C_ITC_BG)
            row += 1

        # 6C — 3 sub-rows (no parser data)
        for i,tl in enumerate(["Inputs","Capital Goods","Input Services"]):
            _itc_row(row,"C" if i==0 else "",
                     "Inward supplies from unregistered persons liable to RCM" if i==0 else "",
                     tl,(None,None,None,None),bg=C_ITC_BG)
            row += 1

        # 6D — 3 sub-rows (no parser data)
        for i,tl in enumerate(["Inputs","Capital Goods","Input Services"]):
            _itc_row(row,"D" if i==0 else "",
                     "Inward supplies from registered persons liable to RCM" if i==0 else "",
                     tl,(None,None,None,None),bg=C_ITC_BG)
            row += 1

        # 6E — 2 sub-rows
        for i,(tl,sfx) in enumerate([("Inputs","6E_Import_Goods_Inputs"),("Capital Goods",None)]):
            v4 = (gv(d,f"{sfx}_CGST"),gv(d,f"{sfx}_SGST"),gv(d,f"{sfx}_IGST"),gv(d,f"{sfx}_Cess")) if sfx else (None,None,None,None)
            _itc_row(row,"E" if i==0 else "",
                     "Import of goods (including supplies from SEZs)" if i==0 else "",
                     tl,v4,bg=C_ITC_BG)
            row += 1

        # 6F, 6G, 6H
        _itc_row(row,"F","Import of services (excluding inward supplies from SEZs)","",
                 (gv(d,"6F_Import_Svcs_CGST"),gv(d,"6F_Import_Svcs_SGST"),gv(d,"6F_Import_Svcs_IGST"),gv(d,"6F_Import_Svcs_Cess")))
        row += 1
        _itc_row(row,"G","Input Tax Credit received from ISD","",
                 (gv(d,"6G_ISD_CGST"),gv(d,"6G_ISD_SGST"),gv(d,"6G_ISD_IGST"),gv(d,"6G_ISD_Cess")))
        row += 1
        _itc_row(row,"H","Amount of ITC reclaimed (other than B above) under the provisions of the Act","",
                 (None,None,None,None))
        row += 1

        # 6I subtotal, 6J difference
        _itc_row(row,"I","Sub-total (B to H above)","",
                 (gv(d,"6I_SubTotal_BtoH_CGST"),gv(d,"6I_SubTotal_BtoH_SGST"),
                  gv(d,"6I_SubTotal_BtoH_IGST"),gv(d,"6I_SubTotal_BtoH_Cess")),is_sub=True)
        row += 1
        _itc_row(row,"J","Difference (I − A above)","",
                 (gv(d,"6J_Difference_IminusA_CGST"),gv(d,"6J_Difference_IminusA_SGST"),
                  gv(d,"6J_Difference_IminusA_IGST"),gv(d,"6J_Difference_IminusA_Cess")))
        row += 1

        # 6K, 6L, 6M (TRAN credits — no parser data)
        for sr_l,desc_l in [("K","Transitional credit through TRAN-1 (filed on or before 27-12-2017)"),
                             ("L","Transitional credit through TRAN-2"),
                             ("M","Any other ITC availed but not specified above")]:
            _itc_row(row,sr_l,desc_l,"",(None,None,None,None)); row += 1

        # 6N subtotal K-M, 6O total
        _itc_row(row,"N","Sub-total (K to M above)","",(None,None,None,None),is_sub=True); row += 1
        _itc_row(row,"O","Total ITC availed (I + N above)","",
                 (gv(d,"6O_TotalITC_CGST"),gv(d,"6O_TotalITC_SGST"),
                  gv(d,"6O_TotalITC_IGST"),gv(d,"6O_TotalITC_Cess")),is_tot=True)
        row += 1

        _sec_hdr(row, "7. Details of ITC Reversed and Ineligible ITC for the financial year"); row += 1

        SEC7 = [
            ("A", "As per Rule 37 (payment not made within 180 days)",            "7A_Rule37"),
            ("A1","As per Rule 37A (CIRP)",                                        "7A1_Rule37A"),
            ("A2","As per Rule 38 (ITC in respect of inputs held in stock)",       "7A2_Rule38"),
            ("B", "As per Rule 39 (ISD reversal)",                                 "7B_Rule39"),
            ("C", "As per Rule 42 (common credits — inputs and services)",         "7C_Rule42"),
            ("D", "As per Rule 43 (capital goods)",                                "7D_Rule43"),
            ("E", "As per section 17(5) (blocked credits)",                        "7E_Sec17_5"),
            ("F", "Reversal of TRAN-1 credit",                                     None),
            ("G", "Reversal of TRAN-2 credit",                                     None),
            ("H1","Other reversals (please specify)",                              "7H1_OtherReversal"),
        ]
        for sr,desc,pfx in SEC7:
            v4 = (gv(d,f"{pfx}_CGST"),gv(d,f"{pfx}_SGST"),gv(d,f"{pfx}_IGST"),gv(d,f"{pfx}_Cess")) if pfx else (None,None,None,None)
            _itc_row(row,sr,desc,"",v4); row += 1

        _itc_row(row,"I","Total ITC Reversed (Sum of A to H above)","",
                 (gv(d,"7I_Total_ITC_Reversed_CGST"),gv(d,"7I_Total_ITC_Reversed_SGST"),
                  gv(d,"7I_Total_ITC_Reversed_IGST"),gv(d,"7I_Total_ITC_Reversed_Cess")),is_sub=True)
        row += 1
        _itc_row(row,"J","Net ITC Available for Utilization (6O − 7I)","",
                 (gv(d,"7J_NetITC_Utilizable_CGST"),gv(d,"7J_NetITC_Utilizable_SGST"),
                  gv(d,"7J_NetITC_Utilizable_IGST"),gv(d,"7J_NetITC_Utilizable_Cess")),is_tot=True)
        row += 1

        _sec_hdr(row, "8. Other ITC related information"); row += 1
        for sr,desc,pfx in [
            ("A", "ITC as per GSTR-2A (Eligible ITC only)",                                   "8A_GSTR2A_ITC"),
            ("B", "ITC as per sum of 6(B) and 6(H) above",                                    "8B_ITC_6B_6H"),
            ("C", "ITC on inward supplies availed for previous financial year",                "8C_NextFY_ITC"),
            ("D", "Difference [A − (B + C)]",                                                  "8D_Difference"),
            ("E", "ITC available but not availed (out of D)",                                  "8E_Available_NotAvailed"),
            ("F", "ITC available but ineligible (out of D)",                                   "8F_Available_Ineligible"),
            ("G", "IGST paid on import of goods (including supplies from SEZs)",               "8G_IGST_Import_Paid"),
            ("H", "IGST credit availed on import of goods in current FY (as per 6E above)",   "8H_IGST_Import_Availed"),
            ("H1","IGST credit availed on import of goods in next financial year",             "8H1_IGST_Import_NextFY"),
            ("I", "Difference (G − H − H1)",                                                   "8I_Diff_GH"),
            ("J", "ITC available on import of goods but not availed",                          "8J_NotAvailed_Import"),
            ("K", "Total ITC to be lapsed in current financial year (E + F + J)",             "8K_ITC_To_Lapse"),
        ]:
            v4 = (gv(d,f"{pfx}_CGST"),gv(d,f"{pfx}_SGST"),gv(d,f"{pfx}_IGST"),gv(d,f"{pfx}_Cess"))
            _itc_row(row,sr,desc,"",v4); row += 1

        # ── PART IV ──────────────────────────────────────────────────────────
        _part_hdr(row, "Part IV — Details of Tax Paid as Declared in Returns"); row += 1

        # Part IV column sub-header (different column labels)
        ws.row_dimensions[row].height = 13.95
        for ci,(label,color,align_h) in enumerate([
            ("Sr",          C_SLATE,  "left"),
            ("Description", C_SLATE,  "left"),
            ("",            C_SLATE,  "left"),
            ("Tax Payable", C_AMBER,  "right"),
            ("Cash Paid",   C_BLUE,   "right"),
            ("ITC — CGST",  C_VIOLET, "right"),
            ("ITC — SGST",  C_GHDR,   "right"),
            ("ITC — IGST",  C_WHITE,  "right"),
            ("ITC — Cess",  C_SLATE,  "right"),
        ], start=1):
            _set(row,ci,label or None,C_P4_HDR,bold=True,color=color,h=align_h)
        row += 1

        P4 = [
            ("A","Integrated Tax", (gv(d,"9A_IGST_Payable"),gv(d,"9A_IGST_Cash"),gv(d,"9A_IGST_ITC_CGST"),gv(d,"9A_IGST_ITC_SGST"),gv(d,"9A_IGST_ITC_IGST"),gv(d,"9A_IGST_ITC_Cess"))),
            ("B","Central Tax",    (gv(d,"9B_CGST_Payable"),gv(d,"9B_CGST_Cash"),gv(d,"9B_CGST_ITC_CGST"),None,gv(d,"9B_CGST_ITC_IGST"),None)),
            ("C","State / UT Tax", (gv(d,"9C_SGST_Payable"),gv(d,"9C_SGST_Cash"),None,gv(d,"9C_SGST_ITC_SGST"),gv(d,"9C_SGST_ITC_IGST"),None)),
            ("D","Cess",           (gv(d,"9D_Cess_Payable"),gv(d,"9D_Cess_Cash"),None,None,None,gv(d,"9D_Cess_ITC_Cess"))),
            ("E","Interest",       (gv(d,"9E_Interest_Payable"),gv(d,"9E_Interest_Cash"),None,None,None,None)),
            ("F","Late Fees",      (gv(d,"9F_LateFee_Payable"),gv(d,"9F_LateFee_Cash"),None,None,None,None)),
            ("G","Penalty",        (gv(d,"9G_Penalty_Payable"),gv(d,"9G_Penalty_Cash"),None,None,None,None)),
            ("H","Other",          (gv(d,"9H_Other_Payable"),gv(d,"9H_Other_Cash"),None,None,None,None)),
        ]
        for sr,desc,v6 in P4:
            _p4_row(row,sr,desc,v6); row += 1

        # ── PART V ───────────────────────────────────────────────────────────
        _part_hdr(row, "Part V — Previous Financial Year Transactions"); row += 1

        for sr,desc,is_red in [
            ("10","Supplies / tax declared through Amendments (+) (net of debit notes)",False),
            ("11","Supplies / tax reduced through Amendments (−) (net of credit notes)",True),
            ("12","Reversal of ITC availed during previous financial year",             False),
            ("13","ITC availed for the previous financial year",                        False),
        ]:
            _data_row(row,sr,desc,"",(None,None,None,None,None),is_red=is_red); row += 1

        # Table 14: Differential tax paid on account of Table 10 & 11 declarations
        _sec_hdr(row, "14. Differential tax paid on account of declaration in Table 10 & 11"); row += 1
        for sr,desc,pfx in [
            ("A","Integrated Tax", "14A_IGST"),
            ("B","Central Tax",    "14B_CGST"),
            ("C","State / UT Tax", "14C_SGST"),
            ("D","Cess",           "14D_Cess"),
            ("E","Interest",       "14E_Interest"),
        ]:
            _p4_row(row,sr,desc,(gv(d,f"{pfx}_Payable"),gv(d,f"{pfx}_Cash"),None,None,None,None)); row += 1

        # Total turnover — green row
        _data_row(row,"","Total Turnover (5N + 10 − 11)","",
                  (gv(d,"5N_TotalTurnover_TaxableValue"),gv(d,"5N_TotalTurnover_CGST"),
                   gv(d,"5N_TotalTurnover_SGST"),gv(d,"5N_TotalTurnover_IGST"),gv(d,"5N_TotalTurnover_Cess")),
                  is_tot=True)
        row += 1

        # ── PART VI ──────────────────────────────────────────────────────────
        _part_hdr(row, "Part VI — Other Information"); row += 1

        # Table 15: Demands and Refunds
        _sec_hdr(row, "15. Details of Demands and Refunds"); row += 1
        for sr,desc,pfx in [
            ("A","Demand of taxes",                                         "15A_Tax_Demands"),
            ("B","Taxes paid in full against the demands",                  "15B_Tax_Demands_Paid"),
            ("C","Taxes paid in partial against the demands",               "15C_Tax_Demands_Partial"),
            ("D","Taxes and interest, refund claimed",                      "15D_Refunds_Claimed"),
            ("E","Taxes and interest, refund sanctioned",                   "15E_Refunds_Sanctioned"),
            ("F","Taxes and interest, refund rejected",                     "15F_Refunds_Rejected"),
            ("G","Taxes and interest, refund pending",                      "15G_Refunds_Pending"),
        ]:
            v4 = (gv(d,f"{pfx}_CGST"),gv(d,f"{pfx}_SGST"),gv(d,f"{pfx}_IGST"),gv(d,f"{pfx}_Cess"))
            _itc_row(row,sr,desc,"",v4); row += 1

        # Table 16: Composition / Job Work / Goods on Approval
        _sec_hdr(row, "16. Information on supplies received from composition taxpayers, deemed supply u/s 143 and goods sent on approval basis"); row += 1
        for sr,desc,pfx in [
            ("A","Supplies received from composition taxpayers",            "16A_Composition_Inward"),
            ("B","Deemed supply u/s 143 (job work)",                        "16B_JobWork_DeemedSupply"),
            ("C","Goods sent on approval basis but not returned",           "16C_GoodsOnApproval"),
        ]:
            v5 = (gv(d,f"{pfx}_TaxableValue"),None,None,gv(d,f"{pfx}_Tax"),None)
            _data_row(row,sr,desc,"",v5); row += 1

        # Table 19: Late Fee
        _sec_hdr(row, "19. Late Fee payable and paid"); row += 1
        for sr,desc,pfx in [
            ("A","Central Tax",    "19A_CentralTax_LateFee"),
            ("B","State / UT Tax", "19B_StateTax_LateFee"),
        ]:
            _p4_row(row,sr,desc,(gv(d,f"{pfx}_Payable"),gv(d,f"{pfx}_Paid"),None,None,None,None)); row += 1

        # ── Footer ───────────────────────────────────────────────────────────
        now_str = datetime.now().strftime("%d %b %Y %H:%M")
        _merge_row(row, f"All amounts in ₹ · {fmt_note}  |  Generated {now_str}",
                   C_FOOT_BG, bold=False, color=C_FOOT_FG, size=8, height=13.05)
        # Override alignment to right
        ws.cell(row, 1).alignment = aln("right", "center")

        # Freeze rows 1-2 (title + header) — matches reference (ySplit=2)
        ws.freeze_panes = "A3"

    wb.save(output_path)
    logger.info("[GSTR-9 Export] Saved → %s  (%d sheet(s))", output_path, len(all_files_data))


@export_bp.get("/export/mom-9/excel")
def mom_9_excel():
    """Generate GSTR-9 Excel matching reference format exactly (one sheet per year)."""
    fmt = request.args.get("format", "raw")
    if fmt not in ("raw", "l", "cr"):
        fmt = "raw"

    files_data  = []
    gstin_found = ""

    for file_id, file_info in store.files.items():
        if file_info.get("gst_type") != "GSTR-9":
            continue
        ext = store.get_extracted_data(file_id)
        if not ext:
            continue
        if not gstin_found:
            gstin_found = ext.get("gstin") or ""
        files_data.append((file_info, ext))

    if not files_data:
        return jsonify(error="No GSTR-9 files found in session"), 404

    files_data.sort(key=lambda fd: _fy_sort_key({"period": fd[0].get("period") or fd[1].get("period") or ""}))

    ts            = datetime.now().strftime("%Y%m%d_%H%M%S")
    gstin_part    = (gstin_found or "UNKNOWN").replace(" ", "")
    download_name = f"GSTR9_{gstin_part}_{ts}.xlsx"
    out_path      = os.path.join("output", download_name)

    try:
        _generate_9_excel(files_data, fmt, out_path)
    except Exception as exc:
        logger.exception("[GSTR-9 Export] Generation failed: %s", exc)
        return jsonify(success=False, error=str(exc)), 500

    return send_file(
        out_path,
        as_attachment=True,
        download_name=download_name,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@export_bp.get("/export/risk/excel")
def risk_excel():
    """Export the linked, auditable risk-ratio workbook.

    Every ratio is a live Excel formula pointing back to the GSTR-1 / GSTR-3B
    source cells (which are themselves =SUM of the monthly figures), so nothing
    is hard-coded and each value traces to its origin. See
    services/risk_workbook.py for the sheet structure.
    """
    if not store.files:
        return jsonify(error="No files in session"), 404

    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"GST_Risk_Report_{ts}.xlsx"
    out  = os.path.join("output", name)

    try:
        from services.risk_workbook import build_linked_workbook
        build_linked_workbook(store, out)
    except Exception as exc:
        logger.exception("Risk export failed: %s", exc)
        return jsonify(error=str(exc)), 500

    return send_file(out, as_attachment=True, download_name=name,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@export_bp.get("/export/anomalies/excel")
def anomalies_excel():
    """Export the anomaly matrix + flagged-items list (see services/anomaly_workbook.py)."""
    if not store.files:
        return jsonify(error="No files in session"), 404

    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"GST_Anomaly_Report_{ts}.xlsx"
    out  = os.path.join("output", name)

    try:
        from services.anomaly_workbook import build_anomaly_workbook
        build_anomaly_workbook(store, out)
    except Exception as exc:
        logger.exception("Anomaly export failed: %s", exc)
        return jsonify(error=str(exc)), 500

    return send_file(out, as_attachment=True, download_name=name,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
