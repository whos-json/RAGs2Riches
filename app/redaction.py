from __future__ import annotations

import hashlib
import re
from typing import Optional

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"\+?\d[\d\s-]{6,}\d")


def redact_text(text: Optional[str]) -> Optional[str]:
    """Basic redaction of emails and phone-like numbers in free text.

    This is a minimum safeguard, not a full PII detector.
    """
    if not text:
        return None
    return PHONE_RE.sub("[PHONE]", EMAIL_RE.sub("[EMAIL]", text))


def alias(prefix: str, value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:6]
    return f"{prefix}-{digest}"
