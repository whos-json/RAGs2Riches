"""RAGS2Riches launcher: starts the local server and shows the UI in a native window.

Works both from source (`python launcher.py` / `pythonw launcher.py`) and as a
PyInstaller executable. Everything stays on 127.0.0.1. Writable data (SQLite DB,
uploads, launcher.log) lives in a `data` folder next to the executable so it
survives restarts.

The window is a pywebview (Edge WebView2) window. If it cannot open, the UI falls
back to an Edge app-mode window, then the default browser. Set RAGS2RICHES_NO_BROWSER=1 to run the
server only (used by scripts/smoke_test.py).
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
            try:
                sock.bind((HOST, port))
            except OSError:
                continue
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


def ensure_stdio(data_dir: Path) -> None:
    """pythonw.exe and windowed exes have no console; send output to a log file."""
    if sys.stdout is None or sys.stderr is None:
        log = open(data_dir / "launcher.log", "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = log
        if sys.stderr is None:
            sys.stderr = log


def show_error(message: str) -> None:
    """Report a startup failure where the user can see it, console or not."""
    print(message)
    if sys.stdin is not None and sys.stdin.isatty():
        input("Press Enter to close...")
    elif os.name == "nt":
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, "RAGS2Riches", 0x10)




def find_edge() -> str | None:
    for env in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            candidate = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if candidate.exists():
                return str(candidate)
    return None


def open_fallback(url: str) -> None:
    """Edge app-mode window if available, otherwise the default browser."""
    edge = find_edge()
    if edge:
        import subprocess

        subprocess.Popen([edge, f"--app={url}"])
    else:
        webbrowser.open(url)


def run_with_window(server, port: int) -> None:
    """Serve in a background thread and show the UI. Returns when the app should exit."""
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 120
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError("The server could not start. See data/launcher.log for details.")
        if time.monotonic() > deadline:
            server.should_exit = True
            raise RuntimeError("The server did not start in time. See data/launcher.log.")
        time.sleep(0.1)

    url = f"http://{HOST}:{port}/"
    try:
        import webview

        webview.create_window("RAGS2Riches", url, width=1280, height=860, min_size=(900, 600))
        webview.start()  # returns when the window is closed
    except Exception as exc:
        print(f"Native window unavailable ({type(exc).__name__}: {exc}); using a browser window instead.")
        open_fallback(url)
        thread.join()  # no window to close, so keep serving until the process is stopped
        return
    server.should_exit = True
    thread.join(timeout=5)


def main() -> int:
    configure_environment()
    ensure_stdio(app_home() / "data")
    port = find_free_port()
    print(f"RAGS2Riches starting on http://{HOST}:{port}/  (Ctrl+C to stop)", flush=True)
    print(f"Data folder: {app_home() / 'data'}", flush=True)
    source = os.environ.get("SOURCE_XLSX", "not found (use the Re-ingest button after adding one)")
    print(f"Source workbook: {source}", flush=True)

    import uvicorn

    from app.api import app

    config = uvicorn.Config(app, host=HOST, port=port, log_level="info")
    server = uvicorn.Server(config)

    if os.environ.get("RAGS2RICHES_NO_BROWSER"):
        server.run()
        return 0
    run_with_window(server, port)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as exc:
        show_error(f"RAGS2Riches failed to start: {type(exc).__name__}: {exc}")
        sys.exit(1)
