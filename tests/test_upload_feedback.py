"""Upload, portfolio, feedback and meta endpoints. No network access needed."""

from __future__ import annotations

import io

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.api as api_mod
from app import llm as llm_mod
from app.api import create_app
from app.config import get_settings
from app.db import Deal, Feedback, make_engine, session_factory


@pytest.fixture
def env(tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'uf.db').as_posix()}")
    monkeypatch.setenv("SOURCE_XLSX", str(tmp_path / "source.xlsx"))
    monkeypatch.setenv("INGEST_DIR", str(uploads))
    get_settings.cache_clear()
    llm_mod.reset_probe_cache()
    yield tmp_path
    get_settings.cache_clear()
    llm_mod.reset_probe_cache()


@pytest.fixture
def client(env):
    with TestClient(create_app()) as test_client:
        yield test_client


def _workbook_bytes() -> bytes:
    frame = pd.DataFrame(
        {
            "Deal Name": ["A", "A", "B"],
            "Account Name": ["Acme", "Acme", "Beta"],
            "Leasing Industry": ["Tech", "Tech", "Finance"],
            "Size (sq/ft)": [1000, 1000, 9000],
            "Lease Term": ["3 years", "3 years", "2 years"],
            "Role": ["Lead Broker", "Support", "Lead Broker"],
            "Agent Name": ["X", "Y", "X"],
            "Deal Done Date": ["01/02/2025", "01/02/2025", "03/04/2025"],
            "Gross Signing Rent (psf/mth)": [5.0, 5.0, 6.0],
            "Gross Fee (SGD)": [100.0, 100.0, 200.0],
            "Net Fee Collected": [90.0, 90.0, 180.0],
            "Property Name": ["P1", "P1", "P2"],
            "Billing Status": ["Billed", "Billed", "Not billed"],
            "Billing FY Year": [2025, 2025, 2025],
            "Lease Expiry Date": ["01/02/2028", "01/02/2028", None],
        }
    )
    buffer = io.BytesIO()
    frame.to_excel(buffer, index=False)
    return buffer.getvalue()


def _upload(client, name: str, body: bytes, **kwargs):
    return client.post(
        "/api/upload",
        params={"filename": name},
        content=body,
        headers={"content-type": "application/octet-stream", **kwargs.pop("headers", {})},
        **kwargs,
    )


def _saved_files(env) -> list[str]:
    return sorted(p.name for p in (env / "uploads").iterdir())


# --- /api/upload ------------------------------------------------------------------------------


def test_upload_happy_path_ingests_and_populates_portfolio(client, env):
    response = _upload(client, "Q1 leasing (final).xlsx", _workbook_bytes())
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "Q1 leasing (final).xlsx"
    assert body["deals_loaded"] == 2 and body["source_rows"] == 3
    assert _saved_files(env) == ["Q1 leasing (final).xlsx"]
    assert client.get("/api/meta").json()["has_data"] is True

    portfolio = client.get("/api/portfolio").json()
    assert portfolio["totals"]["deals"] == 2
    assert portfolio["totals"]["total_fee_sgd"] == 300.0
    assert portfolio["lease_expiry"]["n_with_expiry"] == 1


def test_upload_existing_name_gets_numeric_suffix(client, env):
    first = _upload(client, "data.xlsx", _workbook_bytes())
    second = _upload(client, "data.xlsx", _workbook_bytes())
    assert first.json()["source"] == "data.xlsx"
    assert second.json()["source"] == "data_1.xlsx"
    assert _saved_files(env) == ["data.xlsx", "data_1.xlsx"]


@pytest.mark.parametrize("name", ["data.csv", "data.xlsx.exe", "data", "..", ".xlsx", "a;b.xlsx", "a\u0000.xlsx", "CON.xlsx"])
def test_upload_rejects_bad_names(client, env, name):
    response = _upload(client, name, _workbook_bytes())
    assert response.status_code == 400
    assert _saved_files(env) == []


def test_upload_rejects_non_zip_content(client, env):
    response = _upload(client, "fake.xlsx", b"not a workbook at all")
    assert response.status_code == 400
    assert _saved_files(env) == []


def test_upload_rejects_empty_body(client, env):
    assert _upload(client, "empty.xlsx", b"").status_code == 400


def test_upload_rejects_oversized_content_length(client, env, monkeypatch):
    monkeypatch.setattr(api_mod, "MAX_INGEST_BYTES", 1024)
    response = _upload(client, "big.xlsx", b"PK\x03\x04" + b"x" * 2048)
    assert response.status_code == 413
    assert _saved_files(env) == []


def test_upload_declared_length_is_checked_before_body_is_read(client, env):
    response = _upload(client, "big.xlsx", b"PK\x03\x04", headers={"content-length": str(api_mod.MAX_INGEST_BYTES + 1)})
    assert response.status_code == 413


def test_upload_requires_valid_content_length(client, env):
    chunked = client.post("/api/upload", params={"filename": "a.xlsx"}, content=iter([b"PK\x03\x04abc"]))
    assert chunked.status_code == 411
    invalid = _upload(client, "a.xlsx", b"PK\x03\x04", headers={"content-length": "abc"})
    assert invalid.status_code == 400


@pytest.mark.parametrize("name", ["../../evil.xlsx", "..\\..\\evil.xlsx", "/etc/evil.xlsx", "C:\\temp\\evil.xlsx"])
def test_upload_traversal_names_are_reduced_to_basename(client, env, name):
    response = _upload(client, name, _workbook_bytes())
    assert response.status_code == 200
    assert response.json()["source"] == "evil.xlsx"
    assert _saved_files(env) == ["evil.xlsx"]
    assert not (env / "evil.xlsx").exists()


def test_upload_ingest_failure_deletes_file_and_hides_internals(client, env):
    response = _upload(client, "broken.xlsx", b"PK\x03\x04 this is not really a workbook")
    assert response.status_code == 422
    assert "Error" not in response.text and "broken" not in response.text and "uploads" not in response.text
    assert _saved_files(env) == []



# --- /api/portfolio and /api/meta -------------------------------------------------------------


def test_portfolio_on_empty_db_is_valid(client):
    response = client.get("/api/portfolio")
    assert response.status_code == 200
    body = response.json()
    assert body["totals"]["deals"] == 0 and body["totals"]["median_fee_sgd"] is None
    assert body["by_industry"] == [] and len(body["seasonality"]["by_month"]) == 12


def test_meta_has_data_flag_and_existing_keys(client):
    meta = client.get("/api/meta").json()
    assert meta["has_data"] is False and meta["deal_count"] == 0
    assert {"providers", "industries", "deal_count", "default_llm"} <= set(meta)


# --- /api/feedback ----------------------------------------------------------------------------


def _db_session():
    return session_factory(make_engine())()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"deal_id": "D1"},
        {"deal_id": "", "outcome": "WON"},
        {"deal_id": "   ", "outcome": "WON"},
        {"deal_id": "x" * 256, "outcome": "WON"},
        {"deal_id": "D1", "outcome": "MAYBE"},
        {"deal_id": "D1", "note": "x" * 501},
        {"deal_id": "D1", "note": " \x00\n\t "},
    ],
)
def test_feedback_validation_rejects_bad_payloads(client, payload):
    assert client.post("/api/feedback", json=payload).status_code == 422
    assert client.get("/api/feedback/summary").json()["total"] == 0


def test_feedback_is_stored_and_summarised(client):
    assert client.get("/api/feedback/summary").json() == {
        "total": 0, "by_outcome": {"WON": 0, "LOST": 0, "DROPPED": 0}, "useful_yes": 0, "useful_no": 0,
    }
    for payload in (
        {"deal_id": "D1", "outcome": "WON"},
        {"deal_id": "D2", "outcome": "LOST", "useful": False},
        {"deal_id": "D3", "outcome": "DROPPED", "useful": True},
        {"deal_id": "D4", "useful": True, "note": "good\x07 advice\nthanks"},
    ):
        response = client.post("/api/feedback", json=payload)
        assert response.status_code == 200 and response.json() == {"saved": True}
    assert client.get("/api/feedback/summary").json() == {
        "total": 4, "by_outcome": {"WON": 1, "LOST": 1, "DROPPED": 1}, "useful_yes": 2, "useful_no": 1,
    }
    with _db_session() as session:
        note = session.scalar(select(Feedback.note).where(Feedback.deal_id == "D4"))
        created = session.scalar(select(Feedback.created_at).where(Feedback.deal_id == "D4"))
    assert note == "good advice thanks"
    assert created is not None


def test_feedback_never_rewrites_the_ledger(client):
    with _db_session() as session:
        session.add(Deal(deal_name="D1", source_row_count=1))
        session.commit()
    assert client.post("/api/feedback", json={"deal_id": "D1", "outcome": "WON"}).status_code == 200
    assert client.post("/api/feedback", json={"deal_id": "D1", "outcome": "LOST"}).status_code == 200
    with _db_session() as session:
        assert session.get(Deal, "D1").outcome is None
