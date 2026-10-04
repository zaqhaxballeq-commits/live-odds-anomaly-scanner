\
from __future__ import annotations

import logging
import os
import threading
import time

from flask import Flask, jsonify

from config import settings
from scanner import LiveScanner

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)

app = Flask(__name__)
scanner = LiveScanner(settings)

_thread: threading.Thread | None = None
_thread_lock = threading.Lock()


def ensure_scanner_started() -> None:
    global _thread
    if not settings.start_scanner:
        return
    with _thread_lock:
        if _thread and _thread.is_alive():
            return
        _thread = threading.Thread(target=scanner.run_forever, name="live-odds-scanner", daemon=True)
        _thread.start()


@app.get("/")
def root():
    ensure_scanner_started()
    return jsonify(
        {
            "service": "live-odds-anomaly-scanner",
            "mode": "LIVE_ONLY",
            "status": "ok",
            "scanner": scanner.status.to_dict(),
        }
    )


@app.get("/health")
def health():
    ensure_scanner_started()
    st = scanner.status.to_dict()
    healthy = not st.get("last_error") or scanner.status.running
    return jsonify(
        {
            "status": "ok" if healthy else "degraded",
            "mode": "LIVE_ONLY",
            "scanner": st,
            "telegram_configured": scanner.telegram.enabled,
            "min_alert_score": settings.min_alert_score,
            "scan_seconds": settings.scan_seconds,
            "unix_time": time.time(),
        }
    ), (200 if healthy else 503)


if settings.start_scanner:
    ensure_scanner_started()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
