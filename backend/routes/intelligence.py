"""Intelligence route — Risk ratios and DGARM-style analysis."""
import logging
from flask import Blueprint, jsonify
from store import store
from services.risk_engine import compute_risk_ratios

intelligence_bp = Blueprint("intelligence", __name__)
logger = logging.getLogger(__name__)


@intelligence_bp.get("/intelligence/ratios")
def get_risk_ratios():
    if not store.files:
        return jsonify(available=False, message="No files uploaded yet.")
    try:
        ratios = compute_risk_ratios(store)
        return jsonify(available=True, **ratios)
    except Exception as exc:
        logger.exception("Risk ratio computation failed: %s", exc)
        return jsonify(available=False, error=str(exc)), 500
