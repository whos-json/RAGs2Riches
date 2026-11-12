"""Local web server for the Deal Intelligence & Sales Copilot.

Serves the web UI and a JSON API:
  GET  /api/health         service status
  GET  /api/options        form choices shared with the engine
  POST /api/evaluate-deal  returns the Structured Deal Scorecard

Uses only the Python standard library so it packages into one Windows .exe.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from engine import OPTIONS, load_history, score_deal

MAX_BODY_BYTES = 64 * 1024


def resource_dir() -> Path:
    # PyInstaller unpacks bundled files into sys._MEIPASS at runtime.
    bundled = getattr(sys, "_MEIPASS", None)
    return Path(bundled) if bundled else Path(__file__).resolve().parent


BASE_DIR = resource_dir()
WEB_DIR = BASE_DIR / "web"
HISTORY = load_history(BASE_DIR / "data" / "historical_deals.json")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def do_GET(self) -> None:
        if self.path == "/api/health":
            self._send_json(200, {"status": "ok", "historical_deals": len(HISTORY)})
        elif self.path == "/api/options":
            self._send_json(200, OPTIONS)
        elif self.path.startswith("/api/"):
            self._send_json(404, {"error": "Not found."})
        else:
            super().do_GET()

    def do_POST(self) -> None:
        if self.path != "/api/evaluate-deal":
            self._send_json(404, {"error": "Not found."})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY_BYTES:
            self._send_json(400, {"error": "Request body is missing or too large."})
            return
        try:
            payload = json.loads(self.rfile.read(length))
            result = score_deal(payload, HISTORY)
        except json.JSONDecodeError:
            self._send_json(400, {"error": "Request body must be valid JSON."})
            return
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, result)

    def _send_json(self, status: int, body: Any) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    parser = argparse.ArgumentParser(description="Deal Intelligence & Sales Copilot")
    parser.add_argument("--port", type=int, default=8765, help="first port to try (default 8765)")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    args = parser.parse_args()

    server = None
    for port in range(args.port, args.port + 10):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    if server is None:
        sys.exit(f"Could not bind to any port from {args.port} to {args.port + 9}.")

    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Deal Intelligence & Sales Copilot is running at {url}")
    print("Close this window or press Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.8, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
