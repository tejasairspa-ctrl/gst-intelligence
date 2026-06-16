"""Reconciliation route — Flask blueprint."""
import logging
from flask import Blueprint, jsonify, request
from store import store
from services.reconciliation import compute_reconciliation

recon_bp = Blueprint("reconciliation", __name__)
logger = logging.getLogger(__name__)


@recon_bp.get("/reconciliation")
def get_all_reconciliations():
    """Return all computed reconciliations."""
    return jsonify(
        reconciliations=store.get_all_reconciliations(),
        files_by_period=store.get_files_by_period(),
    )


@recon_bp.get("/reconciliation/<period>")
def get_reconciliation_by_period(period: str):
    """Return reconciliation for a specific period (URL-encoded)."""
    recon = store.get_reconciliation(period)
    if recon is None:
        # Try to compute on-the-fly
        gstr1  = store.get_gstr1_for_period(period)
        gstr3b = store.get_gstr3b_for_period(period)
        if gstr1 is None and gstr3b is None:
            return jsonify(error=f"No data found for period: {period}"), 404
        recon = compute_reconciliation(gstr1, gstr3b)
        store.set_reconciliation(period, recon)
    return jsonify(reconciliation=recon, period=period)


@recon_bp.post("/reconciliation/compute")
def compute_manual():
    """Manually trigger reconciliation for specific file IDs."""
    data = request.get_json() or {}
    gstr1_id  = data.get("gstr1_file_id")
    gstr3b_id = data.get("gstr3b_file_id")

    if not gstr1_id and not gstr3b_id:
        return jsonify(error="Provide gstr1_file_id and/or gstr3b_file_id"), 400

    gstr1_data  = store.get_extracted_data(gstr1_id)  if gstr1_id  else None
    gstr3b_data = store.get_extracted_data(gstr3b_id) if gstr3b_id else None

    try:
        recon = compute_reconciliation(gstr1_data, gstr3b_data)
        period = (gstr1_data or gstr3b_data or {}).get("period", "unknown")
        store.set_reconciliation(period, recon)
        return jsonify(reconciliation=recon, period=period)
    except Exception as exc:
        logger.exception("Reconciliation compute failed: %s", exc)
        return jsonify(error=str(exc)), 500
