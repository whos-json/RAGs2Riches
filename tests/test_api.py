from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.api import create_app
from app.redaction import redact_text


def test_redact_text_removes_email_and_phone():
    text = "Reach jane.doe@example.com or +65 9123 4567 after 5pm"
    redacted = redact_text(text)
    assert "jane.doe@example.com" not in redacted
    assert "9123 4567" not in redacted
    assert "[EMAIL]" in redacted and "[PHONE]" in redacted


def test_stream_endpoint_emits_node_events_then_scorecard(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'api.db').as_posix()}")
    monkeypatch.setenv("SOURCE_XLSX", str(tmp_path / "missing.xlsx"))
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            response = client.post(
                "/api/evaluate/stream",
                json={"deal": {"industry": "Technology", "size_sqft": 4500}, "llm": {"provider": "template"}},
            )
            assert response.status_code == 200
            events = [
                json.loads(line[len("data: "):])
                for line in response.text.split("\n\n")
                if line.startswith("data: ")
            ]
    finally:
        get_settings.cache_clear()

    types = [e["type"] for e in events]
    assert types[0] == "run_start"
    assert types[-1] == "run_complete"
    assert "node_start" in types and "node_end" in types
