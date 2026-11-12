"""Portfolio statistics, lease-date ingestion and the SQLite column migration."""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import date

import pandas as pd
import pytest
from sqlalchemy import inspect, select

from app.db import Deal, init_db, make_engine, session_factory
from app.ingest import build_deal_rows, ingest_xlsx, read_leasing_xlsx
from app.portfolio import SHRINKAGE_K, compute_portfolio

TODAY = date(2025, 6, 15)


def _deal(name: str, **fields) -> Deal:
    return Deal(deal_name=name, source_row_count=1, **fields)


@pytest.fixture
def deals() -> list[Deal]:
    return [
        _deal(
            "d1", account_name="A", industry="Tech", property_name="P1", lead_agent="X",
            gross_fee_sgd=1000.0, size_sqft=3000.0, size_tier="S (<=5k sqft)", lease_term_months=36.0,
            gross_signing_rent_psf=8.0, deal_done_date=date(2025, 5, 1), billing_status="Billed",
            lease_expiry_date=date(2025, 9, 15),
        ),
        _deal(
            "d2", account_name="A", industry="Tech", property_name="P1", lead_agent="X",
            gross_fee_sgd=3000.0, size_sqft=8000.0, size_tier="M (5k-10k sqft)",
            deal_done_date=date(2024, 12, 1), billing_status="Not billed",
            lease_expiry_date=date(2024, 1, 1),
        ),
        _deal(
            "d3", account_name="B", industry="Finance", property_name="P2", lead_agent="Y",
            gross_fee_sgd=2000.0, size_sqft=15000.0, size_tier="L (10k-20k sqft)",
            deal_done_date=date(2025, 6, 30), billing_status="not billed",
            lease_expiry_date=date(2026, 9, 15),
        ),
        _deal("d4", account_name="C", lead_agent="Y"),
        _deal(
            "d5", account_name="D", industry="Tech", property_name="P2", lead_agent="X",
            gross_fee_sgd=0.0, deal_done_date=date(2023, 1, 1), billing_status="NOT BILLED",
        ),
    ]


def _coverage(result: dict, field: str) -> dict:
    return next(row for row in result["coverage"] if row["field"] == field)


def test_totals_and_json_safety(deals):
    result = compute_portfolio(deals, TODAY)
    json.dumps(result, allow_nan=False)
    assert result["as_of"] == "2025-06-15"
    assert result["totals"] == {
        "deals": 5, "accounts": 4, "properties": 2, "agents": 2, "industries": 2,
        "n_with_fee": 3, "total_fee_sgd": 6000.0, "median_fee_sgd": 2000.0,
    }


def test_coverage_counts_only_positive_finite_fees(deals):
    deals.append(_deal("nan", gross_fee_sgd=math.nan))
    result = compute_portfolio(deals, TODAY)
    assert _coverage(result, "fee") == {
        "field": "fee", "label": "Fee recorded", "n": 3, "total": 6, "pct": 50.0,
    }
    assert [row["field"] for row in result["coverage"]] == [
        "fee", "industry", "size", "lease_term", "rent", "done_date", "lease_expiry", "property",
    ]
    assert _coverage(result, "lease_expiry")["n"] == 3
    assert result["fee_distribution"]["n_zero_or_missing"] == 3


def test_industry_rows_group_missing_and_compute_medians(deals):
    rows = {r["industry"]: r for r in compute_portfolio(deals, TODAY)["by_industry"]}
    assert rows["Tech"]["n"] == 3 and rows["Tech"]["n_with_fee"] == 2
    assert rows["Tech"]["median_fee_sgd"] == 2000.0
    assert rows["Tech"]["total_fee_sgd"] == 4000.0
    assert rows["Tech"]["share_of_fees_pct"] == 66.7
    assert rows["Not recorded"]["median_fee_sgd"] is None
    assert rows["Not recorded"]["shrunk_median_fee_sgd"] is None


def test_shrinkage_pulls_tiny_group_toward_global_median():
    big = [_deal(f"b{i}", industry="Big", gross_fee_sgd=1000.0) for i in range(20)]
    tiny = [_deal("t", industry="Tiny", gross_fee_sgd=100_000.0)]
    result = compute_portfolio(big + tiny, TODAY)
    rows = {r["industry"]: r for r in result["by_industry"]}
    global_mean = (20 * math.log(1000) + math.log(100_000)) / 21
    expected = round(math.exp((math.log(100_000) + SHRINKAGE_K * global_mean) / (1 + SHRINKAGE_K)), 2)
    assert rows["Tiny"]["median_fee_sgd"] == 100_000.0
    assert rows["Tiny"]["shrunk_median_fee_sgd"] == expected
    assert 1000 < rows["Tiny"]["shrunk_median_fee_sgd"] < 100_000
    assert rows["Big"]["shrunk_median_fee_sgd"] == pytest.approx(1000, rel=0.1)



def test_size_tiers_follow_fixed_order(deals):
    tiers = compute_portfolio(deals, TODAY)["by_size_tier"]
    assert [t["tier"][0] for t in tiers] == ["S", "M", "L", "N"]
    assert tiers[-1]["tier"] == "Not recorded" and tiers[-1]["n"] == 2
    assert tiers[0]["share_of_deals_pct"] == 20.0


def test_concentration_and_repeat_clients(deals):
    result = compute_portfolio(deals, TODAY)
    top = result["concentration"]["top_accounts"]
    assert top[0] == {"name": "A", "deals": 2, "total_fee_sgd": 4000.0, "share_pct": 66.7}
    assert result["concentration"]["top5_accounts_share_pct"] == 100.0
    repeat = result["repeat_clients"]
    assert repeat["accounts_with_repeat"] == 1
    assert repeat["repeat_share_of_fees_pct"] == 66.7
    assert repeat["accounts"] == [
        {"name": "A", "deals": 2, "total_fee_sgd": 4000.0, "last_done": "2025-05-01"}
    ]


def test_seasonality_uses_done_date(deals):
    season = compute_portfolio(deals, TODAY)["seasonality"]
    assert season["n_dated"] == 4 and season["n_total"] == 5
    assert [y["year"] for y in season["by_year"]] == [2023, 2024, 2025]
    assert len(season["by_month"]) == 12
    assert season["by_month"][5] == {"month": 6, "deals": 1}


def test_billing_state_and_unbilled_ageing(deals):
    billing = compute_portfolio(deals, TODAY)["billing"]
    assert billing["billed"] == {"deals": 1, "fee_sgd": 1000.0}
    assert billing["not_billed"] == {"deals": 3, "fee_sgd": 5000.0}
    assert billing["unknown"] == {"deals": 1, "fee_sgd": 0.0}
    ageing = {b["bucket"]: b["deals"] for b in billing["unbilled_by_age"]}
    assert list(ageing) == ["Under 3 months", "3-6 months", "6-12 months", "Over 12 months", "Date unknown"]
    assert ageing == {
        "Under 3 months": 1, "3-6 months": 0, "6-12 months": 1, "Over 12 months": 1, "Date unknown": 0,
    }
    assert billing["n_dated"] == 3


def test_lease_expiry_buckets_and_calls(deals):
    expiry = compute_portfolio(deals, TODAY)["lease_expiry"]
    assert expiry["n_with_expiry"] == 3 and expiry["n_total"] == 5
    counts = {b["label"]: b["deals"] for b in expiry["buckets"]}
    assert list(counts) == [
        "Already expired", "0-6 months", "6-12 months", "12-18 months", "18-24 months", "Over 24 months",
    ]
    assert counts["Already expired"] == 1 and counts["0-6 months"] == 1 and counts["12-18 months"] == 1
    assert [c["deal_name"] for c in expiry["calls"]] == ["d1", "d3"]
    first = expiry["calls"][0]
    assert first["expiry"] == "2025-09-15" and first["months_left"] == 3.0
    assert first["past_fee_sgd"] == 1000.0 and first["lead_agent"] == "X"


def test_expiry_calls_are_capped_and_sorted():
    many = [
        _deal(f"e{i:02d}", lease_expiry_date=date(2025, 7, 1 + i % 28), gross_fee_sgd=100.0)
        for i in range(40)
    ]
    calls = compute_portfolio(many, TODAY)["lease_expiry"]["calls"]
    assert len(calls) == 25
    assert [c["expiry"] for c in calls] == sorted(c["expiry"] for c in calls)


def test_fee_distribution_bins():
    fees = [10.0 ** (i / 3) for i in range(13)]
    result = compute_portfolio([_deal(f"f{i}", gross_fee_sgd=f) for i, f in enumerate(fees)], TODAY)
    dist = result["fee_distribution"]
    assert dist["n"] == 13 and len(dist["bins"]) == 12
    assert sum(b["count"] for b in dist["bins"]) == 13
    assert dist["bins"][0]["lo"] == 1.0 and dist["bins"][-1]["hi"] == dist["max"]
    assert dist["p50"] == round(fees[6], 2)


def test_few_fees_have_no_bins(deals):
    dist = compute_portfolio(deals, TODAY)["fee_distribution"]
    assert dist["n"] == 3 and dist["bins"] == [] and dist["p50"] == 2000.0


def test_agents_sorted_by_deal_count(deals):
    agents = compute_portfolio(deals, TODAY)["agents"]
    assert [(a["agent"], a["deals"]) for a in agents] == [("X", 3), ("Y", 2)]
    assert agents[0]["median_fee_sgd"] == 2000.0


def test_notes_report_missing_data_honestly(deals):
    notes = " ".join(compute_portfolio(deals, TODAY)["notes"])
    assert "3 of 5" in notes
    assert "win rate cannot be calculated" in notes
    assert "no lease expiry date" in notes


def test_empty_portfolio_is_valid_and_has_no_nan():
    result = compute_portfolio([], TODAY)
    json.dumps(result, allow_nan=False)
    assert result["totals"]["deals"] == 0 and result["totals"]["median_fee_sgd"] is None
    assert all(row["total"] == 0 and row["pct"] is None for row in result["coverage"])
    assert result["fee_distribution"]["bins"] == []
    assert result["by_industry"] == [] and result["agents"] == []
    assert len(result["seasonality"]["by_month"]) == 12
    assert len(result["lease_expiry"]["buckets"]) == 6 and result["lease_expiry"]["calls"] == []
    assert len(result["billing"]["unbilled_by_age"]) == 5
    assert result["concentration"]["top5_accounts_share_pct"] is None
    assert result["notes"]


# --- lease date ingestion ---------------------------------------------------------------------

BASE_COLUMNS = {
    "Deal Name": ["A", "A", "B", "C"],
    "Account Name": ["Acme", "Acme", "Beta", "Gamma"],
    "Leasing Industry": ["Tech", "Tech", "Finance", "Retail"],
    "Size (sq/ft)": [1000, 1000, 2000, 3000],
    "Lease Term": ["3 years", "3 years", "2 years", "1 year"],
    "Role": ["Lead Broker", "Support", "Lead Broker", "Lead Broker"],
    "Agent Name": ["X", "Y", "X", "Y"],
    "Deal Done Date": ["01/02/2020", "01/02/2020", "03/04/2021", "05/06/2022"],
    "Gross Signing Rent (psf/mth)": [5.0, 5.0, 6.0, 7.0],
    "Gross Fee (SGD)": [100.0, 100.0, 200.0, 300.0],
    "Net Fee Collected": [90.0, 90.0, 180.0, 270.0],
    "Property Name": ["P1", "P1", "P2", "P3"],
    "Billing Status": ["Billed", "Billed", "Not billed", "Billed"],
    "Billing FY Year": [2020, 2020, 2021, 2022],
}


def _write_workbook(path, extra: dict | None = None):
    frame = pd.DataFrame({**BASE_COLUMNS, **(extra or {})})
    frame.to_excel(path, index=False)
    return str(path)


def test_lease_dates_take_earliest_commence_and_latest_expiry(tmp_path):
    path = _write_workbook(
        tmp_path / "dates.xlsx",
        {
            "Lease Commence Date": ["01/02/2020", "15/03/2019", "01/01/1985", None],
            "Lease Expiry Date": ["31/01/2023", "30/06/2025", None, "01/01/2200"],
        },
    )
    rows = {r["deal_name"]: r for r in build_deal_rows(read_leasing_xlsx(path))}
    assert rows["A"]["lease_commence_date"] == date(2019, 3, 15)
    assert rows["A"]["lease_expiry_date"] == date(2025, 6, 30)
    assert rows["B"]["lease_commence_date"] is None and rows["B"]["lease_expiry_date"] is None
    assert rows["C"]["lease_commence_date"] is None and rows["C"]["lease_expiry_date"] is None


def test_lease_dates_parse_day_first_and_real_excel_dates(tmp_path):
    path = _write_workbook(
        tmp_path / "mixed.xlsx",
        {
            "Lease Commence Date": [pd.Timestamp("2021-05-04"), None, "02/03/2020", None],
            "Lease Expiry Date": [None, None, "04/05/2024", None],
        },
    )
    rows = {r["deal_name"]: r for r in build_deal_rows(read_leasing_xlsx(path))}
    assert rows["A"]["lease_commence_date"] == date(2021, 5, 4)
    assert rows["B"]["lease_commence_date"] == date(2020, 3, 2)
    assert rows["B"]["lease_expiry_date"] == date(2024, 5, 4)


def test_workbook_without_lease_date_columns_still_ingests(tmp_path):
    path = _write_workbook(tmp_path / "plain.xlsx")
    rows = build_deal_rows(read_leasing_xlsx(path))
    assert len(rows) == 3
    assert all(r["lease_commence_date"] is None and r["lease_expiry_date"] is None for r in rows)

    engine = make_engine(f"sqlite:///{(tmp_path / 'plain.db').as_posix()}")
    init_db(engine)
    sessions = session_factory(engine)
    assert ingest_xlsx(path, sessions)["deals_loaded"] == 3
    with sessions() as session:
        assert session.scalar(select(Deal.lease_expiry_date).where(Deal.deal_name == "A")) is None


# --- migration --------------------------------------------------------------------------------


def test_init_db_adds_missing_columns_to_old_schema(tmp_path):
    db_file = tmp_path / "old.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            "CREATE TABLE deals (deal_name VARCHAR(255) PRIMARY KEY, account_name VARCHAR(255), "
            "industry VARCHAR(120), size_sqft FLOAT, size_tier VARCHAR(40), lease_term_months FLOAT, "
            "gross_signing_rent_psf FLOAT, gross_fee_sgd FLOAT, net_fee_collected_sgd FLOAT, "
            "property_name VARCHAR(255), lead_agent VARCHAR(120), deal_done_date DATE, "
            "billing_status VARCHAR(30), billing_fy_year INTEGER, outcome VARCHAR(10), "
            "source_row_count INTEGER)"
        )
        conn.execute("INSERT INTO deals (deal_name, source_row_count) VALUES ('old', 1)")
    engine = make_engine(f"sqlite:///{db_file.as_posix()}")
    init_db(engine)
    init_db(engine)  # idempotent
    names = {c["name"] for c in inspect(engine).get_columns("deals")}
    assert {"lease_commence_date", "lease_expiry_date"} <= names
    assert "feedback" in inspect(engine).get_table_names()
    with session_factory(engine)() as session:
        old = session.get(Deal, "old")
        assert old is not None and old.lease_expiry_date is None
