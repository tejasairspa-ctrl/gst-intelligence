"""Excel export for the anomaly view — mirrors the on-screen expanded matrix.

Sheets:
  • Yearly Totals   — figures × FY, each year = Total + Δ% vs prev, anomalous
                      cells colour-coded by severity.
  • Monthly Figures — figures × month, anomalous months highlighted.
  • Anomaly List    — one row per flag (Axis, Figure, Period, Value, Baseline,
                      Δ%, Severity, Reason).
"""
from datetime import datetime

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from services.anomaly_engine import compute_anomalies

# Light, print-friendly severity styling
SEV_FILL = {"HIGH": "FEE2E2", "MEDIUM": "FEF3C7", "LOW": "F1F5F9"}
SEV_FONT = {"HIGH": "991B1B", "MEDIUM": "92400E", "LOW": "334155"}

_TITLE_BG = "0A1929"
_HDR_BG   = "1C3557"
_SUB_BG   = "E8EEF6"
_THIN     = Side(style="thin", color="D0D7E2")
_BORDER   = Border(top=_THIN, bottom=_THIN, left=_THIN, right=_THIN)


def _f(bold=False, color="000000", size=9, italic=False):
    return Font(bold=bold, color=color, size=size, italic=italic, name="Calibri")


def _fill(c):
    return PatternFill("solid", fgColor=c)


def _title(ws, text, ncols):
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(ncols, 2))
    c = ws.cell(1, 1, text)
    c.fill = _fill(_TITLE_BG); c.font = _f(bold=True, color="5BA3D9", size=11)
    c.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[1].height = 26


def _rupees(v):
    return round(float(v), 2) if v is not None else None


def _yearly_sheet(ws, matrix):
    fys = matrix["fys"]
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 34
    ncols = 1 + len(fys) * 2
    _title(ws, "Anomaly Detection — Yearly Totals & YoY % (anomalous cells highlighted)", ncols)

    # Header row 2: FY spanning two sub-cols; row 3: Total | Δ% vs prev
    ws.cell(2, 1, "Figure").fill = _fill(_HDR_BG)
    ws.cell(2, 1).font = _f(bold=True, color="FFFFFF")
    ws.cell(2, 1).alignment = Alignment(vertical="center", indent=1)
    col = 2
    fy_col = {}
    for fy in fys:
        ws.merge_cells(start_row=2, start_column=col, end_row=2, end_column=col + 1)
        h = ws.cell(2, col, fy.replace("FY ", "")); h.fill = _fill(_HDR_BG)
        h.font = _f(bold=True, color="FFFFFF"); h.alignment = Alignment(horizontal="center")
        t = ws.cell(3, col, "Total"); t.fill = _fill(_SUB_BG); t.font = _f(bold=True, size=8)
        t.alignment = Alignment(horizontal="right")
        d = ws.cell(3, col + 1, "Δ% vs prev"); d.fill = _fill(_SUB_BG); d.font = _f(bold=True, size=8)
        d.alignment = Alignment(horizontal="right")
        ws.column_dimensions[get_column_letter(col)].width = 15
        ws.column_dimensions[get_column_letter(col + 1)].width = 11
        fy_col[fy] = col
        col += 2

    r = 4
    for row in matrix["rows"]:
        ws.cell(r, 1, row["label"]).font = _f(size=9)
        ws.cell(r, 1).border = _BORDER
        ymap = {c["fy"]: c for c in row["yoy"]}
        for i, fy in enumerate(fys):
            c = ymap.get(fy)
            base = fy_col[fy]
            vcell = ws.cell(r, base, _rupees(c["value"]) if c else None)
            vcell.number_format = '#,##0'; vcell.border = _BORDER
            vcell.alignment = Alignment(horizontal="right")
            if c and c.get("severity"):
                vcell.fill = _fill(SEV_FILL[c["severity"]])
                vcell.font = _f(bold=True, color=SEV_FONT[c["severity"]], size=9)
            else:
                vcell.font = _f(size=9, color="475569")
            pct = c.get("yoy_pct") if c else None
            pcell = ws.cell(r, base + 1, (pct / 100.0) if (i > 0 and pct is not None) else None)
            pcell.number_format = '+0.0%;-0.0%'; pcell.border = _BORDER
            pcell.alignment = Alignment(horizontal="right")
            pcell.font = _f(size=8, color=("047857" if (pct or 0) >= 0 else "B91C1C"))
        r += 1
    ws.freeze_panes = "B4"


def _monthly_sheet(ws, matrix):
    periods = matrix["periods"]
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 34
    _title(ws, "Anomaly Detection — Monthly Figures (anomalous months highlighted)", 1 + len(periods))
    ws.cell(2, 1, "Figure").fill = _fill(_HDR_BG); ws.cell(2, 1).font = _f(bold=True, color="FFFFFF")
    ws.cell(2, 1).alignment = Alignment(vertical="center", indent=1)
    for j, p in enumerate(periods):
        c = ws.cell(2, 2 + j, p); c.fill = _fill(_HDR_BG)
        c.font = _f(bold=True, color="FFFFFF", size=8); c.alignment = Alignment(horizontal="right")
        ws.column_dimensions[get_column_letter(2 + j)].width = 13
    r = 3
    for row in matrix["rows"]:
        ws.cell(r, 1, row["label"]).font = _f(size=9); ws.cell(r, 1).border = _BORDER
        mmap = {c["period"]: c for c in row["mom"]}
        for j, p in enumerate(periods):
            c = mmap.get(p)
            cell = ws.cell(r, 2 + j, _rupees(c["value"]) if c else None)
            cell.number_format = '#,##0'; cell.border = _BORDER
            cell.alignment = Alignment(horizontal="right")
            if c and c.get("severity"):
                cell.fill = _fill(SEV_FILL[c["severity"]]); cell.font = _f(bold=True, color=SEV_FONT[c["severity"]], size=8)
            else:
                cell.font = _f(size=8, color="475569")
        r += 1
    ws.freeze_panes = "B3"


def _list_sheet(ws, res):
    ws.sheet_view.showGridLines = False
    cols = ["Axis", "Type", "Figure / Ratio", "Period", "Value", "Baseline", "Δ%", "Severity", "Reason"]
    widths = [8, 8, 34, 16, 16, 16, 9, 10, 70]
    _title(ws, "Anomaly Detection — Flagged Items", len(cols))
    for j, (h, w) in enumerate(zip(cols, widths), 1):
        c = ws.cell(2, j, h); c.fill = _fill(_HDR_BG); c.font = _f(bold=True, color="FFFFFF", size=9)
        c.alignment = Alignment(horizontal="left")
        ws.column_dimensions[get_column_letter(j)].width = w
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    items = sorted((res.get("mom") or []) + (res.get("yoy") or []),
                   key=lambda a: (order.get(a["severity"], 3), -a.get("score", 0)))
    r = 3
    for a in items:
        pct = a.get("deviation_pct")
        vals = [a["axis"], a.get("kind", ""), a["metric"].replace("[ratio] ", ""),
                a["period"], _rupees(a["value"]) if a.get("unit") == "₹" else a["value"],
                _rupees(a["baseline"]) if a.get("unit") == "₹" else a["baseline"],
                (pct / 100.0) if pct is not None else None, a["severity"], a["reason"]]
        for j, v in enumerate(vals, 1):
            cell = ws.cell(r, j, v); cell.border = _BORDER
            cell.font = _f(size=8, color=SEV_FONT.get(a["severity"], "334155"))
            if j in (5, 6):
                cell.number_format = '#,##0' if a.get("unit") == "₹" else '0.00'
                cell.alignment = Alignment(horizontal="right")
            if j == 7:
                cell.number_format = '+0.0%;-0.0%'; cell.alignment = Alignment(horizontal="right")
            if j == 8:
                cell.fill = _fill(SEV_FILL.get(a["severity"], "F1F5F9")); cell.font = _f(bold=True, color=SEV_FONT.get(a["severity"], "334155"), size=8)
            if j == 9:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
        r += 1
    ws.freeze_panes = "A3"


def build_anomaly_workbook(store, out_path):
    res = compute_anomalies(store)
    matrix = res.get("matrix") or {"periods": [], "fys": [], "rows": []}
    wb = openpyxl.Workbook()
    _yearly_sheet(wb.active, matrix); wb.active.title = "Yearly Totals"
    _monthly_sheet(wb.create_sheet("Monthly Figures"), matrix)
    _list_sheet(wb.create_sheet("Anomaly List"), res)
    wb.save(out_path)
    return out_path
