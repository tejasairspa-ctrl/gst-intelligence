"""
GST Reconciliation Engine — Compares GSTR-1 vs GSTR-3B data.

AUDIT-SAFE: Only uses extracted data. Never assumes missing values.
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MISMATCH_THRESHOLD = 0.01  # 1% difference triggers a flag


def _diff_item(
    label: str,
    gstr1_val: Optional[float],
    gstr3b_val: Optional[float],
    threshold: float = MISMATCH_THRESHOLD,
) -> Optional[Dict]:
    """Create a single reconciliation comparison item."""
    if gstr1_val is None and gstr3b_val is None:
        return None  # Cannot compare if both missing

    item: Dict[str, Any] = {
        "label": label,
        "gstr1": gstr1_val,
        "gstr3b": gstr3b_val,
        "difference": None,
        "difference_pct": None,
        "flag": False,
        "note": "",
    }

    if gstr1_val is None:
        item["note"] = "GSTR-1 value not available"
        return item
    if gstr3b_val is None:
        item["note"] = "GSTR-3B value not available"
        return item

    diff = round(gstr1_val - gstr3b_val, 2)
    max_val = max(abs(gstr1_val), abs(gstr3b_val))
    pct = round(abs(diff / max_val) * 100, 2) if max_val > 0 else 0.0

    item["difference"] = diff
    item["difference_pct"] = pct
    item["flag"] = pct > threshold * 100

    if item["flag"]:
        direction = "excess in GSTR-1" if diff > 0 else "excess in GSTR-3B"
        item["note"] = f"₹{abs(diff):,.2f} {direction} ({pct:.2f}% gap)"
    else:
        item["note"] = "Reconciled within threshold"

    return item


def compute_reconciliation(
    gstr1_data: Optional[Dict],
    gstr3b_data: Optional[Dict],
    threshold: float = MISMATCH_THRESHOLD,
) -> Dict[str, Any]:
    """
    Compare GSTR-1 and GSTR-3B extracted data for the same period.
    Returns a structured reconciliation result.
    """
    result: Dict[str, Any] = {
        "available": False,
        "period": None,
        "gstr1_period": None,
        "gstr3b_period": None,
        "items": [],
        "flags": [],
        "summary": {
            "status": "INSUFFICIENT_DATA",
            "total_items": 0,
            "flagged_items": 0,
            "reconciled_items": 0,
        },
    }

    if not gstr1_data and not gstr3b_data:
        result["flags"].append("Both GSTR-1 and GSTR-3B data are missing")
        return result

    if gstr1_data:
        result["gstr1_period"] = gstr1_data.get("period")
        result["period"] = result["gstr1_period"]
    if gstr3b_data:
        result["gstr3b_period"] = gstr3b_data.get("period")
        result["period"] = result["gstr3b_period"]

    if not gstr1_data:
        result["flags"].append("GSTR-1 data not uploaded — upload GSTR-1 to enable reconciliation")
        return result

    if not gstr3b_data:
        result["flags"].append("GSTR-3B data not uploaded — upload GSTR-3B to enable reconciliation")
        return result

    result["available"] = True

    # ── Taxable Sales Comparison ───────────────────────────────────────────────
    gstr1_sales  = gstr1_data.get("total_taxable_value")
    gstr3b_sales = gstr3b_data.get("taxable_sales")

    item_sales = _diff_item("Taxable Sales (Outward)", gstr1_sales, gstr3b_sales, threshold)
    if item_sales:
        result["items"].append(item_sales)
        if item_sales["flag"]:
            result["flags"].append(
                f"⚠ SALES MISMATCH: GSTR-1 ₹{gstr1_sales:,.2f} vs GSTR-3B ₹{gstr3b_sales:,.2f} "
                f"({item_sales['difference_pct']:.2f}% gap)"
            )
        logger.info("[RECON] Sales: gstr1=%s gstr3b=%s diff=%s pct=%s flag=%s",
                    gstr1_sales, gstr3b_sales, item_sales.get("difference"),
                    item_sales.get("difference_pct"), item_sales["flag"])

    # ── IGST Comparison ───────────────────────────────────────────────────────
    gstr1_igst  = gstr1_data.get("total_igst")
    gstr3b_igst = gstr3b_data.get("igst_on_sales")
    item_igst = _diff_item("IGST", gstr1_igst, gstr3b_igst, threshold)
    if item_igst:
        result["items"].append(item_igst)
        if item_igst["flag"]:
            result["flags"].append(
                f"⚠ IGST MISMATCH: GSTR-1 ₹{gstr1_igst:,.2f} vs GSTR-3B ₹{gstr3b_igst:,.2f}"
            )

    # ── CGST Comparison ───────────────────────────────────────────────────────
    gstr1_cgst  = gstr1_data.get("total_cgst")
    gstr3b_cgst = gstr3b_data.get("cgst_on_sales")
    item_cgst = _diff_item("CGST", gstr1_cgst, gstr3b_cgst, threshold)
    if item_cgst:
        result["items"].append(item_cgst)

    # ── SGST Comparison ───────────────────────────────────────────────────────
    gstr1_sgst  = gstr1_data.get("total_sgst")
    gstr3b_sgst = gstr3b_data.get("sgst_on_sales")
    item_sgst = _diff_item("SGST/UTGST", gstr1_sgst, gstr3b_sgst, threshold)
    if item_sgst:
        result["items"].append(item_sgst)

    # ── Total Tax Comparison ──────────────────────────────────────────────────
    def safe_add(*vals):
        valid = [v for v in vals if v is not None]
        return round(sum(valid), 2) if valid else None

    gstr1_total_tax  = safe_add(gstr1_igst, gstr1_cgst, gstr1_sgst)
    gstr3b_total_tax = safe_add(gstr3b_igst, gstr3b_cgst, gstr3b_sgst)
    item_tax = _diff_item("Total Tax Liability", gstr1_total_tax, gstr3b_total_tax, threshold)
    if item_tax:
        result["items"].append(item_tax)
        if item_tax["flag"]:
            result["flags"].append(
                f"⚠ TAX MISMATCH: GSTR-1 total tax ₹{gstr1_total_tax:,.2f} "
                f"vs GSTR-3B ₹{gstr3b_total_tax:,.2f}"
            )

    # ── B2B comparison ────────────────────────────────────────────────────────
    item_b2b = _diff_item("B2B Taxable Value", gstr1_data.get("b2b_taxable_value"), None, threshold)
    # Note: GSTR-3B doesn't split by B2B/B2CS — so we just report from GSTR-1

    # ── Summary ───────────────────────────────────────────────────────────────
    flagged = sum(1 for item in result["items"] if item.get("flag"))
    reconciled = sum(
        1 for item in result["items"]
        if not item.get("flag")
        and item.get("difference") is not None
    )
    total = len(result["items"])

    result["summary"] = {
        "status": "MISMATCH" if flagged > 0 else ("RECONCILED" if total > 0 else "INSUFFICIENT_DATA"),
        "total_items": total,
        "flagged_items": flagged,
        "reconciled_items": reconciled,
    }

    if not result["flags"] and total > 0:
        result["flags"].append("✅ All comparable items are within the acceptable threshold — returns are reconciled.")

    logger.info("[RECON] Summary: status=%s flagged=%d/%d", result["summary"]["status"], flagged, total)
    return result
