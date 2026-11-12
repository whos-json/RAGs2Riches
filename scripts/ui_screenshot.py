"""Start the app from source and take headless Edge screenshots of the dashboard.

Usage: python scripts/ui_screenshot.py [outdir]
Screenshots: dashboard-empty.png, dashboard-answer.png, dashboard-narrow.png
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EDGES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def kill_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.kill()


def shoot(edge: str, url: str, out: Path, size: str, budget_ms: int) -> bool:
    profile = tempfile.mkdtemp(prefix="r2r_edge_")
    cmd = [
        edge, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={profile}",
        f"--window-size={size}", f"--virtual-time-budget={budget_ms}", f"--screenshot={out}", url,
    ]
    out.unlink(missing_ok=True)
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        # Headless browsers can linger after writing the file, so poll for it instead of waiting for exit.
        deadline = time.time() + 90
        while time.time() < deadline:
            if out.exists() and out.stat().st_size > 1000:
                time.sleep(1)
                break
            if proc.poll() is not None:
                break
            time.sleep(1)
    finally:
        kill_tree(proc)
    return out.exists() and out.stat().st_size > 1000


def main() -> int:
    outdir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "scratch" / "shots4"
    outdir.mkdir(parents=True, exist_ok=True)
    edge = next((p for p in EDGES if Path(p).exists()), None)
    if not edge:
        print("Edge not found")
        return 1
    tmp = tempfile.mkdtemp(prefix="r2r_ui_")
    env = dict(os.environ, RAGS2RICHES_NO_BROWSER="1", DATABASE_URL=f"sqlite:///{Path(tmp, 'ui.db').as_posix()}", INGEST_DIR=tmp)
    server = subprocess.Popen([sys.executable, str(ROOT / "launcher.py")], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        base = None
        deadline = time.time() + 150
        while time.time() < deadline and base is None:
            for port in range(8000, 8011):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/meta", timeout=10) as r:
                        meta = json.loads(r.read())
                        if meta.get("deal_count", 0) > 0:
                            base = f"http://127.0.0.1:{port}"
                            break
                except Exception:
                    continue
            else:
                time.sleep(2)
        if not base:
            print("server never became ready")
            return 1
        ok = [
            shoot(edge, f"{base}/", outdir / "dashboard-empty.png", "1500,1000", 8000),
            shoot(edge, f"{base}/#industry=Technology&size=4500&years=3", outdir / "dashboard-answer.png", "1500,1100", 15000),
            shoot(edge, f"{base}/#industry=Technology&size=4500&years=3", outdir / "dashboard-narrow.png", "420,1400", 15000),
        ]
        print("screenshots:", ok, "->", outdir)
        return 0 if all(ok) else 1
    finally:
        kill_tree(server)


if __name__ == "__main__":
    sys.exit(main())
