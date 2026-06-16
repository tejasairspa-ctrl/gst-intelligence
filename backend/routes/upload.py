"""Upload route — Flask blueprint. Supports multi-file + auto-reconciliation."""
import os
import uuid
import logging
from flask import Blueprint, jsonify, request

from store import store
from services.pdf_parser import parse_gst_pdf, _extract_period_from_filename
from services.analytics_engine import run_analytics
from services.reconciliation import compute_reconciliation

upload_bp = Blueprint("upload", __name__)
logger = logging.getLogger(__name__)

MAX_MB = 50


@upload_bp.post("/upload")
def upload_pdf():
    if "file" not in request.files:
        return jsonify(error="No file provided"), 400

    f = request.files["file"]
    if not f.filename.lower().endswith(".pdf"):
        return jsonify(error="Only PDF files accepted"), 400

    content = f.read()
    if len(content) > MAX_MB * 1024 * 1024:
        return jsonify(error=f"File too large (max {MAX_MB} MB)"), 400

    file_id   = str(uuid.uuid4())
    save_path = os.path.join("uploads", f"{file_id}.pdf")
    with open(save_path, "wb") as fh:
        fh.write(content)

    try:
        extracted = parse_gst_pdf(save_path)
    except Exception as exc:
        logger.exception("Parse failed: %s", exc)
        return jsonify(error=f"PDF parsing failed: {exc}"), 500

    gst_type = extracted.get("form_type", "UNKNOWN")
    period   = extracted.get("period", "")

    # If the parser only got a financial-year string (e.g. "2023-24") but the
    # filename encodes the specific month, use the filename-derived period instead.
    # This gives the GST team "Apr 2023" instead of "2023-24" in the UI.
    import re as _re
    if not period or _re.match(r'^\d{4}-\d{2,4}$', period.strip()):
        name_period = _extract_period_from_filename(f.filename)
        if name_period:
            period = name_period
            extracted['period'] = period
            logger.info("[Upload] Period upgraded from filename '%s' → '%s'", f.filename, period)

    store.add_file(file_id, f.filename, gst_type, period)
    store.set_extracted_data(file_id, extracted)

    # ── Log key extracted values so we can confirm the parser output ──────────
    logger.info(
        "[Upload] EXTRACTED key fields — file=%s gst_type=%s period=%s | "
        "b2b_taxable=%s b2b_igst=%s b2b_cgst=%s b2b_sgst=%s | "
        "b2cs_taxable=%s b2cs_igst=%s b2cs_cgst=%s b2cs_sgst=%s | "
        "cdnur_taxable=%s cdnur_igst=%s cdnur_cgst=%s cdnur_sgst=%s | "
        "total_taxable=%s total_igst=%s total_cgst=%s total_sgst=%s",
        f.filename, gst_type, period,
        extracted.get("b2b_taxable_value"), extracted.get("b2b_igst"),
        extracted.get("b2b_cgst"),          extracted.get("b2b_sgst"),
        extracted.get("b2cs_taxable_value"), extracted.get("b2cs_igst"),
        extracted.get("b2cs_cgst"),          extracted.get("b2cs_sgst"),
        extracted.get("cdnur_taxable"),      extracted.get("cdnur_igst"),
        extracted.get("cdnur_cgst"),         extracted.get("cdnur_sgst"),
        extracted.get("total_taxable_value"), extracted.get("total_igst"),
        extracted.get("total_cgst"),          extracted.get("total_sgst"),
    )

    try:
        analytics = run_analytics(extracted)
    except Exception as exc:
        logger.exception("Analytics failed: %s", exc)
        analytics = {"error": str(exc), "kpis": [], "ratios": [], "insights": []}

    store.set_analytics(file_id, analytics)
    store.mark_file_ready(file_id)

    # ── Auto-reconciliation ────────────────────────────────────────────────────
    reconciliation = None
    reconciliation_triggered = False

    if gst_type in ("GSTR-1", "GSTR-3B") and period and period != "Period not found":
        counterpart_id = store.find_counterpart(file_id)
        if counterpart_id:
            counterpart_data = store.get_extracted_data(counterpart_id)
            counterpart_type = store.files.get(counterpart_id, {}).get("gst_type")

            if gst_type == "GSTR-1":
                gstr1_data  = extracted
                gstr3b_data = counterpart_data
            else:
                gstr1_data  = counterpart_data
                gstr3b_data = extracted

            try:
                reconciliation = compute_reconciliation(gstr1_data, gstr3b_data)
                store.set_reconciliation(period, reconciliation)
                reconciliation_triggered = True
                logger.info("Auto-reconciliation triggered for period=%s", period)
            except Exception as exc:
                logger.exception("Reconciliation failed: %s", exc)

    parse_ok = extracted.get("_parse_success", False)
    warnings = extracted.get("_parse_warnings", [])

    return jsonify(
        file_id=file_id,
        filename=f.filename,
        gst_type=gst_type,
        period=period,
        parse_success=parse_ok,
        parse_warnings=warnings,
        extracted_data={k: v for k, v in extracted.items() if not k.startswith("_")},
        analytics=analytics,
        reconciliation=reconciliation,
        reconciliation_triggered=reconciliation_triggered,
        message=(
            f"Successfully parsed {gst_type} for {period}" if parse_ok
            else "File uploaded with warnings. See parse_warnings."
        ),
    )


@upload_bp.get("/files")
def list_files():
    return jsonify(
        files=store.list_files(),
        files_by_period=store.get_files_by_period(),
    )


@upload_bp.post("/files/<file_id>/activate")
def activate_file(file_id):
    if file_id not in store.files:
        return jsonify(error="File not found"), 404
    store.set_active_file(file_id)
    return jsonify(status="activated", file_id=file_id)


@upload_bp.delete("/session")
def reset_session():
    """Clear all uploaded files, analytics, reconciliations and chat from the store."""
    store.clear_all()
    logger.info("[Session] Store cleared — new session started")
    return jsonify(status="cleared", message="Session reset. All files and data cleared.")
