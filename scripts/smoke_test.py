"""End-to-end smoke test: start the launcher (source or exe) and exercise the live API.

Usage: python scripts/smoke_test.py [path-to-exe]
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_NODES = [
    "validate_input",
    "sql_baseline",
    "analogue_retrieval",
    "llm_synthesis",
    "assemble_scorecard",
]


def fetch(url: str, data: dict | None = None, timeout: float = 60):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode()


def main() -> int:
    exe = sys.argv[1] if len(sys.argv) > 1 else None
    cmd = [exe] if exe else [sys.executable, str(ROOT / "launcher.py")]
    tmp = tempfile.mkdtemp(prefix="r2r_smoke_")
    env = dict(os.environ)
    env["RAGS2RICHES_NO_BROWSER"] = "1"
    env["DATABASE_URL"] = f"sqlite:///{Path(tmp, 'smoke.db').as_posix()}"
    env["INGEST_DIR"] = tmp
    env["PYTHONUNBUFFERED"] = "1"

    # Windowed exes have no stdout, so discover the port by probing instead of parsing output.
    log_path = Path(tmp, "server.log")
    log_file = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log_file, stderr=subprocess.STDOUT)
    failures: list[str] = []
    try:
        port = None
        deadline = time.time() + 180
        while time.time() < deadline and port is None:
            if proc.poll() is not None:
                break
            for candidate in range(8000, 8011):
                try:
                    body = fetch(f"http://127.0.0.1:{candidate}/api/meta", timeout=15)[1]
                    if '"providers"' in body:
                        port = candidate
                        break
                except Exception:
                    continue
            else:
                time.sleep(1)
        if port is None:
            log_file.flush()
            print("FAIL: server did not become reachable\n" + log_path.read_text(encoding="utf-8", errors="replace")[-2000:])
            return 1
        base = f"http://127.0.0.1:{port}"

        for _ in range(120):
            try:
                if fetch(f"{base}/api/meta", timeout=5)[0] == 200:
                    break
            except Exception:
                time.sleep(1)
        else:
            print("FAIL: /api/meta never became ready")
            return 1

        status, page = fetch(f"{base}/")
        if status != 200 or "RAGS2Riches" not in page:
            failures.append("index page missing or wrong product name")

        meta = json.loads(fetch(f"{base}/api/meta")[1])
        if meta.get("deal_count", 0) < 1:
            failures.append(f"no deals loaded (deal_count={meta.get('deal_count')})")
        print(f"deals loaded: {meta.get('deal_count')}, providers: {[p['name'] for p in meta['providers']]}")

        _, stream = fetch(
            f"{base}/api/evaluate/stream",
            {"deal": {"industry": "Technology", "size_sqft": 4500, "lease_term_months": 36}, "llm": {"provider": "template"}},
        )
        events = [json.loads(chunk[6:]) for chunk in stream.split("\n\n") if chunk.startswith("data: ")]
        ended = [e["node"] for e in events if e["type"] == "node_end"]
        if ended != EXPECTED_NODES:
            failures.append(f"node order wrong: {ended}")
        if not events or events[-1]["type"] != "run_complete":
            failures.append(f"stream did not end with run_complete: {events[-1:] }")
        else:
            card = events[-1]["scorecard"]
            if card["estimates"]["win_probability_pct"] is not None:
                failures.append("win probability fabricated without outcome data")
            print("scorecard tier:", card["effort_allocation"]["tier"], "| comparables:", card["evidence"]["baseline"]["n_comparables"])
    finally:
        # A onefile exe is a bootloader plus a child process: kill the whole tree.
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        else:
            proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_file.close()

    if failures:
        print("SMOKE FAILED:\n - " + "\n - ".join(failures))
        return 1
    print("SMOKE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
