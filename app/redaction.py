from __future__ import annotations

import hashlib
import os
import re
import secrets
from typing import Optional

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
# Singapore NRIC / FIN, e.g. S1234567D
NRIC_RE = re.compile(r"\b[STFGM]\d{7}[A-Z]\b", re.IGNORECASE)
PHONE_RE = re.compile(r"\+?\d[\d\s-]{6,}\d")

# Alias hashes are salted so short, guessable names (properties) cannot be
# reversed with a dictionary. Set REDACTION_SALT for aliases that stay stable
# across restarts; otherwise a random per-process salt is used.
_PROCESS_SALT = secrets.token_hex(16)


def redact_text(text: Optional[str]) -> Optional[str]:
    """Basic redaction of emails, URLs, NRIC/FIN numbers and phone-like numbers.

    This is a minimum safeguard, not a full PII detector.
    """
    if not text:
        return None
    text = EMAIL_RE.sub("[EMAIL]", text)
    text = URL_RE.sub("[URL]", text)
    text = NRIC_RE.sub("[ID]", text)
    return PHONE_RE.sub("[PHONE]", text)


def alias(prefix: str, value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    salt = os.getenv("REDACTION_SALT") or _PROCESS_SALT
    digest = hashlib.sha256(f"{salt}:{value}".encode("utf-8")).hexdigest()[:8]
    return f"{prefix}-{digest}"
