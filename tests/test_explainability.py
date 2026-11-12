"""Explainability tests: analogue ``matched_on`` reasons and fee position helpers.

``Deal`` rows are built directly; no database is needed.
"""

from __future__ import annotations

import math
from typing import Optional

import pytest

from app.baseline import compute_baseline, fee_percentile
from app.db import Deal
from app.normalize import size_tier
from app.retrieval import find_analogues
from app.schemas import Analogue, BaselineMetrics

try:
    from app import workflow as wf
except ImportError:  # langchain / langgraph not installed
    wf = None


def make_deal(
    name: str,
    industry: Optional[str] = "Technology",
    size_sqft: Optional[float] = 3000,
    fee: Optional[float] = 10_000,
    term: Optional[float] = 36,
    property_name: Optional[str] = None,
    outcome: Optional[str] = None,
) -> Deal:
    return Deal(
        deal_name=name,
        account_name=f"Account of {name}",
        industry=industry,
        size_sqft=size_sqft,
        size_tier=size_tier(size_sqft),
        lease_term_months=term,
        gross_fee_sgd=fee,
        property_name=property_name,
        lead_agent="Agent Smith",
        outcome=outcome,
        source_row_count=1,
    )


def query(industry=None, size_sqft=None, term=None, property_name=None) -> dict:
    return {
        "industry": industry,
        "size_sqft": size_sqft,
        "size_tier": size_tier(size_sqft),
        "lease_term_months": term,
        "property_name": property_name,
    }


# --- matched_on -----------------------------------------------------------------


def test_matched_on_default_is_empty_list():
    a = Analogue(
        deal_name="X", industry=None, size_sqft=None, lease_term_months=None,
        gross_fee_sgd=None, outcome=None, similarity=0.5,
    )
    assert a.matched_on == []
    b = Analogue(
        deal_name="Y", industry=None, size_sqft=None, lease_term_months=None,
        gross_fee_sgd=None, outcome=None, similarity=0.5,
    )
    assert a.matched_on is not b.matched_on


def test_same_industry_and_size_in_order():
    deal = make_deal("A", industry="Technology", size_sqft=3000, term=60)
    result = find_analogues([deal], query("Technology", 3000, 12))
    assert [a.deal_name for a in result] == ["A"]
    assert result[0].matched_on == ["same industry", "same size band"]


def test_all_four_reasons_in_order():
    deal = make_deal("A", property_name="Marina Tower")
    result = find_analogues([deal], query("Technology", 3000, 36, "Marina Tower"))
    assert result[0].matched_on == [
        "same industry",
        "same size band",
        "similar lease length",
        "same building",
    ]


def test_same_building_only():
    deal = make_deal("A", industry="Retail", size_sqft=50_000, term=120, property_name="Marina Tower")
    result = find_analogues([deal], query("Banking", 3000, 12, "Marina Tower"))
    assert [a.deal_name for a in result] == ["A"]
    assert result[0].matched_on == ["same building"]


def test_industry_only_match():
    deal = make_deal("A", industry="Technology", size_sqft=50_000, term=120)
    result = find_analogues([deal], query("Technology", 3000, 12))
    assert [a.deal_name for a in result] == ["A"]
    assert result[0].matched_on == ["same industry"]


def test_shared_industry_token_counts_as_same_industry():
    deal = make_deal("A", industry="Financial Services", size_sqft=50_000, term=120)
    result = find_analogues([deal], query("Financial Technology", 3000, 12))
    assert result[0].matched_on == ["same industry"]


def test_term_only_is_not_returned():
    deal = make_deal("A", industry="Retail", size_sqft=50_000, term=36)
    assert find_analogues([deal], query("Banking", 3000, 36)) == []


def test_matched_on_differs_per_deal():
    full = make_deal("A-full")
    partial = make_deal("B-partial", size_sqft=50_000, term=120)
    result = find_analogues([partial, full], query("Technology", 3000, 36))
    by_name = {a.deal_name: a.matched_on for a in result}
    assert by_name["A-full"] == ["same industry", "same size band", "similar lease length"]
    assert by_name["B-partial"] == ["same industry"]


# --- ranking / similarity unchanged ---------------------------------------------


def _fixture_deals() -> list[Deal]:
    return [
        make_deal("Z-exact", "Technology", 3000, term=36),
        make_deal("A-partial", "Technology", 30_000, term=60),
        make_deal("M-size", "Retail", 3000, term=120),
        make_deal("K-other", "Banking", 50_000, term=36),
        make_deal("B-tie", "Technology", 3000, term=36),
    ]


def test_ranking_and_similarity_unchanged():
    result = find_analogues(_fixture_deals(), query("Technology", 3000, 36), k=10)
    assert [(a.deal_name, a.similarity) for a in result] == EXPECTED_RANKING


# Captured from the implementation before ``matched_on`` was added.
EXPECTED_RANKING: list[tuple[str, float]] = [
    ("B-tie", 1.0),
    ("Z-exact", 1.0),
    ("A-partial", 0.267),
    ("M-size", 0.247),
]


# --- fee_min / fee_max ----------------------------------------------------------


def test_fee_min_max_populated():
    fees = [12_000.126, 8_000.0, 20_000.0, 15_000.0, 9_500.0]
    deals = [make_deal(f"D{i}", fee=f) for i, f in enumerate(fees)]
    m = compute_baseline(deals, {"industry": "Technology", "size_tier": size_tier(3000)})
    assert m.fee_min_sgd == 8_000.0
    assert m.fee_max_sgd == 20_000.0
    deals[1].gross_fee_sgd = 8_000.126
    m = compute_baseline(deals, {"industry": "Technology", "size_tier": size_tier(3000)})
    assert m.fee_min_sgd == 8_000.13


def test_fee_min_max_none_without_fees():
    deals = [make_deal(f"D{i}", fee=None) for i in range(6)]
    m = compute_baseline(deals, {"industry": "Technology", "size_tier": size_tier(3000)})
    assert m.fee_min_sgd is None and m.fee_max_sgd is None
    empty = compute_baseline([], {"industry": "Technology"})
    assert empty.fee_min_sgd is None and empty.fee_max_sgd is None


def test_fee_min_max_ignore_invalid_fees():
    fees = [float("nan"), float("inf"), -5.0, 0.0, None, 100.0, 300.0]
    deals = [make_deal(f"D{i}", fee=f) for i, f in enumerate(fees)]
    m = compute_baseline(deals, {})
    assert m.fee_min_sgd == 100.0
    assert m.fee_max_sgd == 300.0
    assert math.isfinite(m.fee_max_sgd)


def test_existing_baseline_fields_unchanged():
    deals = [make_deal(f"D{i}", fee=1000 * (i + 1)) for i in range(5)]
    m = compute_baseline(deals, {"industry": "Technology", "size_tier": size_tier(3000)})
    assert m.median_fee_sgd == 3000
    assert m.mean_fee_sgd == 3000
    assert m.fee_p25_sgd == 2000
    assert m.fee_p75_sgd == 4000
    assert m.n_with_fee == 5


def test_baseline_min_max_fields_optional():
    m = BaselineMetrics(
        match_level="x", n_comparables=0, n_with_fee=0, median_fee_sgd=None, mean_fee_sgd=None,
        median_size_sqft=None, median_lease_term_months=None, outcome_coverage=0, win_rate_pct=None,
    )
    assert m.fee_min_sgd is None and m.fee_max_sgd is None


# --- fee_percentile -------------------------------------------------------------


def test_percentile_below_min_and_above_max():
    fees = [100, 200, 300, 400]
    assert fee_percentile(fees, 50) == 0.0
    assert fee_percentile(fees, 1000) == 100.0


def test_percentile_midrank_with_ties():
    fees = [100, 200, 200, 300]
    # 1 strictly below + half of 2 equal = 2 of 4
    assert fee_percentile(fees, 200) == 50.0
    # the minimum value alone gets half credit
    assert fee_percentile(fees, 100) == 12.5
    assert fee_percentile(fees, 300) == 87.5
    assert fee_percentile(fees, 250) == 75.0


def test_percentile_single_value():
    assert fee_percentile([500], 500) == 50.0
    assert fee_percentile([500], 100) == 0.0
    assert fee_percentile([500], 900) == 100.0


def test_percentile_empty_or_unusable():
    assert fee_percentile([], 100) is None
    assert fee_percentile([0, -1, float("nan"), float("inf"), None], 100) is None


def test_percentile_ignores_invalid_fees():
    assert fee_percentile([0, -10, float("nan"), 100, 300], 200) == 50.0


def test_percentile_rounds_to_one_decimal():
    assert fee_percentile([1, 2, 3], 2.5) == pytest.approx(66.7)


def test_percentile_accepts_iterators_and_bad_value():
    assert fee_percentile(iter([1, 2, 3, 4]), 2.5) == 50.0
    assert fee_percentile([1, 2], float("nan")) is None


# --- privacy: matched_on is not sent to the LLM ----------------------------------


@pytest.mark.skipif(wf is None, reason="langchain/langgraph not installed")
def test_matched_on_not_in_redacted_payload():
    analogue = Analogue(
        deal_name="Secret Client Deal", industry="Technology", size_sqft=3000,
        lease_term_months=36, gross_fee_sgd=10_000, outcome=None, similarity=0.9,
        matched_on=["same industry", "same building"],
    )
    baseline = compute_baseline([make_deal(f"D{i}") for i in range(5)], {"industry": "Technology"})
    payload = wf._redacted_payload(
        {"industry": "Technology", "size_sqft": 3000, "size_tier": size_tier(3000), "lease_term_months": 36},
        baseline,
        [analogue],
        {"deal_name": "New"},
    )
    assert payload["analogues"]
    for entry in payload["analogues"]:
        assert "matched_on" not in entry
