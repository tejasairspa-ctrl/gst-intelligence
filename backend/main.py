"""
GST Intelligence API — Flask entry point (Python 3.14 compatible)
"""
import os
import logging
from flask import Flask
from flask_cors import CORS

from routes.upload         import upload_bp
from routes.chat           import chat_bp
from routes.analytics      import analytics_bp
from routes.export         import export_bp
from routes.reconciliation import recon_bp
from routes.intelligence   import intelligence_bp
from routes.gstr2b         import gstr2b_bp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(),                         # console
        logging.FileHandler("backend.log", encoding="utf-8"),  # file
    ],
)

# Also redirect print() to both console and log file so debug prints are captured
import sys, builtins as _builtins

# Reconfigure stdout/stderr to UTF-8 so PDF text containing ₹ (U+20B9)
# doesn't raise a charmap codec error on Windows when print() is called.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass  # Python < 3.7 or non-TextIOWrapper stdout

_log_file = open("backend.log", "a", encoding="utf-8", buffering=1)
_orig_print = _builtins.print
def _tee_print(*args, **kwargs):
    _orig_print(*args, **kwargs)
    kwargs.pop("file", None)
    _orig_print(*args, file=_log_file, **kwargs)
_builtins.print = _tee_print

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

os.makedirs("uploads", exist_ok=True)
os.makedirs("output",  exist_ok=True)

app.register_blueprint(upload_bp,       url_prefix="/api")
app.register_blueprint(chat_bp,         url_prefix="/api")
app.register_blueprint(analytics_bp,    url_prefix="/api")
app.register_blueprint(export_bp,       url_prefix="/api")
app.register_blueprint(recon_bp,        url_prefix="/api")
app.register_blueprint(intelligence_bp, url_prefix="/api")
app.register_blueprint(gstr2b_bp,       url_prefix="/api")


@app.get("/")
def root():
    return {"status": "running", "service": "GST Intelligence API", "version": "2.0.0"}


@app.get("/api/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
