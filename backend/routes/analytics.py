"""Analytics route — Flask blueprint."""
from flask import Blueprint, jsonify
from store import store

analytics_bp = Blueprint("analytics", __name__)


@analytics_bp.get("/analytics")
def get_analytics():
    if not store.has_data():
        return jsonify(available=False, message="No file uploaded yet.")
    ctx = store.get_active_context()
    return jsonify(
        available=True,
        file_info=ctx["file_info"],
        analytics=ctx["analytics"],
        extracted_data={
            k: v for k, v in (ctx["extracted_data"] or {}).items()
            if not k.startswith("_")
        },
    )


@analytics_bp.get("/analytics/<file_id>")
def get_analytics_by_file(file_id):
    analytics = store.get_analytics(file_id)
    extracted = store.get_extracted_data(file_id)
    file_info = store.files.get(file_id)
    if analytics is None:
        return jsonify(error="File not found"), 404
    return jsonify(
        available=True,
        file_info=file_info,
        analytics=analytics,
        extracted_data={k: v for k, v in (extracted or {}).items() if not k.startswith("_")},
    )
