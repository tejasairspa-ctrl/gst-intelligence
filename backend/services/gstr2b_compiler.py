"""
GSTR-2B Compiler
────────────────
Merges N monthly GSTR-2B Excel files (portal downloads) into one consolidated
workbook that looks exactly like the GST portal format, with exactly two extra
columns prepended to every data sheet:

  Col A — GSTIN   : taxpayer's GSTIN (from Read Me sheet)
  Col B — Period  : month-year label  e.g. "April 2025"

All other columns, header text, and styling replicate the portal exactly.
Rows are sorted in Financial-Year order (Apr first, Mar last).

Portal styling reference (from actual portal files):
  Row 1 (title)      : fill #203764, white Arial Bold, merged across all cols
  Row 2-3            : blank, same fill
  Row 4 (subtitle)   : fill #FFFFF2CC, black Arial Bold, merged across all cols
  Row 5-6 (headers)  : fill #203764, white Arial Bold, various merges
  Row 7+  (data)     : no fill, Arial 10
"""
import re
import io
from openpyxl import load_workbook, Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter, column_index_from_string

# ── Month helpers ─────────────────────────────────────────────────────────────
_MONTH_FULL = [
    'january','february','march','april','may','june',
    'july','august','september','october','november','december',
]
_MONTH_SHORT = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
_MONTH_MAP   = {f: s for f, s in zip(_MONTH_FULL, _MONTH_SHORT)}

# FY order: Apr=0 … Dec=8, Jan=9, Feb=10, Mar=11  (handles full + short names)
_FY_POS = {
    'april':0,'may':1,'june':2,'july':3,'august':4,'september':5,
    'october':6,'november':7,'december':8,'january':9,'february':10,'march':11,
    'apr':0,'jun':2,'jul':3,'aug':4,'sep':5,
    'oct':6,'nov':7,'dec':8,'jan':9,'feb':10,'mar':11,
}


def _fy_sort_key(period_label: str) -> tuple:
    parts = (period_label or '').strip().split()
    if len(parts) < 2:
        return (9999, 99)
    mon = parts[0].lower()
    try:
        yr = int(parts[1])
    except ValueError:
        return (9999, 99)
    pos      = _FY_POS.get(mon, 99)
    fy_start = yr - 1 if pos >= 9 else yr
    return (fy_start, pos)


def _is_amendment_sheet(name: str) -> bool:
    base = re.sub(r'\s*\(.*\)', '', name).strip()
    return base.endswith('A')


def _extract_readme_info(ws) -> tuple:
    """Return (period_label, gstin) from the Read me worksheet."""
    month_str = fy_str = gstin = ''
    for row in ws.iter_rows(min_row=1, max_row=15, values_only=True):
        label = str(row[0]).strip().lower() if row[0] else ''
        value = str(row[2]).strip()         if len(row) > 2 and row[2] else ''
        if 'financial year' in label:
            fy_str = value
        elif 'tax period' in label:
            month_str = value
        elif label == 'gstin':
            gstin = value

    month_lower = month_str.lower()
    # Full month name e.g. "January"
    cal_year = ''
    if fy_str and '-' in fy_str:
        parts    = fy_str.split('-')
        start_yr = parts[0]
        end_part = parts[1]
        end_yr   = ('20' + end_part) if len(end_part) == 2 else end_part
        if month_lower in _MONTH_FULL:
            mn       = _MONTH_FULL.index(month_lower) + 1
            cal_year = start_yr if mn >= 4 else end_yr
    elif fy_str.isdigit():
        cal_year = fy_str

    # Keep full month name in period label (e.g. "January 2026")
    period_label = f"{month_str} {cal_year}".strip() if month_str else ''
    return period_label, gstin


def _period_from_filename(filename: str) -> str:
    m = re.match(r'^(\d{2})(\d{4})', filename)
    if m:
        mn_num = int(m.group(1))
        yr     = m.group(2)
        if 1 <= mn_num <= 12:
            return f"{_MONTH_FULL[mn_num-1].capitalize()} {yr}"
    return ''


# ── Portal-matching styles ────────────────────────────────────────────────────
_NAVY   = 'FF203764'   # portal header/title fill
_YELLOW = 'FFFFF2CC'  # portal subtitle fill
_WHITE  = 'FFFFFFFF'
_BLACK  = 'FF000000'

_FILL_NAVY   = PatternFill('solid', start_color=_NAVY)
_FILL_YELLOW = PatternFill('solid', start_color=_YELLOW)
_FILL_NONE   = PatternFill(fill_type=None)

_FONT_HDR    = Font(name='Arial', bold=True,  size=10, color=_WHITE)
_FONT_SUB    = Font(name='Arial', bold=True,  size=10, color=_BLACK)
_FONT_DATA   = Font(name='Arial', bold=False, size=10)
_FONT_PERIOD = Font(name='Arial', bold=True,  size=10, color=_WHITE)

_ALIGN_CTR   = Alignment(horizontal='center', vertical='center', wrap_text=True)
_ALIGN_LEFT  = Alignment(horizontal='left',   vertical='center', wrap_text=False)

_THIN        = Side(style='thin', color='BFBFBF')
_BORDER_DATA = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)


def _apply_header_cell(cell, fill, font, align=None):
    cell.fill      = fill
    cell.font      = font
    cell.alignment = align or _ALIGN_CTR


def _col_letter(idx_1based: int) -> str:
    return get_column_letter(idx_1based)


# ── Main compiler ─────────────────────────────────────────────────────────────

def compile_gstr2b(file_streams: list) -> bytes:
    """
    Compile multiple GSTR-2B Excel files into one consolidated workbook.

    Parameters
    ----------
    file_streams : list of (filename: str, stream: BinaryIO)

    Returns
    -------
    bytes : compiled .xlsx workbook
    """
    # sheet_name → {header_rows, rows, max_col, data_start}
    registry:    dict = {}
    files_meta:  list = []

    for filename, stream in file_streams:
        try:
            wb = load_workbook(stream, data_only=True)
        except Exception as exc:
            raise ValueError(f"Cannot open '{filename}': {exc}") from exc

        period, gstin = _extract_readme_info(wb.worksheets[0])
        if not period:
            period = _period_from_filename(filename)
        if not period:
            period = filename[:10]

        files_meta.append({'filename': filename, 'gstin': gstin, 'period': period})

        for ws in wb.worksheets[5:]:
            sname      = ws.title
            amendment  = _is_amendment_sheet(sname)
            data_start = 8 if amendment else 7   # actual data row in source

            if sname not in registry:
                header_rows = [
                    list(row)
                    for row in ws.iter_rows(min_row=1, max_row=data_start - 1, values_only=True)
                ]
                registry[sname] = {
                    'header_rows': header_rows,
                    'rows':        [],
                    'max_col':     ws.max_column or 21,
                    'data_start':  data_start,
                    'amendment':   amendment,
                }

            for row in ws.iter_rows(min_row=data_start, values_only=True):
                if any(c is not None for c in row):
                    registry[sname]['rows'].append((gstin, period, list(row)))

        wb.close()

    # Sort files_meta in FY order
    files_meta.sort(key=lambda fm: _fy_sort_key(fm['period']))

    # ── Build output workbook ─────────────────────────────────────────────
    wb_out = Workbook()
    wb_out.remove(wb_out.active)

    for sname, data in registry.items():
        ws_out    = wb_out.create_sheet(title=sname)
        hdr_rows  = data['header_rows']
        n_hdr     = len(hdr_rows)          # 6 for regular, 7 for amendment
        max_col   = data['max_col']        # original portal column count
        out_cols  = max_col + 2            # +2 for GSTIN and Period

        # ── Write header rows ─────────────────────────────────────────
        # Row structure (portal + 2 new cols):
        #   Rows 1-3 : title block  — NAVY fill, col A blank, col B blank, cols C+ = portal row 1
        #   Row 4    : subtitle     — YELLOW fill, all cols including A & B
        #   Row 5    : header line 1 — NAVY, A5='GSTIN', B5='Period', C5+ = portal row 5
        #   Row 6    : header line 2 — NAVY, A6=blank, B6=blank, C6+ = portal row 6
        #   Row 7    : (amendment only) header line 3 — NAVY, A7=blank, B7=blank, C7+ = portal row 7

        for i, hrow in enumerate(hdr_rows):
            row_num = i + 1
            if row_num <= 3:
                # Title block (rows 1-3): merged across full width, value must be in col A
                out_row = [hrow[0] if hrow else None] + [None] * (out_cols - 1)
            elif row_num == 4:
                # Subtitle row: merged across full width, value in col A
                out_row = [hrow[0] if hrow else None] + [None] * (out_cols - 1)
            elif row_num == n_hdr - 1:
                # First proper column-header row: GSTIN in A, Period in B, rest = portal
                out_row = ['GSTIN', 'Period'] + hrow
            else:
                # Second/third column-header row: A & B blank, rest = portal
                out_row = [None, None] + hrow

            ws_out.append(out_row)

            # Determine styling
            if row_num == 4:
                fill, font = _FILL_YELLOW, _FONT_SUB
            else:
                fill, font = _FILL_NAVY, _FONT_HDR

            for col_idx in range(1, out_cols + 1):
                cell = ws_out.cell(row=row_num, column=col_idx)
                _apply_header_cell(cell, fill, font)

        # Merged cells — replicate portal merges shifted right by 2
        # Title block: merge A1 : last_col + 3 (row 1-3)
        title_end = _col_letter(out_cols)
        ws_out.merge_cells(f'A1:{title_end}3')
        # Subtitle: merge A4:last_col
        ws_out.merge_cells(f'A4:{title_end}4')
        # GSTIN col: merge A(n_hdr-1):A(n_hdr)  so label spans both header rows
        first_hdr = n_hdr - 1
        ws_out.merge_cells(f'A{first_hdr}:A{n_hdr}')
        # Period col: same
        ws_out.merge_cells(f'B{first_hdr}:B{n_hdr}')

        # ── Write data rows ───────────────────────────────────────────
        # Sort by FY period
        sorted_rows = sorted(
            data['rows'],
            key=lambda r: _fy_sort_key(r[1])   # r[1] = period
        )

        for j, (gstin_val, period_val, src_row) in enumerate(sorted_rows):
            out_row = [gstin_val, period_val] + src_row
            ws_out.append(out_row)
            row_num = n_hdr + j + 1
            ws_out.row_dimensions[row_num].height = 15

            for col_idx in range(1, len(out_row) + 1):
                cell = ws_out.cell(row=row_num, column=col_idx)
                cell.font      = _FONT_DATA
                cell.alignment = _ALIGN_LEFT
                cell.border    = _BORDER_DATA

        # ── Column widths ─────────────────────────────────────────────
        ws_out.column_dimensions['A'].width = 22   # GSTIN
        ws_out.column_dimensions['B'].width = 14   # Period
        # Restore portal-like widths for data columns
        default_widths = {
            'C': 20, 'D': 20, 'E': 16, 'F': 16, 'G': 20,
            'H': 18, 'I': 16, 'J': 14, 'K': 14, 'L': 14,
        }
        for col_letter, w in default_widths.items():
            ws_out.column_dimensions[col_letter].width = w

        # Auto-filter on the last header row
        ws_out.auto_filter.ref = f'A{n_hdr}:{title_end}{n_hdr}'

        # Freeze panes below header + left of col C (past GSTIN+Period)
        ws_out.freeze_panes = f'C{n_hdr + 1}'

    # ── Compilation summary sheet ─────────────────────────────────────
    info = wb_out.create_sheet(title='Summary', index=0)
    info.append(['GSTR-2B Compiled Report'])
    info.append([])
    info.append(['Period', 'GSTIN', 'Source File'])
    for fm in files_meta:
        info.append([fm['period'], fm['gstin'], fm['filename']])

    info['A1'].font = Font(name='Arial', bold=True, size=12, color=_NAVY)
    hdr_fill = PatternFill('solid', start_color=_NAVY)
    for col in range(1, 4):
        c = info.cell(row=3, column=col)
        c.fill = hdr_fill
        c.font = _FONT_HDR
    info.column_dimensions['A'].width = 18
    info.column_dimensions['B'].width = 22
    info.column_dimensions['C'].width = 55

    # ── Serialize ─────────────────────────────────────────────────────
    buf = io.BytesIO()
    wb_out.save(buf)
    buf.seek(0)
    return buf.getvalue()
