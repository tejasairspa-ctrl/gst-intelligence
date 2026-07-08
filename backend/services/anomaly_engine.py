"""Adaptive, peer-relative anomaly detection for GST figures and ratios.

Design (per user spec):
  • No fixed percentage threshold. Each metric is judged against ITS OWN normal
    behaviour (robust median + MAD), so the deviation is measured in units of that
    metric's own variability — a stable figure flags a small move, a volatile one
    only a big move.
  • The anomaly LINE is set by how the whole set of metrics is behaving that run:
    we take every metric-point's robust score and derive the cutoff from the
    distribution of those scores (median + 3·MAD of the scores), with a modest
    statistical floor. A point is flagged when it deviates far more than its peers.
  • Cross-factor consistency comes for free: the risk RATIOS (turnover↔tax,
    ITC↔turnover, cash↔liability …) are treated as metrics too, so a figure that
    moves out of step with its peers surfaces as a ratio anomaly, while a big move
    that is consistent across related factors does not fire.

Fully deterministic / explainable (audit-safe) — every flag carries the baseline,
the actual value, the % deviation and a plain-English reason.

Axes:
  • MOM — the chronological monthly series (whole uploaded range).
  • YOY — the per-financial-year series (FY totals for figures, FY value for ratios).
"""
from statistics import median
from typing import Dict, Any, List

from services import risk_engine as R

# Robust modified-z consistency constant (Iglewicz–Hoaglin).
_MODZ_K = 0.6745
# Statistical floor for "outlier" so an ultra-calm dataset doesn't over-flag.
_Z_FLOOR = 3.5
# Ignore moves below this rupee value (avoids flagging noise on near-zero series).
_MATERIALITY = 1000.0

# Key figures to monitor — (label, form, accessor, unit)
_FIGURES = [
    ("Total Taxable Turnover", "G1",  R.g1_total,             "₹"),
    ("B2B Sales",              "G1",  R.g1_b2b,               "₹"),
    ("B2C (Small) Sales",      "G1",  R.g1_b2cs,              "₹"),
    ("B2C (Large) Sales",      "G1",  R.g1_b2cl,              "₹"),
    ("Export Turnover",        "G1",  R._g1_export_turnover,  "₹"),
    ("Non-GST Supplies",       "G1",  R.g1_nongst,            "₹"),
    ("Credit Notes (CDNR+CDNUR)", "G1",
     lambda e: abs(R.g1_cdnr(e) or 0) + abs(R.g1_cdnur(e) or 0), "₹"),
    ("Output Taxable (3.1a)",  "G3B", lambda e: e.get("taxable_sales") or 0, "₹"),
    ("Output Tax Liability",   "G3B", lambda e: R._g3b_total_liab(e) or 0,   "₹"),
    ("ITC Availed (4A)",       "G3B", lambda e: R._g3b_itc_availed(e) or 0,  "₹"),
    ("ITC Reversed (4B)",      "G3B", lambda e: R._g3b_itc_reversed(e) or 0, "₹"),
    ("Cash Paid (6.1)",        "G3B", lambda e: R._g3b_cash_paid(e) or 0,    "₹"),
    ("RCM Liability (3.1d)",   "G3B", lambda e: e.get("s31d_rcm_taxable") or 0, "₹"),
]

# Figures whose value is meaningless in the old merged-B2B layout (FY 20-21/21-22).
_LEGACY_SKIP = {"B2B Sales"}


def _mad(vals: List[float], med: float) -> float:
    return median([abs(v - med) for v in vals]) if vals else 0.0


def _modz(v: float, med: float, mad: float) -> float:
    """Robust modified z-score; falls back to a scaled relative move when MAD=0."""
    if mad > 0:
        return _MODZ_K * (v - med) / mad
    # Constant history: only a material move counts, and it's a strong outlier.
    if abs(v - med) < _MATERIALITY:
        return 0.0
    return (_Z_FLOOR * 2.0) * (1 if v > med else -1)


def _fmt(v: float, unit: str) -> str:
    if unit == "₹":
        return f"₹{v:,.0f}"
    if unit == "%":
        return f"{v:.2f}%"
    return f"{v:,.2f}"


def _direction(v: float, med: float) -> str:
    if abs(med) < _MATERIALITY and abs(v) >= _MATERIALITY:
        return "appeared"
    if abs(v) < _MATERIALITY and abs(med) >= _MATERIALITY:
        return "ceased"
    return "increase" if v > med else "decrease"


def _pct(v: float, med: float):
    return ((v - med) / abs(med) * 100.0) if med else None


def _detect(series: Dict[str, dict], axis: str) -> List[dict]:
    """series: {label: {"unit":.., "points":[(key,value)..], "kind":"figure|ratio"}}.

    Returns anomaly dicts for the points that deviate far more than their peers.
    """
    scored = []
    for label, s in series.items():
        pts = [(k, float(v)) for k, v in s["points"] if v is not None]
        if len(pts) < 3:                       # too short to establish a norm
            continue
        vals = [v for _, v in pts]
        med = median(vals)
        mad = _mad(vals, med)
        # A ratio series that never moves, or a figure with no material spread, is skipped.
        if s["kind"] == "figure" and mad == 0 and max(abs(x) for x in vals) < _MATERIALITY:
            continue
        for k, v in pts:
            z = _modz(v, med, mad)
            if z != 0:
                scored.append({"label": label, "unit": s["unit"], "kind": s["kind"],
                               "key": k, "value": v, "median": med, "mad": mad, "z": z})
    if not scored:
        return []

    # Peer-relative cutoff: derived from the distribution of all |z| this run.
    allz = [abs(x["z"]) for x in scored]
    zmed = median(allz)
    cutoff = max(_Z_FLOOR, zmed + 3.0 * _mad(allz, zmed))

    out = []
    for x in scored:
        az = abs(x["z"])
        if az < cutoff:
            continue
        rel = az / cutoff                       # how far past the (adaptive) line
        severity = "HIGH" if rel >= 2.5 else ("MEDIUM" if rel >= 1.5 else "LOW")
        direction = _direction(x["value"], x["median"])
        pct = _pct(x["value"], x["median"])
        vfmt = _fmt(x["value"], x["unit"])
        mfmt = _fmt(x["median"], x["unit"])
        if direction == "appeared":
            reason = f"{x['label']} newly reported at {vfmt} (previously ~0)."
        elif direction == "ceased":
            reason = f"{x['label']} dropped to ~0 (usual ~{mfmt})."
        else:
            pj = f"{pct:+.0f}%" if pct is not None else "n/a"
            reason = (f"{x['label']} {vfmt} is {pj} vs its usual ~{mfmt} "
                      f"— {rel:.1f}× this run's anomaly line.")
        out.append({
            "axis": axis,
            "metric": x["label"],
            "kind": x["kind"],
            "period": x["key"],
            "value": round(x["value"], 2),
            "baseline": round(x["median"], 2),
            "unit": x["unit"],
            "deviation_pct": round(pct, 1) if pct is not None else None,
            "direction": direction,
            "score": round(az, 2),
            "cutoff": round(cutoff, 2),
            "severity": severity,
            "reason": reason,
        })
    # Most severe first, then largest score.
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    out.sort(key=lambda a: (order[a["severity"]], -a["score"]))
    return out


def _period_map(store):
    """{period: {"G1": ext, "G3B": ext}} excluding annual-summary files."""
    by = {}
    for fid, info in store.files.items():
        ext = store.get_extracted_data(fid)
        if not ext or ext.get("is_annual_summary"):
            continue
        p = info.get("period") or "Unknown Period"
        g = info.get("gst_type") or "?"
        if p in ("Unknown Period", "Period not found"):
            continue
        by.setdefault(p, {})["G1" if g == "GSTR-1" else "G3B" if g == "GSTR-3B" else g] = ext
    return by


def compute_anomalies(store) -> Dict[str, Any]:
    by_period = _period_map(store)
    periods = sorted(by_period, key=R._period_sort_key)

    # ── Figure series: MOM (per month) and YOY (per FY sum) ────────────────────
    mom_series: Dict[str, dict] = {}
    fy_buckets: Dict[str, Dict[str, list]] = {}   # {fy: {"G1":[ext..],"G3B":[ext..]}}
    for p in periods:
        fy = R._period_to_fy(p)
        for form in ("G1", "G3B"):
            ext = by_period[p].get(form)
            if ext:
                fy_buckets.setdefault(fy, {}).setdefault(form, []).append(ext)

    for label, form, fn, unit in _FIGURES:
        pts = []
        for p in periods:
            ext = by_period[p].get(form)
            if ext is None:
                continue
            if label in _LEGACY_SKIP and ext.get("legacy_combined_b2b"):
                continue
            try:
                pts.append((p, fn(ext) or 0))
            except Exception:
                pass
        if pts:
            mom_series[label] = {"unit": unit, "points": pts, "kind": "figure"}

    fys = sorted(fy_buckets, key=R._fy_sort_key)
    fy_agg = {}
    for fy in fys:
        agg = {}
        for form in ("G1", "G3B"):
            exts = fy_buckets[fy].get(form) or []
            if exts:
                a = R._sum_fields(exts)
                if any(e.get("legacy_combined_b2b") for e in exts):
                    a["legacy_combined_b2b"] = True
                agg[form] = a
        fy_agg[fy] = agg

    yoy_series: Dict[str, dict] = {}
    for label, form, fn, unit in _FIGURES:
        pts = []
        for fy in fys:
            a = fy_agg[fy].get(form)
            if a is None:
                continue
            if label in _LEGACY_SKIP and a.get("legacy_combined_b2b"):
                continue
            try:
                pts.append((fy, fn(a) or 0))
            except Exception:
                pass
        if pts:
            yoy_series[label] = {"unit": unit, "points": pts, "kind": "figure"}

    # ── Ratio series (cross-factor detectors) ──────────────────────────────────
    try:
        rd = R.compute_risk_ratios(store)
    except Exception:
        rd = {}
    # MOM ratio points come from each ratio's per-period breakdown.
    for sec in ("gstr1", "gstr3b", "cross"):
        for r in rd.get(sec, []):
            pv = [(p["period"], p["value"]) for p in (r.get("period_values") or [])
                  if p.get("value") is not None]
            if len(pv) >= 3:
                mom_series[f"[ratio] {r['name']}"] = {"unit": r.get("unit", "%"),
                                                      "points": pv, "kind": "ratio"}
    # YOY ratio points from the trend table.
    for r in rd.get("trend", {}).get("ratios", []):
        vals = r.get("values") or {}
        pv = [(fy, vals[fy]) for fy in sorted(vals, key=R._fy_sort_key)]
        if len(pv) >= 3:
            yoy_series[f"[ratio] {r['name']}"] = {"unit": r.get("unit", "%"),
                                                  "points": pv, "kind": "ratio"}

    mom = _detect(mom_series, "MOM")
    yoy = _detect(yoy_series, "YOY")

    def _counts(items):
        c = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for a in items:
            c[a["severity"]] += 1
        return c

    total = mom + yoy
    return {
        "mom": mom,
        "yoy": yoy,
        "summary": {
            "total": len(total),
            "high": sum(1 for a in total if a["severity"] == "HIGH"),
            "medium": sum(1 for a in total if a["severity"] == "MEDIUM"),
            "low": sum(1 for a in total if a["severity"] == "LOW"),
            "mom_counts": _counts(mom),
            "yoy_counts": _counts(yoy),
        },
        "has_anomalies": len(total) > 0,
    }
