"""
Chat Service — Direct numeric answers + LLM for explanations.

AUDIT-SAFE: The system prompt forbids hallucination.
CRITICAL: LLM is ONLY for explanation/insights. Numeric answers come from analytics.
"""
import json
import logging
import re
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL    = "llama3:8b"
OLLAMA_TIMEOUT  = 120


# ── Direct numeric answer engine ──────────────────────────────────────────────

def _fmt_rupees(value: Optional[float]) -> str:
    if value is None:
        return "Not available in document"
    return f"₹{value:,.2f}"


def _fmt_pct(value: Optional[float]) -> str:
    if value is None:
        return "Not available in document"
    return f"{value:.2f}%"


def _total_tax_3b(d: Dict) -> Optional[float]:
    vals = [d.get("igst_on_sales"), d.get("cgst_on_sales"), d.get("sgst_on_sales")]
    valid = [v for v in vals if v is not None]
    return round(sum(valid), 2) if valid else None


def _total_itc_available(d: Dict) -> Optional[float]:
    vals = [d.get("itc_igst_available"), d.get("itc_cgst_available"), d.get("itc_sgst_available")]
    valid = [v for v in vals if v is not None]
    return round(sum(valid), 2) if valid else None


def _total_cash_paid(d: Dict) -> Optional[float]:
    vals = [d.get("cash_paid_igst"), d.get("cash_paid_cgst"), d.get("cash_paid_sgst")]
    valid = [v for v in vals if v is not None]
    return round(sum(valid), 2) if valid else None


def _total_itc_used(d: Dict) -> Optional[float]:
    vals = [d.get("itc_used_igst"), d.get("itc_used_cgst"), d.get("itc_used_sgst")]
    valid = [v for v in vals if v is not None]
    return round(sum(valid), 2) if valid else None


# Keyword patterns → answer generators
# Each entry: (regex_pattern, answer_builder_fn(extracted, analytics) -> str)
DIRECT_ANSWER_PATTERNS = [
    # Total taxable sales / turnover
    (
        r"total\s+(taxable\s+)?(sales|turnover|outward|revenue|supply|supplies)",
        lambda d, a: (
            f"**Total Taxable Sales**: {_fmt_rupees(d.get('taxable_sales') or d.get('total_taxable_value') or d.get('total_taxable_outward'))}\n\n"
            f"*(Source: Section 3.1(a) / HSN Summary — extracted directly from document)*"
        ),
    ),
    # Tax liability
    (
        r"(total\s+)?tax\s+(liability|payable|due)|total\s+gst",
        lambda d, a: (
            f"**Total Tax Liability**: {_fmt_rupees(_total_tax_3b(d))}\n\n"
            f"• IGST: {_fmt_rupees(d.get('igst_on_sales'))}\n"
            f"• CGST: {_fmt_rupees(d.get('cgst_on_sales'))}\n"
            f"• SGST/UTGST: {_fmt_rupees(d.get('sgst_on_sales'))}\n\n"
            f"*(Source: Section 3.1 — extracted directly from GSTR-3B)*"
        ),
    ),
    # IGST
    (
        r"\bigst\b",
        lambda d, a: (
            f"**IGST**: {_fmt_rupees(d.get('igst_on_sales') or d.get('total_igst'))}\n\n"
            f"*(Source: extracted directly from document)*"
        ),
    ),
    # CGST
    (
        r"\bcgst\b",
        lambda d, a: (
            f"**CGST**: {_fmt_rupees(d.get('cgst_on_sales') or d.get('total_cgst'))}\n\n"
            f"*(Source: extracted directly from document)*"
        ),
    ),
    # SGST
    (
        r"\bsgst\b|\butgst\b",
        lambda d, a: (
            f"**SGST/UTGST**: {_fmt_rupees(d.get('sgst_on_sales') or d.get('total_sgst'))}\n\n"
            f"*(Source: extracted directly from document)*"
        ),
    ),
    # ITC available
    (
        r"itc\s+(available|gross|total)|input\s+tax\s+credit\s+available",
        lambda d, a: (
            f"**ITC Available (Gross)**: {_fmt_rupees(_total_itc_available(d))}\n\n"
            f"• IGST ITC: {_fmt_rupees(d.get('itc_igst_available'))}\n"
            f"• CGST ITC: {_fmt_rupees(d.get('itc_cgst_available'))}\n"
            f"• SGST ITC: {_fmt_rupees(d.get('itc_sgst_available'))}\n\n"
            f"*(Source: Section 4(C) Net ITC Available — extracted from GSTR-3B)*"
        ),
    ),
    # ITC utilized / used
    (
        r"itc\s+(used|utilized|utilised)|input\s+tax.*used",
        lambda d, a: (
            f"**ITC Utilized**: {_fmt_rupees(_total_itc_used(d))}\n\n"
            f"*(Source: Section 6.1 — extracted from GSTR-3B)*"
        ),
    ),
    # Cash paid
    (
        r"cash\s+(paid|payment|outflow)|tax\s+paid.*cash",
        lambda d, a: (
            f"**Cash Payment**: {_fmt_rupees(_total_cash_paid(d))}\n\n"
            f"• IGST Cash: {_fmt_rupees(d.get('cash_paid_igst'))}\n"
            f"• CGST Cash: {_fmt_rupees(d.get('cash_paid_cgst'))}\n"
            f"• SGST Cash: {_fmt_rupees(d.get('cash_paid_sgst'))}\n\n"
            f"*(Source: Section 6.1 — extracted from GSTR-3B)*"
        ),
    ),
    # Interest
    (
        r"\binterest\b",
        lambda d, a: (
            f"**Interest Paid**: {_fmt_rupees(d.get('interest_paid'))}\n\n"
            f"*(Source: Section 5.1 — extracted from GSTR-3B)*"
        ),
    ),
    # Late fee
    (
        r"late\s+fee",
        lambda d, a: (
            f"**Late Fee Paid**: {_fmt_rupees(d.get('late_fee_paid'))}\n\n"
            f"*(Source: Section 5.1 — extracted from GSTR-3B)*"
        ),
    ),
    # B2B
    (
        r"\bb2b\b|business\s+to\s+business",
        lambda d, a: (
            f"**B2B Taxable Value**: {_fmt_rupees(d.get('b2b_taxable_value'))}\n\n"
            f"*(Source: Section 4A/4B/6B/6C — extracted from GSTR-1)*"
        ),
    ),
    # B2C / B2CS
    (
        r"\bb2c\b|business\s+to\s+consumer",
        lambda d, a: (
            f"**B2C Sales**:\n"
            f"• B2C Large (B2CL): {_fmt_rupees(d.get('b2cl_taxable_value'))}\n"
            f"• B2C Small (B2CS): {_fmt_rupees(d.get('b2cs_taxable_value'))}\n\n"
            f"*(Source: Sections 5A/5B and 7 — extracted from GSTR-1)*"
        ),
    ),
    # Credit notes
    (
        r"credit\s+note|cdn",
        lambda d, a: (
            f"**Credit/Debit Notes Value**: {_fmt_rupees(d.get('cdn_value'))}\n\n"
            f"*(Source: Section 9B — extracted from GSTR-1)*"
        ),
    ),
    # Export
    (
        r"\bexport",
        lambda d, a: (
            f"**Export Value**: {_fmt_rupees(d.get('export_value'))}\n\n"
            f"*(Source: Section 6A — extracted from GSTR-1)*"
        ),
    ),
    # GSTIN
    (
        r"\bgstin\b|gst\s+(number|registration)",
        lambda d, a: (
            f"**GSTIN**: {d.get('gstin') or 'Not found in document'}\n\n"
            f"*(Source: extracted from document header)*"
        ),
    ),
    # Period / filing period
    (
        r"\b(filing\s+)?period\b|which\s+month|tax\s+period",
        lambda d, a: (
            f"**Filing Period**: {d.get('period') or 'Not found in document'}\n\n"
            f"*(Source: extracted from document header)*"
        ),
    ),
]


def get_direct_answer(
    query: str,
    extracted_data: Dict,
    analytics: Dict,
) -> Optional[str]:
    """
    Try to answer a query directly from extracted data + analytics.
    Returns a formatted answer string, or None if LLM is needed.

    RULE: Only answers numeric/factual questions about extracted fields.
    For conceptual questions (explain, why, how), returns None → LLM handles.
    """
    query_lower = query.lower().strip()

    # Skip if clearly an explanation/conceptual question
    explanation_keywords = [
        r"explain|describe|what\s+is\s+an?|how\s+does|why|should\s+i|advice|recommend",
        r"summarize|summary|overview|tell\s+me\s+about|compare|difference\s+between",
    ]
    for pat in explanation_keywords:
        if re.search(pat, query_lower):
            logger.debug("[DirectAnswer] Skipping explanation query: %s", query_lower[:50])
            return None

    # Check against direct answer patterns
    for pattern, answer_fn in DIRECT_ANSWER_PATTERNS:
        if re.search(pattern, query_lower):
            try:
                answer = answer_fn(extracted_data, analytics)
                # Only return if the answer has actual data (not all "Not available")
                if "Not available in document" not in answer or any(
                    kpi.get("available") for kpi in analytics.get("kpis", [])
                ):
                    logger.info("[DirectAnswer] Matched pattern '%s' for query: %s", pattern, query_lower[:50])
                    return answer
            except Exception as exc:
                logger.exception("[DirectAnswer] Error building answer: %s", exc)
                return None

    # Also check KPI labels directly
    kpis = analytics.get("kpis", [])
    for kpi in kpis:
        label_lower = kpi.get("label", "").lower()
        # Check if query mentions the KPI label significantly
        label_words = [w for w in label_lower.split() if len(w) > 3]
        if label_words and all(w in query_lower for w in label_words[:2]):
            if kpi.get("available") and kpi.get("value") is not None:
                unit = kpi.get("unit", "₹")
                val = kpi["value"]
                if unit == "₹":
                    val_str = f"₹{val:,.2f}"
                elif unit == "%":
                    val_str = f"{val:.2f}%"
                elif unit == "x":
                    val_str = f"{val:.2f}x"
                else:
                    val_str = str(val)
                logger.info("[DirectAnswer] KPI match: %s = %s", kpi["label"], val_str)
                return f"**{kpi['label']}**: {val_str}\n\n*(Source: Computed from extracted document data)*"
            else:
                return f"**{kpi['label']}**: Not available in this document\n\n*(The relevant section was not found in the uploaded PDF)*"

    return None


# ── Context builder ───────────────────────────────────────────────────────────

def _fmt(value: Optional[float], unit: str = "₹") -> str:
    if value is None:
        return "NOT AVAILABLE IN DOCUMENT"
    if unit == "₹":
        return f"₹{value:,.2f}"
    if unit == "%":
        return f"{value:.2f}%"
    if unit == "x":
        return f"{value:.2f}x"
    return str(value)


def build_context(ctx: Dict[str, Any]) -> str:
    """Serialise extracted data + analytics into a plain-text context block."""
    file_info      = ctx.get("file_info", {}) or {}
    extracted_data = ctx.get("extracted_data", {}) or {}
    analytics      = ctx.get("analytics", {}) or {}
    reconciliation = ctx.get("reconciliation")

    lines = [
        "=" * 70,
        "GST DOCUMENT DATA — EXTRACTED AND VERIFIED",
        "=" * 70,
        f"Form Type  : {file_info.get('gst_type', 'UNKNOWN')}",
        f"File Name  : {file_info.get('filename', '')}",
        f"Period     : {extracted_data.get('period', 'NOT FOUND')}",
        f"GSTIN      : {extracted_data.get('gstin') or 'NOT FOUND'}",
        f"Entity Name: {extracted_data.get('legal_name') or 'NOT FOUND'}",
        "",
        "─" * 70,
        "KEY PERFORMANCE INDICATORS (computed from extracted data)",
        "─" * 70,
    ]

    kpis: List[Dict] = analytics.get("kpis", [])
    for k in kpis:
        val_str = _fmt(k.get("value"), k.get("unit", "₹"))
        lines.append(f"  {k['label']:<40} : {val_str}")

    lines += ["", "─" * 70, "RATIO ANALYSIS", "─" * 70]
    ratios: List[Dict] = analytics.get("ratios", [])
    for r in ratios:
        val_str = _fmt(r.get("value"), r.get("unit", "%"))
        bench   = f" (Benchmark: {r['benchmark']})" if r.get("benchmark") else ""
        lines.append(f"  {r['name']:<50} : {val_str}{bench}")

    lines += ["", "─" * 70, "SYSTEM-GENERATED INSIGHTS", "─" * 70]
    for i, ins in enumerate(analytics.get("insights", []), 1):
        lines.append(f"  {i}. {ins}")

    if reconciliation and reconciliation.get("available"):
        lines += ["", "─" * 70, "RECONCILIATION (GSTR-1 vs GSTR-3B)", "─" * 70]
        recon_status = reconciliation.get("summary", {}).get("status", "UNKNOWN")
        lines.append(f"  Status: {recon_status}")
        for item in reconciliation.get("items", []):
            flag = "⚠" if item.get("flag") else "✓"
            lines.append(
                f"  {flag} {item['label']:<30} | GSTR-1: {_fmt(item.get('gstr1'))} | "
                f"GSTR-3B: {_fmt(item.get('gstr3b'))} | Diff: {item.get('difference_pct', 'N/A')}%"
            )

    lines += ["", "─" * 70, "RAW EXTRACTED FIELDS (directly from PDF)", "─" * 70]
    for key, val in extracted_data.items():
        if key.startswith("_") or key in ("form_type", "period", "gstin", "legal_name"):
            continue
        lines.append(
            f"  {key:<40} : "
            f"{_fmt(val) if isinstance(val, (int, float)) else (val if val is not None else 'NOT FOUND')}"
        )

    if extracted_data.get("_parse_warnings"):
        lines += ["", "⚠ PARSE WARNINGS:"]
        for w in extracted_data["_parse_warnings"]:
            lines.append(f"  - {w}")

    lines.append("=" * 70)
    return "\n".join(lines)


# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a highly experienced Indian Chartered Accountant and GST compliance expert.
You are assisting a client by answering questions about their GST return documents.

CRITICAL RULES (non-negotiable):
1. ONLY use data from the "GST DOCUMENT DATA" block provided to you.
2. NEVER invent, guess, assume, or interpolate any numerical value.
3. If information is missing, say: "This data is not available in the provided document."
4. All monetary values must be stated with ₹ symbol and two decimal places.
5. For numeric answers, the system provides them directly — your role is explanation.
6. Structure responses as:
   **Summary**: One sentence answer.
   **Key Numbers**: Bullet points with exact figures.
   **Insights**: 2-3 observations based ONLY on available data.
7. Maintain a professional, audit-safe tone.
8. Do NOT perform arithmetic — all calculations are already done in the analytics.
"""


def build_prompt(query: str, context: str, chat_history: List[Dict]) -> str:
    """Build the full Ollama prompt with context and history."""
    history_text = ""
    recent = chat_history[-12:] if len(chat_history) > 12 else chat_history
    for msg in recent:
        role = "USER" if msg["role"] == "user" else "ASSISTANT"
        history_text += f"\n{role}: {msg['content']}"

    return f"""{SYSTEM_PROMPT}

{context}

CONVERSATION HISTORY:{history_text}

USER QUESTION: {query}

ASSISTANT:"""


# ── Ollama client ─────────────────────────────────────────────────────────────

async def check_ollama() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            if r.status_code == 200:
                models = [m["name"] for m in r.json().get("models", [])]
                return any(OLLAMA_MODEL.split(":")[0] in m for m in models)
    except Exception:
        pass
    return False


async def ask_ollama(prompt: str) -> str:
    """Send a prompt to Ollama and return the complete response."""
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "top_p": 0.9, "num_predict": 1024},
    }
    try:
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
            response = await client.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()
            return data.get("response", "").strip()
    except httpx.ConnectError:
        return (
            "⚠️ **Ollama is not running.**\n\n"
            "Start Ollama with: `ollama serve`\n"
            "Then pull the model: `ollama pull llama3:8b`\n\n"
            "**Note:** For numeric questions (tax, ITC, sales figures), I can answer directly "
            "without the AI model — just ask about specific values."
        )
    except httpx.TimeoutException:
        return "⚠️ The AI model took too long to respond. Try a shorter question."
    except Exception as exc:
        logger.exception("Ollama call failed: %s", exc)
        return f"⚠️ An error occurred while contacting the AI model: {str(exc)}"


async def ask_ollama_stream(prompt: str) -> AsyncGenerator[str, None]:
    """Stream response from Ollama token by token."""
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": True,
        "options": {"temperature": 0.1, "top_p": 0.9, "num_predict": 1024},
    }
    try:
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
            async with client.stream("POST", f"{OLLAMA_BASE_URL}/api/generate", json=payload) as response:
                async for line in response.aiter_lines():
                    if line:
                        try:
                            chunk = json.loads(line)
                            token = chunk.get("response", "")
                            if token:
                                yield token
                            if chunk.get("done"):
                                break
                        except json.JSONDecodeError:
                            continue
    except httpx.ConnectError:
        yield "⚠️ **Ollama is not running.** Start: `ollama serve` and pull: `ollama pull llama3:8b`"
    except Exception as exc:
        logger.exception("Ollama stream failed: %s", exc)
        yield f"⚠️ Error: {str(exc)}"
