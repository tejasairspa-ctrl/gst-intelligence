"""Self-proving check: every risk ratio's source numbers must equal the
canonical MOM/Excel totals for the same line item.

This locks the "seamless linkage" requirement in place — if any ratio ever
starts reading a parallel/fallback field that diverges from what the MOM table
shows, this test fails. Run against any real dataset:

    venv/Scripts/python.exe -m tests.test_ratio_sources "<folder of GSTR-1 PDFs>"
"""
import sys, os, glob, re, calendar

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.pdf_parser import parse_gst_pdf
from services import risk_engine as R


def _period_from_filename(fn):
    m = re.search(r'_(\d{2})(\d{4})', fn)
    return f'{calendar.month_name[int(m.group(1))]} {m.group(2)}' if m else 'Unknown'


class _Store:
    def __init__(self): self.files = {}; self._ext = {}; self.reconciliations = {}
    def get_extracted_data(self, fid): return self._ext.get(fid)
    def get_all_reconciliations(self): return {}


def _canonical_fy_totals(exts):
    """FY totals built from the SAME canonical accessors the MOM row uses."""
    s = lambda fn: sum(fn(e) for e in exts)
    return {
        "B2B Sales":              abs(s(R.g1_b2b)),
        "B2CL Sales (Unregistered)": abs(s(R.g1_b2cl)),
        "Total Taxable Turnover": abs(s(R.g1_total)),
        "B2B Credit Notes (CDNR)": abs(s(R.g1_cdnr)),
        "Unregistered Credit Notes (CDNUR)": abs(s(R.g1_cdnur)),
        "Export Credit Notes (CDNUR)": abs(s(R.g1_cdnur)),
        "Export Turnover":        s(R._g1_export_turnover),
        "Deemed Exports":         s(R.g1_deemed),
        "SEZ Supplies":           s(R.g1_sez),
        "Non-GST Supplies":       s(R.g1_nongst),
    }


def check(folder):
    st = _Store()
    exts = []
    for f in sorted(glob.glob(os.path.join(folder, "GSTR1_*.pdf"))):
        fid = os.path.basename(f)
        ext = parse_gst_pdf(f)
        st.files[fid] = {"id": fid, "gst_type": "GSTR-1", "period": _period_from_filename(fid)}
        st._ext[fid] = ext
        if not ext.get("is_annual_summary"):
            exts.append(ext)

    canon = _canonical_fy_totals(exts)
    res = R.compute_risk_ratios(st)

    failures, checked = [], 0
    for r in res.get("trend", {}).get("ratios", []):
        for fy, comps in (r.get("components") or {}).items():
            for c in comps:
                label, val = c.get("label"), c.get("value")
                if label in canon and val is not None:
                    checked += 1
                    if abs(abs(val) - canon[label]) > 1.0:
                        failures.append(f"{r['name']} [{fy}] {label}: ratio={val:,.0f} vs MOM={canon[label]:,.0f}")

    print(f"Checked {checked} ratio source-numbers against canonical MOM totals.")
    if failures:
        print("FAIL — ratio sources diverge from the MOM table:")
        for f in failures: print("  -", f)
        return 1
    print("PASS — every ratio source number matches the MOM table total.")
    return 0


if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else "."
    raise SystemExit(check(folder))
