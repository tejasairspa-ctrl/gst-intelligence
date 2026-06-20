"""Build the linked workbook from real PDFs, recalc with LibreOffice, and assert
the formula-computed ratio cells match compute_risk_ratios' trend values."""
import sys, os, glob, re, calendar, subprocess, json, shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.pdf_parser import parse_gst_pdf
from services import risk_engine as R
from services.risk_workbook import build_linked_workbook


def _period(fn):
    m = re.search(r'_(\d{2})(\d{4})', fn)
    return f'{calendar.month_name[int(m.group(1))]} {m.group(2)}' if m else 'Unknown'


class Store:
    def __init__(self): self.files = {}; self._e = {}
    def get_extracted_data(self, fid): return self._e.get(fid)
    def get_all_reconciliations(self): return {}


def load(folders):
    st = Store()
    for folder in folders:
        for pat, g in (("GSTR1_*.pdf", "GSTR-1"), ("GSTR3B_*.pdf", "GSTR-3B")):
            for f in sorted(glob.glob(os.path.join(folder, pat))):
                fid = os.path.basename(f)
                st.files[fid] = {"id": fid, "gst_type": g, "period": _period(fid)}
                st._e[fid] = parse_gst_pdf(f)
    return st


def main(folders):
    st = load(folders)
    out = os.path.join(os.path.dirname(__file__), "_linked_test.xlsx")
    build_linked_workbook(st, out)
    print("workbook built:", out)

    # Engine truth (trend table = ratio of FY sums)
    rd = R.compute_risk_ratios(st)
    truth = {}  # (sl, fy) -> value
    for row in rd["trend"]["ratios"]:
        for fy, v in row["values"].items():
            truth[(row["sl_no"], fy)] = v

    # Recalculate the workbook's formulas end-to-end (data sheets → ratios).
    import warnings, openpyxl
    warnings.filterwarnings("ignore")
    import formulas
    xl = formulas.ExcelModel().loads(out).finish()
    sol = xl.calculate()

    def _num(v):
        try:
            v = v.value[0, 0]
        except Exception:
            v = getattr(v, "value", v)
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    computed = {}  # "E4" -> value  (Risk Ratios sheet)
    for k, v in sol.items():
        if "RISK RATIOS'!" in k.upper():
            addr = k.split("!")[-1]
            computed[addr] = _num(v)

    wb = openpyxl.load_workbook(out)
    ws = wb["Risk Ratios"]
    hdr = [c.value for c in ws[2]]
    fy_cols = {h: i + 1 for i, h in enumerate(hdr) if isinstance(h, str) and h.startswith("FY")}
    from openpyxl.utils import get_column_letter

    checked = fails = 0
    for row in ws.iter_rows(min_row=3):
        sl = row[0].value
        for fy, ci in fy_cols.items():
            key = (sl, fy)
            if key not in truth:
                continue
            addr = f"{get_column_letter(ci)}{row[0].row}"
            cell = computed.get(addr)
            if cell is None:
                continue
            checked += 1
            if abs(cell - truth[key]) > 0.1:
                fails += 1
                print(f"  MISMATCH sl{sl} {fy}: excel={cell:.2f} engine={truth[key]:.2f}")
    print(f"checked {checked} recalculated formula cells vs engine trend; {fails} mismatches")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
