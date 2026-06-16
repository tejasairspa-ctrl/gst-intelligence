"""GSTR-2B route — Flask blueprint for GSTR-2B Excel compilation."""
import io
import logging
from datetime import datetime
from flask import Blueprint, request, send_file, jsonify

from services.gstr2b_compiler import compile_gstr2b

gstr2b_bp = Blueprint('gstr2b', __name__)
logger = logging.getLogger(__name__)

MAX_FILES = 12
MAX_MB    = 30


@gstr2b_bp.post('/gstr2b/compile')
def compile_route():
    files = request.files.getlist('files')
    if not files or (len(files) == 1 and files[0].filename == ''):
        return jsonify(error='No files provided'), 400

    if len(files) > MAX_FILES:
        return jsonify(error=f'Maximum {MAX_FILES} files allowed (one per month)'), 400

    file_streams = []
    for f in files:
        if not f.filename.lower().endswith('.xlsx'):
            return jsonify(error=f"'{f.filename}' is not an .xlsx file"), 400
        raw = f.read()
        if len(raw) > MAX_MB * 1024 * 1024:
            return jsonify(error=f"'{f.filename}' exceeds {MAX_MB} MB limit"), 400
        file_streams.append((f.filename, io.BytesIO(raw)))

    try:
        compiled = compile_gstr2b(file_streams)
    except ValueError as exc:
        logger.warning('GSTR-2B compile input error: %s', exc)
        return jsonify(error=str(exc)), 400
    except Exception as exc:
        logger.exception('GSTR-2B compile failed: %s', exc)
        return jsonify(error=f'Compilation failed: {exc}'), 500

    ts       = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_name = f'GSTR2B_Compiled_{ts}.xlsx'

    return send_file(
        io.BytesIO(compiled),
        as_attachment=True,
        download_name=out_name,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
