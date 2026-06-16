"""
GST Analytics Engine — Pure Python, deterministic, audit-safe.

RULE: Every computed value comes ONLY from extracted_data.
      If any required field is None → the metric is None (never assumed/guessed).
"""
from typing import Any, Dict, List, Optional


# ── Safe arithmetic helpers ───────────────────────────────────────────────────

def _safe_add(*args: Optional[float]) -> Optional[float]:
    """Sum values; return None if ALL are None."""
    vals = [v for v in args if v is not None]
    return round(sum(vals), 2) if vals else None


def _safe_div(num: Optional[float], den: Optional[float]) -> Optional[float]:
    """Divide; return None if either operand is None or denominator is 0."""
    if num is None or den is None or den == 0:
        return None
    return round(num / den, 4)


def _pct(num: Optional[float], den: Optional[float]) -> Optional[float]:
    """Return percentage (0-100), rounded to 2 decimals."""
    v = _safe_div(num, den)
    return round(v * 100, 2) if v is not None else None


# ── Aggregation helpers ───────────────────────────────────────────────────────

def _total_tax_from_3b(d: Dict) -> Optional[float]:
    return _safe_add(d.get("igst_on_sales"), d.get("cgst_on_sales"), d.get("sgst_on_sales"))


def _total_itc_available_3b(d: Dict) -> Optional[float]:
    return _safe_add(
        d.get("itc_igst_available"),
        d.get("itc_cgst_available"),
        d.get("itc_sgst_available"),
    )


def _total_itc_reversed_3b(d: Dict) -> Optional[float]:
    return _safe_add(
        d.get("itc_reversed_igst"),
        d.get("itc_reversed_cgst"),
        d.get("itc_reversed_sgst"),
    )


def _total_itc_net_3b(d: Dict) -> Optional[float]:
    avail = _total_itc_available_3b(d)
    rev = _total_itc_reversed_3b(d)
    if avail is None:
        return None
    return _safe_add(avail, -(rev or 0))


def _total_itc_used_3b(d: Dict) -> Optional[float]:
    return _safe_add(
        d.get("itc_used_igst"),
        d.get("itc_used_cgst"),
        d.get("itc_used_sgst"),
    )


def _total_cash_paid_3b(d: Dict) -> Optional[float]:
    return _safe_add(
        d.get("cash_paid_igst"),
        d.get("cash_paid_cgst"),
        d.get("cash_paid_sgst"),
    )


# ── KPI computation ───────────────────────────────────────────────────────────

def compute_kpis(extracted_data: Dict) -> List[Dict]:
    d = extracted_data
    form = d.get("form_type", "UNKNOWN")

    kpis = []

    def kpi(label: str, value: Optional[float], unit: str = "₹", note: str = "") -> Dict:
        return {
            "label": label,
            "value": value,
            "unit": unit,
            "available": value is not None,
            "note": note if value is None else note,
        }

    if form == "GSTR-3B":
        total_tax = _total_tax_from_3b(d)
        itc_avail = _total_itc_available_3b(d)
        itc_net   = _total_itc_net_3b(d)
        itc_used  = _total_itc_used_3b(d)
        cash_paid = _total_cash_paid_3b(d)

        kpis = [
            kpi("Total Taxable Sales",     d.get("taxable_sales")),
            kpi("Total Tax Liability",     total_tax),
            kpi("IGST Liability",          d.get("igst_on_sales")),
            kpi("CGST Liability",          d.get("cgst_on_sales")),
            kpi("SGST/UTGST Liability",    d.get("sgst_on_sales")),
            kpi("ITC Available (Gross)",   itc_avail),
            kpi("ITC Reversed",            _total_itc_reversed_3b(d)),
            kpi("ITC Net Available",       itc_net),
            kpi("ITC Utilized",            itc_used),
            kpi("Cash Paid",               cash_paid),
            kpi("Interest Paid",           d.get("interest_paid"),   note="Not found in document"),
            kpi("Late Fee Paid",           d.get("late_fee_paid"),   note="Not found in document"),
        ]

    elif form == "GSTR-1":
        kpis = [
            kpi("Total Taxable Value",     d.get("total_taxable_value")),
            kpi("Total IGST",              d.get("total_igst")),
            kpi("Total CGST",              d.get("total_cgst")),
            kpi("Total SGST/UTGST",        d.get("total_sgst")),
            kpi("B2B Taxable Value",       d.get("b2b_taxable_value")),
            kpi("B2C (Large) Value",       d.get("b2cl_taxable_value")),
            kpi("B2C (Small) Value",       d.get("b2cs_taxable_value")),
            kpi("Export Value",            d.get("export_value")),
            kpi("Credit Notes Value",      d.get("cdn_value")),
        ]

    elif form == "GSTR-9":
        # Use detailed Part 4 / Part 6 fields if available, else fall back to aliases
        net_taxable = d.get("4N_Net_TaxPayable_TaxableValue") or d.get("total_taxable_outward")
        net_igst    = d.get("4N_Net_TaxPayable_IGST")         or d.get("taxable_outward_igst")
        net_cgst    = d.get("4N_Net_TaxPayable_CGST")         or d.get("taxable_outward_cgst")
        net_sgst    = d.get("4N_Net_TaxPayable_SGST")         or d.get("taxable_outward_sgst")
        total_tax   = _safe_add(net_igst, net_cgst, net_sgst)

        itc_igst    = d.get("6O_TotalITC_IGST") or d.get("itc_igst")
        itc_cgst    = d.get("6O_TotalITC_CGST") or d.get("itc_cgst")
        itc_sgst    = d.get("6O_TotalITC_SGST") or d.get("itc_sgst")
        itc_total   = _safe_add(itc_igst, itc_cgst, itc_sgst)
        itc_rev     = _safe_add(d.get("7I_Total_ITC_Reversed_IGST"), d.get("7I_Total_ITC_Reversed_CGST"), d.get("7I_Total_ITC_Reversed_SGST"))
        itc_net     = _safe_add(d.get("7J_NetITC_Utilizable_IGST"),  d.get("7J_NetITC_Utilizable_CGST"),  d.get("7J_NetITC_Utilizable_SGST"))

        cash_igst   = d.get("9A_IGST_Cash")
        cash_cgst   = d.get("9B_CGST_Cash")
        cash_sgst   = d.get("9C_SGST_Cash")
        total_cash  = _safe_add(cash_igst, cash_cgst, cash_sgst)

        final_tv    = d.get("FinalTurnover_5N_plus10_minus11_TaxableValue")
        b2b_tv      = d.get("4B_B2B_TaxableValue")
        b2c_tv      = d.get("4A_B2C_TaxableValue")
        cdn_tv      = d.get("4I_CreditNotes_TaxableValue")
        nil_tv      = d.get("5E_NilRated_TaxableValue")
        exempt_tv   = d.get("5D_Exempted_TaxableValue")
        nongst_tv   = d.get("5F_NonGST_TaxableValue")
        late_fee    = d.get("9F_LateFee_Cash")
        interest    = d.get("9E_Interest_Cash")
        gstr2a_itc  = _safe_add(d.get("8A_GSTR2A_ITC_IGST"), d.get("8A_GSTR2A_ITC_CGST"), d.get("8A_GSTR2A_ITC_SGST"))

        kpis = [
            kpi("Final Turnover (5N+10-11)",    final_tv),
            kpi("Net Taxable Outward (4N)",      net_taxable),
            kpi("Total Tax Payable",             total_tax),
            kpi("IGST Payable",                  d.get("9A_IGST_Payable")),
            kpi("CGST Payable",                  d.get("9B_CGST_Payable")),
            kpi("SGST Payable",                  d.get("9C_SGST_Payable")),
            kpi("Total ITC Availed (6O)",        itc_total),
            kpi("ITC from GSTR-3B (6A)",         _safe_add(d.get("6A_ITC_GSTR3B_IGST"), d.get("6A_ITC_GSTR3B_CGST"), d.get("6A_ITC_GSTR3B_SGST"))),
            kpi("GSTR-2A ITC Available (8A)",    gstr2a_itc),
            kpi("ITC Reversed (7I)",             itc_rev),
            kpi("Net ITC Utilizable (7J)",       itc_net),
            kpi("Cash Paid (Total)",             total_cash),
            kpi("B2B Taxable Supplies",          b2b_tv),
            kpi("B2C Taxable Supplies",          b2c_tv),
            kpi("Credit Notes (4I)",             cdn_tv),
            kpi("Nil-Rated Supplies",            nil_tv),
            kpi("Exempted Supplies",             exempt_tv),
            kpi("Non-GST Supplies",              nongst_tv),
            kpi("Late Fee Paid",                 late_fee),
            kpi("Interest Paid",                 interest),
        ]

    elif form == "GSTR-9C":
        kpis = [
            kpi("Turnover as per Books",   d.get("turnover_as_per_books")),
            kpi("Turnover as per GSTR-9",  d.get("turnover_as_per_gstr9")),
            kpi("Turnover Difference",     d.get("turnover_difference")),
            kpi("ITC as per Books",        d.get("itc_as_per_books")),
            kpi("ITC as per GSTR-3B",      d.get("itc_as_per_gstr3b")),
            kpi("ITC Difference",          d.get("itc_difference")),
        ]

    return kpis


# ── Ratio computation ─────────────────────────────────────────────────────────

def compute_ratios(extracted_data: Dict) -> List[Dict]:
    d = extracted_data
    form = d.get("form_type", "UNKNOWN")
    ratios = []

    def ratio(
        name: str,
        value: Optional[float],
        unit: str = "%",
        benchmark: Optional[str] = None,
        interpretation: str = "",
    ) -> Dict:
        return {
            "name": name,
            "value": value,
            "unit": unit,
            "available": value is not None,
            "benchmark": benchmark,
            "interpretation": interpretation,
        }

    if form == "GSTR-3B":
        taxable      = d.get("taxable_sales")
        total_tax    = _total_tax_from_3b(d)
        itc_avail    = _total_itc_available_3b(d)
        itc_net      = _total_itc_net_3b(d)
        itc_used     = _total_itc_used_3b(d)
        cash_paid    = _total_cash_paid_3b(d)
        itc_reversed = _total_itc_reversed_3b(d)

        # Tax-to-Sales ratio
        tax_ratio = _pct(total_tax, taxable)
        ratios.append(ratio(
            "Effective Tax Rate (Tax / Taxable Sales)",
            tax_ratio,
            benchmark="≈ Applicable GST rate slab (5%, 12%, 18%, 28%)",
            interpretation=(
                "Higher than applicable rate may indicate classification issues."
                if tax_ratio and tax_ratio > 18 else
                "Lower than expected may indicate ITC mismatch or under-reporting."
                if tax_ratio and tax_ratio < 5 else
                "Within typical range."
            ) if tax_ratio is not None else "",
        ))

        # ITC utilization ratio
        itc_util = _pct(itc_used, itc_avail)
        ratios.append(ratio(
            "ITC Utilization Ratio (Used / Available)",
            itc_util,
            benchmark="Higher is better; ~80–100% is optimal",
            interpretation=(
                "Good ITC utilization." if itc_util and itc_util >= 80 else
                "ITC under-utilization — review carry-forward strategy."
                if itc_util is not None else ""
            ),
        ))

        # ITC reversal ratio
        rev_ratio = _pct(itc_reversed, itc_avail)
        ratios.append(ratio(
            "ITC Reversal Ratio (Reversed / Available)",
            rev_ratio,
            benchmark="Lower is better; >20% warrants investigation",
            interpretation=(
                "High reversal — verify eligibility & supplier compliance."
                if rev_ratio and rev_ratio > 20 else
                "Reversal within acceptable range." if rev_ratio is not None else ""
            ),
        ))

        # Cash payment ratio
        cash_ratio = _pct(cash_paid, total_tax)
        ratios.append(ratio(
            "Cash Payment Ratio (Cash Paid / Total Tax)",
            cash_ratio,
            benchmark="Lower cash burden = better ITC management",
            interpretation=(
                "Predominantly cash-funded — ITC may be under-utilized."
                if cash_ratio and cash_ratio > 70 else
                "Healthy ITC offset against tax liability." if cash_ratio is not None else ""
            ),
        ))

        # ITC cover ratio (times)
        itc_cover = _safe_div(itc_net, total_tax)
        ratios.append(ratio(
            "ITC Cover Ratio (Net ITC / Tax Liability)",
            round(itc_cover, 2) if itc_cover is not None else None,
            unit="x",
            benchmark="> 1.0 means ITC exceeds liability",
            interpretation=(
                "ITC covers full liability with surplus." if itc_cover and itc_cover >= 1 else
                "ITC insufficient to cover full liability." if itc_cover is not None else ""
            ),
        ))

    elif form == "GSTR-1":
        total = d.get("total_taxable_value")
        cdn   = d.get("cdn_value")
        exp   = d.get("export_value")
        b2b   = d.get("b2b_taxable_value")

        ratios.append(ratio(
            "Credit Note Ratio (CDN / Total Sales)",
            _pct(cdn, total),
            benchmark="< 2% is typical",
            interpretation=(
                "High credit note ratio — review sales returns / disputes."
                if cdn and total and (cdn / total) > 0.02 else ""
            ),
        ))
        ratios.append(ratio(
            "Export Ratio (Exports / Total Sales)",
            _pct(exp, total),
            benchmark="Industry-specific",
        ))
        ratios.append(ratio(
            "B2B Ratio (B2B / Total Sales)",
            _pct(b2b, total),
            benchmark="Higher B2B = more ITC flowing to recipients",
        ))

    elif form == "GSTR-9C":
        bk  = d.get("turnover_as_per_books")
        g9  = d.get("turnover_as_per_gstr9")
        diff = d.get("turnover_difference")

        ratios.append(ratio(
            "Turnover Reconciliation Gap (Difference / Books Turnover)",
            _pct(diff, bk),
            benchmark="< 1% is acceptable",
            interpretation=(
                "Significant gap — investigate unreconciled transactions."
                if diff and bk and abs(diff / bk) > 0.01 else
                "Turnover well-reconciled." if diff is not None else ""
            ),
        ))

    return ratios


# ── Chart data ────────────────────────────────────────────────────────────────

def compute_chart_data(extracted_data: Dict) -> Dict[str, List[Dict]]:
    d = extracted_data
    form = d.get("form_type", "UNKNOWN")

    def pt(label: str, value: Optional[float]) -> Dict:
        return {"label": label, "value": value}

    tax_dist, itc_breakdown, sales_breakdown = [], [], []

    if form == "GSTR-3B":
        tax_dist = [
            pt("IGST", d.get("igst_on_sales")),
            pt("CGST", d.get("cgst_on_sales")),
            pt("SGST/UTGST", d.get("sgst_on_sales")),
        ]
        tax_dist = [p for p in tax_dist if p["value"] is not None]

        avail = _total_itc_available_3b(d)
        rev   = _total_itc_reversed_3b(d)
        used  = _total_itc_used_3b(d)
        itc_breakdown = [
            pt("ITC Available", avail),
            pt("ITC Reversed",  rev),
            pt("ITC Used",      used),
        ]
        itc_breakdown = [p for p in itc_breakdown if p["value"] is not None]

        sales_breakdown = [
            pt("Taxable Sales",   d.get("taxable_sales")),
            pt("Zero-Rated",      d.get("zero_rated_sales")),
            pt("Nil-Rated",       d.get("nil_rated_sales")),
            pt("Exempt",          d.get("exempt_sales")),
        ]
        sales_breakdown = [p for p in sales_breakdown if p["value"] is not None]

    elif form == "GSTR-1":
        sales_breakdown = [
            pt("B2B",    d.get("b2b_taxable_value")),
            pt("B2CL",   d.get("b2cl_taxable_value")),
            pt("B2CS",   d.get("b2cs_taxable_value")),
            pt("Exports", d.get("export_value")),
        ]
        sales_breakdown = [p for p in sales_breakdown if p["value"] is not None]

        tax_dist = [
            pt("IGST", d.get("total_igst")),
            pt("CGST", d.get("total_cgst")),
            pt("SGST/UTGST", d.get("total_sgst")),
        ]
        tax_dist = [p for p in tax_dist if p["value"] is not None]

    elif form == "GSTR-9":
        tax_dist = [
            pt("IGST", d.get("taxable_outward_igst")),
            pt("CGST", d.get("taxable_outward_cgst")),
            pt("SGST/UTGST", d.get("taxable_outward_sgst")),
        ]
        tax_dist = [p for p in tax_dist if p["value"] is not None]

        itc_breakdown = [
            pt("ITC-IGST", d.get("itc_igst")),
            pt("ITC-CGST", d.get("itc_cgst")),
            pt("ITC-SGST", d.get("itc_sgst")),
        ]
        itc_breakdown = [p for p in itc_breakdown if p["value"] is not None]

    elif form == "GSTR-9C":
        sales_breakdown = [
            pt("Books Turnover",  d.get("turnover_as_per_books")),
            pt("GSTR-9 Turnover", d.get("turnover_as_per_gstr9")),
        ]
        sales_breakdown = [p for p in sales_breakdown if p["value"] is not None]

        itc_breakdown = [
            pt("ITC (Books)",  d.get("itc_as_per_books")),
            pt("ITC (GSTR-3B)", d.get("itc_as_per_gstr3b")),
        ]
        itc_breakdown = [p for p in itc_breakdown if p["value"] is not None]

    return {
        "tax_distribution": tax_dist,
        "itc_breakdown": itc_breakdown,
        "sales_breakdown": sales_breakdown,
    }


# ── Insights ──────────────────────────────────────────────────────────────────

def generate_insights(extracted_data: Dict, ratios: List[Dict], kpis: List[Dict]) -> List[str]:
    """
    Generate text insights based STRICTLY on extracted data and computed ratios.
    No assumptions — insight is skipped if data is missing.
    """
    d = extracted_data
    form = d.get("form_type", "UNKNOWN")
    insights = []

    # Helper: get ratio value by name
    def get_ratio(name_fragment: str) -> Optional[float]:
        for r in ratios:
            if name_fragment.lower() in r["name"].lower():
                return r.get("value")
        return None

    if form == "GSTR-3B":
        tax_rate = get_ratio("Effective Tax Rate")
        if tax_rate is not None:
            insights.append(
                f"Effective GST rate on taxable sales is {tax_rate:.2f}%. "
                f"Compare with applicable rate slabs for compliance check."
            )

        itc_util = get_ratio("ITC Utilization Ratio")
        if itc_util is not None:
            if itc_util >= 90:
                insights.append(f"ITC utilization is excellent at {itc_util:.1f}% — minimal carry-forward.")
            elif itc_util >= 70:
                insights.append(f"ITC utilization is {itc_util:.1f}% — moderate carry-forward balance exists.")
            else:
                insights.append(
                    f"ITC utilization is low at {itc_util:.1f}%. "
                    f"Review eligible ITC and consider optimizing working capital."
                )

        rev_ratio = get_ratio("ITC Reversal Ratio")
        if rev_ratio is not None and rev_ratio > 10:
            insights.append(
                f"ITC reversal ratio of {rev_ratio:.1f}% is notable. "
                f"Verify supplier GSTIN compliance and eligibility of reversed credits."
            )

        cash_ratio = get_ratio("Cash Payment Ratio")
        if cash_ratio is not None:
            insights.append(
                f"Cash payment ratio is {cash_ratio:.1f}% of total tax liability. "
                + ("High cash outflow — consider ITC optimization." if cash_ratio > 50 else
                   "ITC is effectively offsetting cash outflows.")
            )

        late_fee = d.get("late_fee_paid")
        if late_fee is not None and late_fee > 0:
            insights.append(
                f"Late fee of ₹{late_fee:,.2f} was paid. Review filing timelines."
            )

        interest = d.get("interest_paid")
        if interest is not None and interest > 0:
            insights.append(
                f"Interest of ₹{interest:,.2f} was paid — indicates delayed payment or short payment."
            )

    elif form == "GSTR-1":
        cdn_ratio = get_ratio("Credit Note Ratio")
        if cdn_ratio is not None:
            if cdn_ratio > 5:
                insights.append(
                    f"Credit note ratio is high at {cdn_ratio:.1f}% of total sales. "
                    f"Investigate causes of sales returns or price adjustments."
                )
            else:
                insights.append(f"Credit note ratio of {cdn_ratio:.1f}% is within normal range.")

        exp_ratio = get_ratio("Export Ratio")
        if exp_ratio is not None and exp_ratio > 0:
            insights.append(
                f"Exports constitute {exp_ratio:.1f}% of total supplies. "
                f"Ensure LUT/bond compliance for zero-rated exports."
            )

    elif form == "GSTR-9C":
        diff = d.get("turnover_difference")
        if diff is not None and abs(diff) > 0:
            insights.append(
                f"Turnover difference of ₹{abs(diff):,.2f} between books and GSTR-9 "
                f"{'excess in books' if diff > 0 else 'excess in GSTR-9'}. Reconcile before filing."
            )
        itc_diff = d.get("itc_difference")
        if itc_diff is not None and abs(itc_diff) > 0:
            insights.append(
                f"ITC difference of ₹{abs(itc_diff):,.2f} detected. "
                f"Audit ITC ledger against GSTR-3B filings."
            )

    if not insights:
        insights.append(
            "Limited data extracted. Ensure the uploaded PDF is a text-based GST portal document."
        )

    return insights


# ── Master analytics function ─────────────────────────────────────────────────

def run_analytics(extracted_data: Dict) -> Dict[str, Any]:
    """
    Compute all analytics from extracted data.
    Returns a structured analytics dict.
    """
    kpis    = compute_kpis(extracted_data)
    ratios  = compute_ratios(extracted_data)
    charts  = compute_chart_data(extracted_data)
    insights = generate_insights(extracted_data, ratios, kpis)

    return {
        "form_type": extracted_data.get("form_type", "UNKNOWN"),
        "period":    extracted_data.get("period", ""),
        "gstin":     extracted_data.get("gstin"),
        "kpis":      kpis,
        "ratios":    ratios,
        "charts":    charts,
        "insights":  insights,
    }
