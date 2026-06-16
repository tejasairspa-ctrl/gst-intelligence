"""
Export Service — Generates Excel and PDF CA-format reports.
All data sourced exclusively from extracted/analytics dicts.
"""
import copy
import io
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Excel Export ──────────────────────────────────────────────────────────────

def export_excel(extracted_data: Dict, analytics: Dict, output_path: str) -> str:
    """
    Create a structured Excel workbook with multiple sheets.
    Returns the file path.
    """
    try:
        import openpyxl
        from openpyxl.styles import (
            Alignment, Border, Font, PatternFill, Side,
        )
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise RuntimeError("openpyxl not installed. Run: pip install openpyxl")

    wb = openpyxl.Workbook()

    # ── Colour palette ────────────────────────────────────────────────────────
    BLUE_DARK   = "1E3A5F"
    BLUE_MID    = "2E6DA4"
    BLUE_LIGHT  = "D6E4F0"
    GREEN_LIGHT = "E2EFDA"
    ORANGE      = "F4B942"
    WHITE       = "FFFFFF"
    GREY_LIGHT  = "F5F5F5"

    def header_style(ws, row, col, text, bold=True, bg=BLUE_DARK, fg=WHITE, size=11):
        cell = ws.cell(row=row, column=col, value=text)
        cell.font = Font(bold=bold, color=fg, size=size)
        cell.fill = PatternFill("solid", fgColor=bg)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        return cell

    def data_cell(ws, row, col, value, number_format=None, bg=None, bold=False):
        cell = ws.cell(row=row, column=col, value=value)
        if number_format:
            cell.number_format = number_format
        if bg:
            cell.fill = PatternFill("solid", fgColor=bg)
        if bold:
            cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="right" if isinstance(value, (int, float)) else "left")
        return cell

    def na_cell(ws, row, col):
        cell = ws.cell(row=row, column=col, value="Data not available")
        cell.font = Font(italic=True, color="888888")
        cell.alignment = Alignment(horizontal="left")
        return cell

    def set_col_widths(ws, widths):
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w

    now = datetime.now().strftime("%d-%b-%Y %H:%M")
    form_type = extracted_data.get("form_type", "GST")
    period    = extracted_data.get("period", "")
    gstin     = extracted_data.get("gstin", "")
    entity    = extracted_data.get("legal_name", "")

    # ═══════════════════════════════════════════════════════════════════════════
    # SHEET 1 — Summary
    # ═══════════════════════════════════════════════════════════════════════════
    ws1 = wb.active
    ws1.title = "Summary"

    ws1.merge_cells("A1:D1")
    t = ws1["A1"]
    t.value = f"GST Intelligence Report — {form_type}"
    t.font = Font(bold=True, size=14, color=WHITE)
    t.fill = PatternFill("solid", fgColor=BLUE_DARK)
    t.alignment = Alignment(horizontal="center", vertical="center")
    ws1.row_dimensions[1].height = 30

    meta = [
        ("Form Type", form_type),
        ("Period", period or "N/A"),
        ("GSTIN", gstin or "N/A"),
        ("Entity Name", entity or "N/A"),
        ("Report Generated", now),
    ]
    for i, (k, v) in enumerate(meta, 3):
        ws1.cell(row=i, column=1, value=k).font = Font(bold=True)
        ws1.cell(row=i, column=2, value=v)

    ws1.cell(row=9, column=1, value="KEY PERFORMANCE INDICATORS").font = Font(bold=True, size=12)

    header_style(ws1, 10, 1, "Metric")
    header_style(ws1, 10, 2, "Value (₹)")
    header_style(ws1, 10, 3, "Status")

    kpis: List[Dict] = analytics.get("kpis", [])
    for i, kpi in enumerate(kpis, 11):
        ws1.cell(row=i, column=1, value=kpi["label"])
        if kpi["available"]:
            cell = data_cell(ws1, i, 2, kpi["value"], number_format='₹#,##0.00')
            ws1.cell(row=i, column=3, value="✓ Available")
            if i % 2 == 0:
                ws1["A" + str(i)].fill = PatternFill("solid", fgColor=GREY_LIGHT)
                cell.fill = PatternFill("solid", fgColor=GREY_LIGHT)
        else:
            na_cell(ws1, i, 2)
            ws1.cell(row=i, column=3, value="Not in document").font = Font(italic=True, color="888888")

    set_col_widths(ws1, [40, 20, 20, 20])

    # ═══════════════════════════════════════════════════════════════════════════
    # SHEET 2 — Ratio Analysis
    # ═══════════════════════════════════════════════════════════════════════════
    ws2 = wb.create_sheet("Ratio Analysis")

    ws2.merge_cells("A1:E1")
    t2 = ws2["A1"]
    t2.value = "Ratio Analysis"
    t2.font = Font(bold=True, size=13, color=WHITE)
    t2.fill = PatternFill("solid", fgColor=BLUE_MID)
    t2.alignment = Alignment(horizontal="center")
    ws2.row_dimensions[1].height = 25

    headers = ["Ratio Name", "Value", "Unit", "Benchmark", "Interpretation"]
    for j, h in enumerate(headers, 1):
        header_style(ws2, 2, j, h, bg=BLUE_LIGHT, fg="000000")

    ratios: List[Dict] = analytics.get("ratios", [])
    for i, r in enumerate(ratios, 3):
        ws2.cell(row=i, column=1, value=r["name"])
        if r["available"]:
            ws2.cell(row=i, column=2, value=r["value"])
        else:
            na_cell(ws2, i, 2)
        ws2.cell(row=i, column=3, value=r.get("unit", "%"))
        ws2.cell(row=i, column=4, value=r.get("benchmark") or "")
        ws2.cell(row=i, column=5, value=r.get("interpretation") or "")
        if i % 2 == 0:
            for col in range(1, 6):
                ws2.cell(row=i, column=col).fill = PatternFill("solid", fgColor=GREY_LIGHT)

    set_col_widths(ws2, [50, 12, 8, 35, 45])

    # ═══════════════════════════════════════════════════════════════════════════
    # SHEET 3 — Insights
    # ═══════════════════════════════════════════════════════════════════════════
    ws3 = wb.create_sheet("Insights")
    ws3.merge_cells("A1:B1")
    t3 = ws3["A1"]
    t3.value = "System-Generated Insights"
    t3.font = Font(bold=True, size=13, color=WHITE)
    t3.fill = PatternFill("solid", fgColor=BLUE_DARK)
    t3.alignment = Alignment(horizontal="center")

    header_style(ws3, 2, 1, "#", bg=BLUE_LIGHT, fg="000000")
    header_style(ws3, 2, 2, "Insight", bg=BLUE_LIGHT, fg="000000")

    insights: List[str] = analytics.get("insights", [])
    for i, ins in enumerate(insights, 3):
        ws3.cell(row=i, column=1, value=i - 2)
        c = ws3.cell(row=i, column=2, value=ins)
        c.alignment = Alignment(wrap_text=True)

    set_col_widths(ws3, [5, 100])

    # ═══════════════════════════════════════════════════════════════════════════
    # SHEET 4 — Raw Extracted Data
    # ═══════════════════════════════════════════════════════════════════════════
    ws4 = wb.create_sheet("Raw Data")
    ws4.merge_cells("A1:B1")
    t4 = ws4["A1"]
    t4.value = f"Raw Extracted Fields — {form_type}"
    t4.font = Font(bold=True, size=13, color=WHITE)
    t4.fill = PatternFill("solid", fgColor=BLUE_DARK)
    t4.alignment = Alignment(horizontal="center")

    header_style(ws4, 2, 1, "Field", bg=BLUE_LIGHT, fg="000000")
    header_style(ws4, 2, 2, "Extracted Value", bg=BLUE_LIGHT, fg="000000")

    row = 3
    for key, val in extracted_data.items():
        if key.startswith("_"):
            continue
        ws4.cell(row=row, column=1, value=key)
        if isinstance(val, (int, float)):
            c = ws4.cell(row=row, column=2, value=val)
            c.number_format = '#,##0.00'
        elif val is None:
            c = ws4.cell(row=row, column=2, value="Not found in document")
            c.font = Font(italic=True, color="888888")
        else:
            ws4.cell(row=row, column=2, value=str(val))
        if row % 2 == 0:
            ws4.cell(row=row, column=1).fill = PatternFill("solid", fgColor=GREY_LIGHT)
            ws4.cell(row=row, column=2).fill = PatternFill("solid", fgColor=GREY_LIGHT)
        row += 1

    set_col_widths(ws4, [45, 30])

    wb.save(output_path)
    logger.info("Excel exported to %s", output_path)
    return output_path


# ── PDF CA Report Export ──────────────────────────────────────────────────────

def export_pdf_report(extracted_data: Dict, analytics: Dict, output_path: str) -> str:
    """
    Generate a CA-format PDF report using ReportLab.
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            HRFlowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
            TableStyle,
        )
    except ImportError:
        raise RuntimeError("reportlab not installed. Run: pip install reportlab")

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    story  = []

    # Custom styles
    title_style   = ParagraphStyle("Title",   fontSize=18, fontName="Helvetica-Bold",
                                   textColor=colors.HexColor("#1E3A5F"), alignment=1, spaceAfter=6)
    h1_style      = ParagraphStyle("H1",      fontSize=13, fontName="Helvetica-Bold",
                                   textColor=colors.HexColor("#1E3A5F"), spaceBefore=16, spaceAfter=6)
    h2_style      = ParagraphStyle("H2",      fontSize=11, fontName="Helvetica-Bold",
                                   textColor=colors.HexColor("#2E6DA4"), spaceBefore=10, spaceAfter=4)
    body_style    = ParagraphStyle("Body",    fontSize=10, fontName="Helvetica",
                                   leading=14, spaceAfter=4)
    note_style    = ParagraphStyle("Note",    fontSize=9,  fontName="Helvetica-Oblique",
                                   textColor=colors.grey, spaceAfter=4)
    warn_style    = ParagraphStyle("Warn",    fontSize=9,  fontName="Helvetica-Bold",
                                   textColor=colors.orange, spaceAfter=4)

    def hr():
        return HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#2E6DA4"), spaceAfter=6)

    def na(val: Optional[Any]) -> str:
        if val is None:
            return "Not available in document"
        if isinstance(val, float):
            return f"₹{val:,.2f}"
        return str(val)

    now        = datetime.now().strftime("%d %B %Y, %H:%M")
    form_type  = extracted_data.get("form_type", "GST Return")
    period     = extracted_data.get("period", "N/A")
    gstin      = extracted_data.get("gstin") or "N/A"
    entity     = extracted_data.get("legal_name") or "N/A"

    # ── Cover ─────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 1 * cm))
    story.append(Paragraph("GST Intelligence Report", title_style))
    story.append(Paragraph(f"{form_type} — {period}", styles["Heading2"]))
    story.append(hr())

    meta = [
        ["GSTIN", gstin],
        ["Entity Name", entity],
        ["Form Type", form_type],
        ["Period", period],
        ["Report Date", now],
        ["Prepared by", "GST Intelligence System (Audit-Safe)"],
    ]
    meta_table = Table(meta, colWidths=[5 * cm, 11 * cm])
    meta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#D6E4F0")),
        ("FONTNAME",   (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 10),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
        ("GRID",       (0, 0), (-1, -1), 0.3, colors.grey),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 0.5 * cm))

    # ── Section 1: Executive Summary ──────────────────────────────────────────
    story.append(Paragraph("1. Executive Summary", h1_style))
    story.append(hr())

    kpis: List[Dict] = analytics.get("kpis", [])
    kpi_data = [["Metric", "Value", "Status"]]
    for k in kpis:
        val_str = na(k.get("value")) if k["available"] else "Not available in document"
        status  = "Available" if k["available"] else "—"
        kpi_data.append([k["label"], val_str, status])

    kpi_table = Table(kpi_data, colWidths=[8 * cm, 5 * cm, 4 * cm])
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), colors.HexColor("#1E3A5F")),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
        ("GRID",          (0, 0), (-1, -1), 0.3, colors.grey),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ALIGN",         (1, 1), (1, -1), "RIGHT"),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 0.4 * cm))

    # ── Section 2: Ratio Analysis ─────────────────────────────────────────────
    story.append(Paragraph("2. Ratio Analysis", h1_style))
    story.append(hr())

    ratios: List[Dict] = analytics.get("ratios", [])
    if ratios:
        r_data = [["Ratio", "Value", "Benchmark", "Interpretation"]]
        for r in ratios:
            val_str = f"{r['value']:.2f}{r.get('unit','%')}" if r["available"] else "N/A"
            r_data.append([
                r["name"],
                val_str,
                r.get("benchmark") or "—",
                r.get("interpretation") or "—",
            ])
        r_table = Table(r_data, colWidths=[5.5 * cm, 2.5 * cm, 5 * cm, 4 * cm])
        r_table.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), colors.HexColor("#2E6DA4")),
            ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
            ("GRID",          (0, 0), (-1, -1), 0.3, colors.grey),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("WORDWRAP",      (0, 0), (-1, -1), True),
        ]))
        story.append(r_table)
    else:
        story.append(Paragraph("No ratio data available.", note_style))
    story.append(Spacer(1, 0.4 * cm))

    # ── Section 3: Key Findings & Insights ────────────────────────────────────
    story.append(Paragraph("3. Key Findings & Observations", h1_style))
    story.append(hr())

    insights: List[str] = analytics.get("insights", [])
    for i, ins in enumerate(insights, 1):
        story.append(Paragraph(f"{i}. {ins}", body_style))

    story.append(Spacer(1, 0.4 * cm))

    # ── Section 4: Raw Data ───────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("4. Raw Extracted Data (Appendix)", h1_style))
    story.append(hr())
    story.append(Paragraph(
        "The following table contains all fields as directly extracted from the PDF document. "
        "Fields showing 'Not available' were not found in the document.",
        note_style,
    ))
    story.append(Spacer(1, 0.3 * cm))

    raw_data = [["Field", "Extracted Value"]]
    for key, val in extracted_data.items():
        if key.startswith("_"):
            continue
        if isinstance(val, float):
            val_str = f"₹{val:,.2f}"
        elif val is None:
            val_str = "Not available in document"
        else:
            val_str = str(val)
        raw_data.append([key, val_str])

    raw_table = Table(raw_data, colWidths=[8 * cm, 9 * cm])
    raw_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), colors.HexColor("#1E3A5F")),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
        ("GRID",          (0, 0), (-1, -1), 0.3, colors.grey),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(raw_table)
    story.append(Spacer(1, 0.5 * cm))

    # ── Section 5: Disclaimer ─────────────────────────────────────────────────
    story.append(Paragraph("5. Disclaimer", h1_style))
    story.append(hr())
    story.append(Paragraph(
        "This report has been generated automatically by GST Intelligence System. "
        "All values are derived solely from the uploaded PDF document using pattern-based extraction. "
        "Fields marked as 'Not available' were not found in the provided document. "
        "No values have been assumed, estimated, or extrapolated. "
        "This report is for informational purposes only and should be verified by a qualified "
        "Chartered Accountant before being used for compliance or filing purposes.",
        note_style,
    ))

    doc.build(story)
    logger.info("PDF report exported to %s", output_path)
    return output_path


# ── GSTR-1 MOM Template-based Export ─────────────────────────────────────────  REWRITTEN
#
# Template: "GSTR-1 Vs Books" (format.xlsx / template_gstr1_mom.xlsx)
#
# Template layout (verified by inspection):
#   Rows 1-5  : empty
#   Row 6     : title "GSTR-1"  (merged A6:AM6)
#   Row 7     : section group headers  (B2B, B2CL, B2C(others), Nil rated…)
#   Row 8     : sub-column headers     (Taxable value, IGST, CGST, SGST…)
#   Rows 9-20 : data  —  April(9) … March(20)
#   Row 21    : Grand Total  (SUM formulas — preserved from template)
#   Row 22    : As per Annual Summary  (manual entry, left blank)
#   Row 23    : Difference  (formula = row21-row22 — preserved)
#
# DATA_START_ROW = 9   (first month row, April)
# DATA_END_ROW   = 20  (last month row, March)
#
# EXPLICIT COLUMN MAP  (1-based, matching actual template columns exactly)
# ─────────────────────────────────────────────────────────────────────────
#   1  A  month
#   2  B  b2b_taxable        9  I  b2co_igst        17 Q  amend_cgst
#   3  C  b2b_igst          10  J  b2co_cgst        18 R  amend_sgst
#   4  D  b2b_cgst          11  K  b2co_sgst        19 S  adv_recv_taxable
#   5  E  b2b_sgst          12  L  nil_rated        20 T  adv_recv_igst
#   6  F  b2cl_taxable      13  M  exempt           21 U  adv_recv_cgst
#   7  G  b2cl_igst         14  N  non_gst          22 V  adv_recv_sgst
#   8  H  b2co_taxable      15  O  amend_taxable    23 W  adv_adj_taxable
#                            16  P  amend_igst       24 X  adv_adj_igst
#                                                    25 Y  adv_adj_cgst
#                                                    26 Z  adv_adj_sgst
#   27 AA  cdn_reg_taxable   31 AE cdn_unreg_taxable   35 AI hsn_taxable
#   28 AB  cdn_reg_igst      32 AF cdn_unreg_igst      36 AJ hsn_taxable_excl_nil
#   29 AC  cdn_reg_cgst      33 AG cdn_unreg_cgst      37 AK ← FORMULA (IGST sum)
#   30 AD  cdn_reg_sgst      34 AH cdn_unreg_sgst      38 AL ← FORMULA (CGST sum)
#                                                        39 AM ← FORMULA (= AL)

# Month name (lowercase) → template data row number
_MONTH_TO_ROW: Dict[str, int] = {
    "april": 9, "may": 10, "june": 11, "july": 12,
    "august": 13, "september": 14, "october": 15, "november": 16,
    "december": 17, "january": 18, "february": 19, "march": 20,
}

# Explicit column map — key → 1-based column number (LOCKED to template)
_COL_MAP: Dict[str, int] = {
    "month":              1,
    # B2B
    "b2b_taxable":        2,
    "b2b_igst":           3,
    "b2b_cgst":           4,
    "b2b_sgst":           5,
    # B2CL (Large)
    "b2cl_taxable":       6,
    "b2cl_igst":          7,
    # B2C Others (B2CS — intra-state, IGST=0)
    "b2cs_taxable":       8,
    "b2cs_igst":          9,
    "b2cs_cgst":         10,
    "b2cs_sgst":         11,
    # Nil / Exempt / Non-GST
    "nil_rated":         12,
    "exempt":            13,
    "non_gst":           14,
    # Amendment to B2C (not tracked -> 0)
    "_amend_tx":         15,
    "_amend_ig":         16,
    "_amend_cg":         17,
    "_amend_sg":         18,
    # Advance Received (not tracked -> 0)
    "_arecv_tx":         19,
    "_arecv_ig":         20,
    "_arecv_cg":         21,
    "_arecv_sg":         22,
    # Advance Adjustment (not tracked -> 0)
    "_aadj_tx":          23,
    "_aadj_ig":          24,
    "_aadj_cg":          25,
    "_aadj_sg":          26,
    # CDN Registered
    "cdnr_taxable":      27,
    "cdnr_igst":         28,
    "cdnr_cgst":         29,
    "cdnr_sgst":         30,
    # CDN Unregistered (not tracked -> 0)
    "cdnur_taxable":     31,
    "cdnur_igst":        32,
    "cdnur_cgst":        33,
    "cdnur_sgst":        34,
    # Totals (AI, AJ) — AK/AL/AM are formula cells, never written
    "hsn_taxable":       35,
    "_hsn_excl":         36,
}

# Formula columns in data rows — never overwrite these
_FORMULA_COLS = {37, 38, 39}  # AK, AL, AM


def _fmt_val(val: Any, fmt: str) -> float:
    """Convert raw value to the requested display unit. Always returns float."""
    try:
        n = float(val) if val is not None else 0.0
    except (TypeError, ValueError):
        n = 0.0
    if fmt == "l":
        return round(n / 1e5, 2)
    if fmt == "cr":
        return round(n / 1e7, 2)
    return round(n, 2)


def _resolve_month(period: str) -> Optional[str]:
    """
    Return lowercase full month name from any period string.
    Tries word match first, then 3-letter abbreviation, then numeric month.
    Returns None if period is blank or unrecognisable.
    """
    import re
    if not period or not period.strip():
        return None

    p = period.lower().strip()

    # Full month names
    FULL = ["january","february","march","april","may","june",
            "july","august","september","october","november","december"]
    for m in FULL:
        if m in p:
            return m

    # 3-letter abbreviations (word-boundary aware)
    ABBR = {
        "jan":"january","feb":"february","mar":"march","apr":"april",
        "jun":"june","jul":"july","aug":"august","sep":"september",
        "oct":"october","nov":"november","dec":"december",
    }
    for abbr, full in ABBR.items():
        if re.search(r'\b' + abbr + r'\b', p):
            return full

    # Numeric month  e.g. "04/2025", "2025-10", "10-2025"
    m = re.search(r'\b(0?[1-9]|1[0-2])\b', p)
    if m:
        return FULL[int(m.group(1)) - 1]

    return None


def generate_gstr1_mom_from_template(
    rows: List[Dict],
    template_path: str,
    output_path: str,
    gstin: str = "",
    format_mode: str = "raw",
) -> str:
    """
    Fill the GSTR-1 MOM Excel template with month-wise data.

    `rows` must be a list of dicts with these keys (from the route):
        month, b2b_taxable, b2b_igst, b2b_cgst, b2b_sgst,
        b2cl_taxable, b2cl_igst,
        b2co_taxable, b2co_cgst, b2co_sgst,
        nil_rated, cdn_reg_taxable, cdn_reg_igst, cdn_reg_cgst, cdn_reg_sgst,
        hsn_taxable

    Template structure is kept exactly — only data cells (cols 1-36, rows 9-20)
    are written.  Formula cells (AK=37, AL=38, AM=39) are never touched.
    """
    try:
        import openpyxl
    except ImportError:
        raise RuntimeError("openpyxl not installed.  Run: pip install openpyxl")

    # ── Backward-compatible key normalisation ────────────────────────────────
    def normalize_row(r):
        return {
            "month":          r.get("month"),
            "b2b_taxable":    r.get("b2b_taxable",    0),
            "b2b_igst":       r.get("b2b_igst",       0),
            "b2b_cgst":       r.get("b2b_cgst",       0),
            "b2b_sgst":       r.get("b2b_sgst",       0),
            "b2cl_taxable":   r.get("b2cl_taxable",   0),
            "b2cl_igst":      r.get("b2cl_igst",      0),
            # b2cs — accept both new (b2cs_*) and old (b2co_*) keys
            "b2cs_taxable":   r.get("b2cs_taxable")   or r.get("b2co_taxable",   0),
            "b2cs_igst":      r.get("b2cs_igst")      or r.get("b2co_igst",      0),
            "b2cs_cgst":      r.get("b2cs_cgst")      or r.get("b2co_cgst",      0),
            "b2cs_sgst":      r.get("b2cs_sgst")      or r.get("b2co_sgst",      0),
            # cdnr — accept both new (cdnr_*) and old (cdn_reg_*) keys
            # Use is-not-None check so negative values (-12,81,21,444.19) pass through
            "cdnr_taxable":   r["cdnr_taxable"]   if r.get("cdnr_taxable")   is not None else (r.get("cdn_reg_taxable",  0) or 0),
            "cdnr_igst":      r["cdnr_igst"]      if r.get("cdnr_igst")      is not None else (r.get("cdn_reg_igst",     0) or 0),
            "cdnr_cgst":      r["cdnr_cgst"]      if r.get("cdnr_cgst")      is not None else (r.get("cdn_reg_cgst",     0) or 0),
            "cdnr_sgst":      r["cdnr_sgst"]      if r.get("cdnr_sgst")      is not None else (r.get("cdn_reg_sgst",     0) or 0),
            # cdnur — accept both new (cdnur_*) and old (cdn_unreg_*) keys
            "cdnur_taxable":  r["cdnur_taxable"]  if r.get("cdnur_taxable")  is not None else (r.get("cdn_unreg_taxable", 0) or 0),
            "cdnur_igst":     r["cdnur_igst"]     if r.get("cdnur_igst")     is not None else (r.get("cdn_unreg_igst",    0) or 0),
            "cdnur_cgst":     r["cdnur_cgst"]     if r.get("cdnur_cgst")     is not None else (r.get("cdn_unreg_cgst",    0) or 0),
            "cdnur_sgst":     r["cdnur_sgst"]     if r.get("cdnur_sgst")     is not None else (r.get("cdn_unreg_sgst",    0) or 0),
            "nil_rated":      r.get("nil_rated",      0),
            "exempt":         r.get("exempt",         0),
            "non_gst":        r.get("non_gst",        0),
            "hsn_taxable":    r.get("hsn_taxable")    or r.get("hsn_taxable_excl", 0),
        }

    rows = [normalize_row(r) for r in rows]

    # ── DEBUG: confirm data before writing ───────────────────────────────────
    print("ROWS COUNT:", len(rows))
    print("SAMPLE:", rows[:1])

    if not rows:
        logger.error("[MOM Export] No rows provided — nothing to write")
        raise ValueError("[MOM Export] No rows provided — nothing to write")

    # Warn if all values are zero but DO NOT raise — still export
    _numeric_keys = [
        "b2b_taxable", "b2b_igst", "b2b_cgst", "b2b_sgst",
        "b2cl_taxable", "b2cl_igst",
        "b2cs_taxable", "b2cs_cgst", "b2cs_sgst",
        "nil_rated", "cdnr_taxable", "hsn_taxable",
    ]
    if all(all((r.get(k) or 0) == 0 for k in _numeric_keys) for r in rows):
        print("WARNING: All values zero, but continuing export")

    # ── Load template ─────────────────────────────────────────────────────────
    wb = openpyxl.load_workbook(template_path, data_only=False)
    ws = wb.active   # "GSTR-1 Vs Books" is the only / first sheet

    NUM_FMT = "#,##0.00"

    # ── Write data ────────────────────────────────────────────────────────────
    # Strategy:
    #   1. Try to place each row in the correct month slot via _MONTH_TO_ROW
    #      (April=row9 … March=row20 — locked to template structure).
    #   2. If month cannot be determined, fall back to next free sequential row.
    DATA_START = 9
    DATA_END   = 20
    next_free_row = DATA_START   # fallback pointer

    for row in rows:
        # ── Resolve target row ────────────────────────────────────────────────
        month_str = str(row.get("month") or "")
        month_key = _resolve_month(month_str)
        if month_key and month_key in _MONTH_TO_ROW:
            target_row = _MONTH_TO_ROW[month_key]
            print(f"[MOM Export] '{month_str}' -> row {target_row} ({month_key})")
        else:
            # Fallback: next sequential slot
            target_row = next_free_row
            print(f"[MOM Export] period unresolved ('{month_str}') -> fallback row {target_row}")
            next_free_row += 1
            if next_free_row > DATA_END:
                print("[MOM Export] WARNING: more rows than template slots — truncating")
                break

        # ── Write month label (col A) ─────────────────────────────────────────
        label = month_key.capitalize() if month_key else (month_str or f"Row {target_row}")
        ws.cell(row=target_row, column=_COL_MAP["month"]).value = label

        # ── Helper: write numeric cell ────────────────────────────────────────
        def w(key: str, val: Any):
            col = _COL_MAP[key]
            if col in _FORMULA_COLS:
                return   # never overwrite formula cells
            cell = ws.cell(row=target_row, column=col)
            cell.value = _fmt_val(val, format_mode)
            cell.number_format = NUM_FMT

        # ── B2B ───────────────────────────────────────────────────────────────
        w("b2b_taxable", row.get("b2b_taxable", 0))
        w("b2b_igst",    row.get("b2b_igst",    0))
        w("b2b_cgst",    row.get("b2b_cgst",    0))
        w("b2b_sgst",    row.get("b2b_sgst",    0))

        # ── B2CL ─────────────────────────────────────────────────────────────
        w("b2cl_taxable", row.get("b2cl_taxable", 0))
        w("b2cl_igst",    row.get("b2cl_igst",    0))

        # ── B2C Others (B2CS) — IGST = 0 for intra-state ─────────────────────
        w("b2cs_taxable", row.get("b2cs_taxable", 0))
        w("b2cs_igst",    0)
        w("b2cs_cgst",    row.get("b2cs_cgst",    0))
        w("b2cs_sgst",    row.get("b2cs_sgst",    0))

        # ── Nil / Exempt / Non-GST ────────────────────────────────────────────
        w("nil_rated", row.get("nil_rated", 0))
        w("exempt",    row.get("exempt",   0))
        w("non_gst",   row.get("non_gst",  0))

        # ── Amendment B2C (not tracked) ───────────────────────────────────────
        w("_amend_tx", 0); w("_amend_ig", 0)
        w("_amend_cg", 0); w("_amend_sg", 0)

        # ── Advance Received (not tracked) ────────────────────────────────────
        w("_arecv_tx", 0); w("_arecv_ig", 0)
        w("_arecv_cg", 0); w("_arecv_sg", 0)

        # ── Advance Adjustment (not tracked) ──────────────────────────────────
        w("_aadj_tx", 0); w("_aadj_ig", 0)
        w("_aadj_cg", 0); w("_aadj_sg", 0)

        # ── CDN Registered ────────────────────────────────────────────────────
        w("cdnr_taxable", row.get("cdnr_taxable", 0))
        w("cdnr_igst",    row.get("cdnr_igst",    0))
        w("cdnr_cgst",    row.get("cdnr_cgst",    0))
        w("cdnr_sgst",    row.get("cdnr_sgst",    0))

        # ── CDN Unregistered (not tracked) ────────────────────────────────────
        w("cdnur_taxable", row.get("cdnur_taxable", 0)); w("cdnur_igst", row.get("cdnur_igst", 0))
        w("cdnur_cgst",    row.get("cdnur_cgst",    0)); w("cdnur_sgst", row.get("cdnur_sgst", 0))

        # ── HSN Totals (AI, AJ) — AK/AL/AM are formula cells, skip ──────────
        w("hsn_taxable", row.get("hsn_taxable", 0))
        w("_hsn_excl",   row.get("hsn_taxable", 0))

        print(f"Writing row {target_row}: ", row.get("month"),
              "b2b=", row.get("b2b_taxable", 0),
              "b2cs=", row.get("b2cs_taxable", 0),
              "cdnr=", row.get("cdnr_taxable", 0),
              "hsn=", row.get("hsn_taxable", 0))

    # ── Save ──────────────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    wb.save(output_path)
    print(f"[MOM Export] Saved -> {output_path}")
    logger.info("[MOM Export] Saved to %s", output_path)
    return output_path
