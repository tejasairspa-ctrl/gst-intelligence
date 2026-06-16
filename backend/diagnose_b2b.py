"""
Diagnostic: Check B2B and CDNR extracted values per period.
Run AFTER uploading files: python diagnose_b2b.py
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

from store import store

by_period = store.get_files_by_period()
if not by_period:
    print("❌ No files in store. Upload your PDFs first then run this.")
    sys.exit(1)

# Sort chronologically
MONTH_ORDER = {
    'january':1,'february':2,'march':3,'april':4,'may':5,'june':6,
    'july':7,'august':8,'september':9,'october':10,'november':11,'december':12
}
def sort_key(p):
    parts = p.lower().split()
    if len(parts) < 2: return (9999, 0)
    try: return (int(parts[1]), MONTH_ORDER.get(parts[0], 0))
    except: return (9999, 0)

print(f"\n{'='*95}")
print(f"{'Period':<22} {'Total Taxable':>16} {'B2B Taxable':>16} {'CDNR':>16} {'Ratio %':>10}  Flags")
print(f"{'='*95}")

fy_b2b  = {}
fy_cdnr = {}

for period in sorted(by_period.keys(), key=sort_key):
    g1_info = by_period[period].get('GSTR-1')
    if not g1_info:
        continue
    ext = store.get_extracted_data(g1_info['id'])
    if not ext:
        continue

    total = ext.get('total_taxable_value')
    b2b   = ext.get('b2b_taxable_value')
    cdnr  = ext.get('cdnr_taxable') or ext.get('cdn_value')
    warns = ext.get('_parse_warnings', [])

    ratio = None
    if b2b and cdnr is not None:
        ratio = round(abs(cdnr) / abs(b2b) * 100, 2) if b2b != 0 else None

    # Flags
    flags = []
    if b2b is None:       flags.append("⚠ B2B MISSING")
    if b2b == 0:          flags.append("⚠ B2B=0")
    if cdnr is None:      flags.append("⚠ CDNR MISSING")
    if ratio and ratio > 50: flags.append(f"🔴 HIGH RATIO {ratio}%")
    if warns:             flags.append(f"[{len(warns)} parser warnings]")

    # FY bucket
    parts = period.lower().split()
    if len(parts) >= 2:
        mo = MONTH_ORDER.get(parts[0], 0)
        yr = int(parts[1]) if parts[1].isdigit() else 0
        fy_start = yr - 1 if mo <= 3 else yr
        fy = f"FY {fy_start}-{str(fy_start+1)[-2:]}"
        fy_b2b.setdefault(fy, 0)
        fy_cdnr.setdefault(fy, 0)
        if b2b:  fy_b2b[fy]  += b2b
        if cdnr: fy_cdnr[fy] += abs(cdnr)

    def fmt(v):
        if v is None: return "MISSING"
        if abs(v) >= 1e7: return f"₹{v/1e7:.2f} Cr"
        if abs(v) >= 1e5: return f"₹{v/1e5:.2f} L"
        return f"₹{v:,.0f}"

    ratio_str = f"{ratio:.2f}%" if ratio is not None else "—"
    flag_str  = "  ".join(flags) if flags else "✓"

    print(f"{period:<22} {fmt(total):>16} {fmt(b2b):>16} {fmt(cdnr):>16} {ratio_str:>10}  {flag_str}")

print(f"\n{'='*95}")
print("FY-LEVEL AGGREGATED TOTALS")
print(f"{'='*95}")
print(f"{'FY':<15} {'B2B (sum)':>16} {'CDNR (sum)':>16} {'Ratio %':>10}")
print(f"{'-'*60}")
for fy in sorted(fy_b2b.keys()):
    b = fy_b2b.get(fy, 0)
    c = fy_cdnr.get(fy, 0)
    r = round(c / b * 100, 2) if b else None

    def fmt(v):
        if v >= 1e7: return f"₹{v/1e7:.2f} Cr"
        if v >= 1e5: return f"₹{v/1e5:.2f} L"
        return f"₹{v:,.0f}"

    print(f"{fy:<15} {fmt(b):>16} {fmt(c):>16} {str(round(r,2))+'%' if r else '—':>10}")
