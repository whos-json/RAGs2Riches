from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.db import Deal, init_db, make_engine, session_factory
from app.ingest import build_deal_rows, ingest_xlsx, read_leasing_xlsx
from app.normalize import parse_lease_term_months, size_tier, term_band
from app.workflow import build_graph, run_workflow

MOCK_XLSX = Path(os.getenv("SOURCE_XLSX", r"C:\Users\justin.fan\Downloads\mock leasing data.xlsx"))
needs_mock = pytest.mark.skipif(not MOCK_XLSX.exists(), reason="mock leasing workbook not available")

NODE_ORDER = [
    "validate_input",
    "sql_baseline",
    "analogue_retrieval",
    "llm_synthesis",
    "assemble_scorecard",
]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("36", 36.0),
        ("3 years", 36.0),
        ("2 years 15 days", 24.0),
        ("38mths 17 days", 38.0),
        ("14 months and 4 days", 14.0),
        ("1 mth", 1.0),
        (None, None),
        ("n/a", None),
        (float("nan"), None),
    ],
)
def test_parse_lease_term(raw, expected):
    assert parse_lease_term_months(raw) == expected


def test_size_tiers():
    assert size_tier(2500) == "S (<=5k sqft)"
    assert size_tier(5000) == "S (<=5k sqft)"
    assert size_tier(5001) == "M (5k-10k sqft)"
    assert size_tier(20001) == "XL (>20k sqft)"
    assert size_tier(None) is None


def test_term_band():
    assert term_band(12) == "<=12m"
    assert term_band(36) == "25-36m"
    assert term_band(None) is None


@needs_mock
def test_fee_is_per_deal_maximum_not_sum():
    rows = build_deal_rows(read_leasing_xlsx(str(MOCK_XLSX)))
    assert len(rows) == 563
    client_012 = next(r for r in rows if r["deal_name"] == "Client 012 - Deal 1")
    assert client_012["gross_fee_sgd"] == pytest.approx(44832.25)
    assert client_012["source_row_count"] == 3


@pytest.fixture()
def seeded(tmp_path):
    db_url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    engine = make_engine(db_url)
    init_db(engine)
    sessions = session_factory(engine)
    if MOCK_XLSX.exists():
        ingest_xlsx(str(MOCK_XLSX), sessions)
    return sessions


@needs_mock
def test_ingest_is_idempotent(seeded):
    ingest_xlsx(str(MOCK_XLSX), seeded)
    with seeded() as session:
        assert session.scalar(select(func.count()).select_from(Deal)) == 563


@needs_mock
def test_template_workflow_streams_nodes_and_leaves_outcomes_unknown(seeded):
    graph = build_graph(seeded)
    events: list[dict] = []
    deal = {
        "industry": "Financial & Insurance Services",
        "size_sqft": 5000,
        "lease_term_months": 36,
        "gross_signing_rent_psf": None,
        "property_name": None,
        "agent_name": "Daphne Heng",
        "notes": "Contact jane.doe@example.com or +65 9123 4567 for details.",
    }
    scorecard = run_workflow(graph, deal, {"provider": "template", "model": None}, emit=events.append)

    ended = [e["node"] for e in events if e["type"] == "node_end"]
    assert ended == NODE_ORDER
    assert events[0]["type"] == "run_start"

    assert scorecard["estimates"]["win_probability_pct"] is None
    assert scorecard["qualification"]["pursue_recommendation"] is None
    assert scorecard["estimates"]["estimated_timeframe_days"] is None
    assert scorecard["narrative_source"] == "template"
    assert scorecard["evidence"]["baseline"]["n_comparables"] >= 5
    assert len(scorecard["evidence"]["analogues"]) <= 5
    assert any("WON/LOST" in gap for gap in scorecard["data_gaps"])


@needs_mock
def test_backtest_excludes_the_deal_itself(seeded):
    graph = build_graph(seeded)
    deal = {"deal_name": "Client 012 - Deal 1", "industry": "Technology", "size_sqft": 4500}
    scorecard = run_workflow(graph, deal, {"provider": "template", "model": None})
    names = [a["deal_name"] for a in scorecard["evidence"]["analogues"]]
    assert "Client 012 - Deal 1" not in names
    assert scorecard["deal_id"] == "Client 012 - Deal 1"


@needs_mock
def test_unreachable_llm_falls_back_to_template(seeded, monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:9")
    get_settings.cache_clear()
    try:
        graph = build_graph(seeded)
        scorecard = run_workflow(
            graph,
            {"industry": "Technology", "size_sqft": 4500, "notes": None},
            {"provider": "ollama", "model": "qwen2.5:7b-instruct"},
        )
    finally:
        get_settings.cache_clear()
    assert scorecard["narrative_source"] == "template_fallback"
    assert any("failed" in w for w in scorecard["warnings"])
    assert scorecard["llm_provider"] == "ollama"
