"""Syntax-check the inline script in app/static/index.html with node, and scan for emojis."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

HTML = Path(__file__).resolve().parent.parent / "app" / "static" / "index.html"
EMOJI = re.compile("[\U0001F000-\U0001FFFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]")
EMOJI_ENTITY = re.compile(r"&#(?:x[0-9a-fA-F]+|\d+);")


def main() -> int:
    text = HTML.read_text(encoding="utf-8")
    problems = []
    if EMOJI.search(text):
        problems.append("literal emoji or dingbat characters found")
    for entity in EMOJI_ENTITY.findall(text):
        code = int(entity[3:-1], 16) if entity[2] in "xX" else int(entity[2:-1])
        if code >= 0x2190:
            problems.append(f"symbol entity {entity} (U+{code:04X})")
    match = re.search(r"<script>(.*)</script>", text, re.S)
    if not match:
        problems.append("no inline script found")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            js = Path(tmp, "ui.js")
            js.write_text(match.group(1), encoding="utf-8")
            result = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
            if result.returncode != 0:
                problems.append("node --check failed:\n" + result.stderr)
    if problems:
        print("UI CHECK FAILED\n - " + "\n - ".join(problems))
        return 1
    print("UI CHECK PASSED: script parses, no emojis or symbol entities")
    return 0


if __name__ == "__main__":
    sys.exit(main())
