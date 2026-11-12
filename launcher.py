"""RAGS2Riches launcher: starts the local server and opens the browser.

Works both from source (`python launcher.py`) and as a PyInstaller executable.
Everything stays on 127.0.0.1. Writable data (SQLite DB, uploads) lives in a
`data` folder next to the executable so it survives restarts.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

HOST = "127.0.0.1"
PORT_RANGE = range(8000, 8011)
SEED_XLSX_NAME = "mock leasing data.xlsx"


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_home() -> Path:
    """Folder for writable runtime data (next to the exe, or the repo root)."""
    return Path(sys.executable).resolve().parent if frozen() else Path(__file__).resolve().parent


def resource_root() -> Path:
    """Folder holding bundled read-only files."""
    bundled = getattr(sys, "_MEIPASS", None)
    return Path(bundled) if bundled else Path(__file__).resolve().parent


def find_free_port() -> int:
    for port in PORT_RANGE:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex((HOST, port)) != 0:
                return port
    raise RuntimeError(f"No free port between {PORT_RANGE.start} and {PORT_RANGE.stop - 1}.")


def configure_environment() -> None:
    """Set defaults before `app` is imported. Existing environment values win."""
    data_dir = app_home() / "data"
    (data_dir / "uploads").mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{(data_dir / 'deals.db').as_posix()}")
    os.environ.setdefault("INGEST_DIR", str(data_dir / "uploads"))

    if "SOURCE_XLSX" not in os.environ:
        candidates = [
            data_dir / SEED_XLSX_NAME,
            resource_root() / "seed" / SEED_XLSX_NAME,
        ]
        for candidate in candidates:
            if candidate.exists():
                os.environ["SOURCE_XLSX"] = str(candidate)
                break


def open_browser_when_ready(port: int, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex((HOST, port)) == 0:
                webbrowser.open(f"http://{HOST}:{port}/")
                return
        time.sleep(0.3)


def main() -> int:
    configure_environment()
    port = find_free_port()
    print(f"RAGS2Riches starting on http://{HOST}:{port}/  (Ctrl+C to stop)")
    print(f"Data folder: {app_home() / 'data'}")
    print(f"Source workbook: {os.environ.get('SOURCE_XLSX', 'not found (use the Re-ingest button after adding one)')}")

    import uvicorn

    from app.api import app

    threading.Thread(target=open_browser_when_ready, args=(port,), daemon=True).start()
    uvicorn.run(app, host=HOST, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as exc:
        print(f"\nRAGS2Riches failed to start: {type(exc).__name__}: {exc}")
        input("Press Enter to close...")
        sys.exit(1)
