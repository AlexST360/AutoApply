"""
dashboard_server.py — Servidor local para el dashboard interactivo.

Sirve el dashboard en http://localhost:8765 y expone una API mínima
para actualizar el estado de las ofertas directamente desde el browser.

Uso:  python main.py serve
"""

import json
import logging
import sqlite3
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from modules.tracker import generate_dashboard

logger = logging.getLogger(__name__)
PORT = 8765

ALLOWED_STATUSES = {"found", "scored", "candidate", "approved", "discarded", "applied", "skip", "error"}


def _set_status(job_id: int, status: str) -> bool:
    if status not in ALLOWED_STATUSES:
        return False
    con = sqlite3.connect(config.DB_PATH)
    try:
        con.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
        con.commit()
        return con.execute("SELECT changes()").fetchone()[0] > 0
    finally:
        con.close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # silenciar logs de cada request

    def _send(self, code: int, body: bytes, content_type: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/" or path == "/dashboard":
            # Regenerar y servir dashboard
            generate_dashboard()
            html = (config.DASHBOARD_DIR / "index.html").read_bytes()
            self._send(200, html, "text/html; charset=utf-8")

        elif path == "/api/jobs":
            con = sqlite3.connect(config.DB_PATH)
            con.row_factory = sqlite3.Row
            rows = con.execute("SELECT * FROM jobs ORDER BY date_found DESC, score DESC LIMIT 500").fetchall()
            con.close()
            body = json.dumps([dict(r) for r in rows], ensure_ascii=False, default=str).encode()
            self._send(200, body)

        else:
            self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        path = urlparse(self.path).path
        # POST /api/jobs/{id}/status   body: {"status": "approved"}
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "jobs" and parts[2].isdigit():
            job_id = int(parts[2])
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
                status = data.get("status", "")
                if _set_status(job_id, status):
                    self._send(200, b'{"ok":true}')
                else:
                    self._send(400, b'{"error":"invalid status or id"}')
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}).encode())
        else:
            self._send(404, b'{"error":"not found"}')


def run_server():
    generate_dashboard()
    server = HTTPServer(("localhost", PORT), Handler)
    url = f"http://localhost:{PORT}"
    logger.info("Dashboard en %s (Ctrl+C para detener)", url)
    print(f"\n  Dashboard abierto en {url}")
    print("  Ctrl+C para detener el servidor.\n")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Servidor detenido.")
