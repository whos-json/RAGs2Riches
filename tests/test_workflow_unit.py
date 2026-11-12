"""Pure-python unit tests for baseline, retrieval and workflow helpers.

No network, no pandas, no database session: ``Deal`` rows are built directly.
Written with ``unittest`` so they run under both pytest and ``python -m unittest``.
Workflow-helper tests are skipped when langchain/langgraph are not installed.
"""

from __future__ import annotations

import json
import math
import re
import unittest
from typing import Optional

from app.baseline import MIN_COMPARABLES, compute_baseline
from app.db import Deal
from app.normalize import size_tier
from app.retrieval import MIN_SIMILARITY, find_analogues
from app.schemas import Analogue, BaselineMetrics, DealInput, Narrative

try:
    from app import workflow as wf
except ImportError:  # langchain / langgraph not installed
    wf = None

needs_workflow = unittest.skipIf(wf is None, "langchain/langgraph not installed")


def make_deal(
    name: str,
    industry: Optional[str] = "Technology",
    size_sqft: Optional[float] = 3000,
    fee: Optional[float] = 10_000,
    term: Optional[float] = 36,
    outcome: Optional[str] = None,
    property_name: Optional[str] = None,
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


def norm(industry=None, size_sqft=None, term=None, property_name=None, deal_name=None) -> dict:
    return {
        "deal_name": deal_name,
        "industry": industry,
        "size_sqft": size_sqft,
        "size_tier": size_tier(size_sqft),
        "lease_term_months": term,
        "property_name": property_name,
    }


class BaselineTests(unittest.TestCase):
    def test_empty_pool(self):
        m = compute_baseline([], norm("Technology", 3000))
        self.assertEqual(m.n_comparables, 0)
        self.assertEqual(m.n_with_fee, 0)
        self.assertIsNone(m.median_fee_sgd)
        self.assertIsNone(m.mean_fee_sgd)
        self.assertIsNone(m.median_size_sqft)
        self.assertIsNone(m.median_lease_term_months)
        self.assertIsNone(m.win_rate_pct)
        self.assertEqual(m.outcome_coverage, 0)

    def test_all_values_none(self):
        deals = [make_deal(f"D{i}", size_sqft=None, fee=None, term=None) for i in range(6)]
        m = compute_baseline(deals, norm())
        self.assertEqual(m.n_comparables, 6)
        self.assertEqual(m.n_with_fee, 0)
        self.assertIsNone(m.median_fee_sgd)
        self.assertIsNone(m.median_size_sqft)
        self.assertIsNone(m.median_lease_term_months)

    def test_median_is_robust_to_outliers(self):
        fees = [10_000, 11_000, 12_000, 13_000, 1_000_000_000]
        deals = [make_deal(f"D{i}", fee=f) for i, f in enumerate(fees)]
        m = compute_baseline(deals, norm("Technology", 3000))
        self.assertEqual(m.median_fee_sgd, 12_000)
        self.assertGreater(m.mean_fee_sgd, 1_000_000)  # mean is distorted, median is not

    def test_invalid_numbers_are_ignored(self):
        fees = [float("nan"), float("inf"), -5.0, 0.0, None, 100.0, 300.0]
        deals = [make_deal(f"D{i}", fee=f) for i, f in enumerate(fees)]
        m = compute_baseline(deals, norm())
        self.assertEqual(m.n_comparables, len(fees))
        self.assertEqual(m.n_with_fee, 2)
        self.assertEqual(m.median_fee_sgd, 200.0)
        self.assertTrue(math.isfinite(m.mean_fee_sgd))

    def test_quartiles_need_enough_data(self):
        few = compute_baseline([make_deal(f"D{i}", fee=1000 * (i + 1)) for i in range(3)], norm())
        self.assertIsNone(few.fee_p25_sgd)
        self.assertIsNone(few.fee_p75_sgd)
        many = compute_baseline([make_deal(f"D{i}", fee=1000 * (i + 1)) for i in range(5)], norm())
        self.assertEqual(many.fee_p25_sgd, 2000)
        self.assertEqual(many.fee_p75_sgd, 4000)

    def test_exclude_name(self):
        deals = [make_deal(f"D{i}", fee=100) for i in range(5)] + [make_deal("SELF", fee=9_999_999)]
        m = compute_baseline(deals, norm(), exclude_name="SELF")
        self.assertEqual(m.n_comparables, 5)
        self.assertEqual(m.median_fee_sgd, 100)

    def test_match_level_widening(self):
        tech_small = [make_deal(f"T{i}") for i in range(MIN_COMPARABLES)]
        other = [make_deal(f"R{i}", industry="Retail", size_sqft=30_000) for i in range(3)]
        m = compute_baseline(tech_small + other, norm("Technology", 3000))
        self.assertEqual(m.match_level, "industry + size tier")
        self.assertEqual(m.n_comparables, MIN_COMPARABLES)

        m = compute_baseline(tech_small[:2] + other[:2], norm("Technology", 3000))
        self.assertEqual(m.match_level, "all deals (insufficient matches)")
        self.assertEqual(m.n_comparables, 4)

    def test_industry_match_ignores_case_and_whitespace(self):
        deals = [make_deal(f"D{i}", industry="  technology ") for i in range(MIN_COMPARABLES)]
        m = compute_baseline(deals, norm("Technology"))
        self.assertEqual(m.match_level, "industry")

    def test_no_outcomes_means_no_win_rate(self):
        m = compute_baseline([make_deal(f"D{i}") for i in range(6)], norm())
        self.assertIsNone(m.win_rate_pct)
        self.assertEqual(m.outcome_coverage, 0)

    def test_win_rate_from_decided_deals_only(self):
        outcomes = ["WON", "WON", "LOST", None, None, "won"]
        deals = [make_deal(f"D{i}", outcome=o) for i, o in enumerate(outcomes)]
        m = compute_baseline(deals, norm())
        self.assertEqual(m.outcome_coverage, 4)
        self.assertEqual(m.win_rate_pct, 75.0)


class RetrievalTests(unittest.TestCase):
    def test_empty_inputs(self):
        self.assertEqual(find_analogues([], norm("Technology", 3000)), [])
        self.assertEqual(find_analogues([make_deal("A")], norm()), [])
        self.assertEqual(find_analogues([make_deal("A")], norm("Technology", 3000), k=0), [])

    def test_no_zero_overlap_results(self):
        # Shares only the lease-term band with the query: not a meaningful analogue.
        unrelated = make_deal("U", industry="Retail", size_sqft=50_000, term=36)
        related = make_deal("R", industry="Banking", size_sqft=3000, term=36)
        result = find_analogues([unrelated, related], norm("Banking", 3000, 36))
        self.assertEqual([a.deal_name for a in result], ["R"])

        only_unrelated = find_analogues([unrelated], norm("Banking", 3000, 36))
        self.assertEqual(only_unrelated, [])

    def test_similarity_floor_and_bounds(self):
        deals = [make_deal(f"D{i}", industry=i_name) for i, i_name in enumerate(["Tech", "Banking", "Retail"])]
        for a in find_analogues(deals, norm("Tech", 3000, 36)):
            self.assertGreaterEqual(a.similarity, round(MIN_SIMILARITY, 3))
            self.assertLessEqual(a.similarity, 1.0)

    def test_ties_are_deterministic(self):
        names = ["C", "A", "B", "E", "D"]
        deals = [make_deal(n) for n in names]
        query = norm("Technology", 3000, 36)
        first = [a.deal_name for a in find_analogues(deals, query, k=5)]
        self.assertEqual(first, ["A", "B", "C", "D", "E"])
        reversed_order = [a.deal_name for a in find_analogues(list(reversed(deals)), query, k=5)]
        self.assertEqual(first, reversed_order)
        top_two = [a.deal_name for a in find_analogues(deals, query, k=2)]
        self.assertEqual(top_two, ["A", "B"])

    def test_better_match_ranks_first(self):
        exact = make_deal("Z-exact", industry="Technology", size_sqft=3000, term=36)
        partial = make_deal("A-partial", industry="Technology", size_sqft=30_000, term=60)
        result = find_analogues([partial, exact], norm("Technology", 3000, 36))
        self.assertEqual([a.deal_name for a in result], ["Z-exact", "A-partial"])
        self.assertGreater(result[0].similarity, result[1].similarity)

    def test_unseen_query_term_does_not_inflate_similarity(self):
        deals = [make_deal(f"D{i}", industry="Technology", size_sqft=3000) for i in range(3)]
        result = find_analogues(deals, norm("Quantum", 3000))
        self.assertTrue(result)
        for a in result:
            self.assertLess(a.similarity, 0.9)

    def test_exclude_name_and_outcome_filter(self):
        deals = [
            make_deal("SELF", outcome="WON"),
            make_deal("W1", outcome="WON"),
            make_deal("L1", outcome="LOST"),
            make_deal("N1", outcome=None),
        ]
        query = norm("Technology", 3000, 36)
        names = [a.deal_name for a in find_analogues(deals, query, exclude_name="SELF")]
        self.assertNotIn("SELF", names)
        won = [a.deal_name for a in find_analogues(deals, query, exclude_name="SELF", outcome="won")]
        self.assertEqual(won, ["W1"])

    def test_property_match_counts_as_overlap(self):
        a = make_deal("A", industry="Retail", size_sqft=50_000, property_name="Marina Tower")
        b = make_deal("B", industry="Retail", size_sqft=50_000, property_name="Other Plaza")
        result = find_analogues([a, b], norm(None, None, None, property_name="Marina Tower"))
        self.assertEqual([x.deal_name for x in result], ["A"])


class SchemaTests(unittest.TestCase):
    def test_blank_strings_become_none(self):
        d = DealInput(industry="   ", notes="", property_name=" Tower ")
        self.assertIsNone(d.industry)
        self.assertIsNone(d.notes)
        self.assertEqual(d.property_name, "Tower")

    def test_baseline_quartile_fields_are_optional(self):
        m = BaselineMetrics(
            match_level="x",
            n_comparables=0,
            n_with_fee=0,
            median_fee_sgd=None,
            mean_fee_sgd=None,
            median_size_sqft=None,
            median_lease_term_months=None,
            outcome_coverage=0,
            win_rate_pct=None,
        )
        self.assertIsNone(m.fee_p25_sgd)


def _baseline(**overrides) -> BaselineMetrics:
    fields = dict(
        match_level="all deals",
        n_comparables=30,
        n_with_fee=30,
        median_fee_sgd=50_000.0,
        mean_fee_sgd=55_000.0,
        median_size_sqft=3000.0,
        median_lease_term_months=36.0,
        outcome_coverage=0,
        win_rate_pct=None,
    )
    fields.update(overrides)
    return BaselineMetrics(**fields)


@needs_workflow
class WorkflowHelperTests(unittest.TestCase):
    def test_pursue_never_fabricated_without_outcomes(self):
        self.assertIsNone(wf._pursue_recommendation(_baseline()))
        # A win rate from too few decided deals must not drive a recommendation either.
        thin = _baseline(outcome_coverage=wf.MIN_DECIDED_OUTCOMES_FOR_PURSUE - 1, win_rate_pct=100.0)
        self.assertIsNone(wf._pursue_recommendation(thin))

    def test_pursue_bands(self):
        n = wf.MIN_DECIDED_OUTCOMES_FOR_PURSUE
        self.assertEqual(
            wf._pursue_recommendation(_baseline(outcome_coverage=n, win_rate_pct=wf.PURSUE_HIGH_PRIORITY_WIN_PCT)),
            "PURSUE_HIGH_PRIORITY",
        )
        self.assertEqual(
            wf._pursue_recommendation(_baseline(outcome_coverage=n, win_rate_pct=wf.PURSUE_WIN_PCT)), "PURSUE"
        )
        self.assertEqual(
            wf._pursue_recommendation(_baseline(outcome_coverage=n, win_rate_pct=wf.PURSUE_WIN_PCT - 1)), "NURTURE"
        )

    def test_effort_tier(self):
        self.assertEqual(wf._effort_tier(None)[1], wf.TIER3_MAX_HOURS)
        self.assertEqual(wf._effort_tier(wf.MID_VALUE_FEE_SGD)[1], wf.TIER2_MAX_HOURS)
        self.assertEqual(wf._effort_tier(wf.HIGH_VALUE_FEE_SGD)[1], wf.TIER1_MAX_HOURS)

    def test_confidence_counts_only_comparables_with_fees(self):
        self.assertEqual(wf._confidence(_baseline(n_with_fee=2)), "LOW")
        self.assertEqual(wf._confidence(_baseline(n_with_fee=12)), "MEDIUM")
        self.assertEqual(wf._confidence(_baseline(outcome_coverage=25, win_rate_pct=50.0)), "HIGH")

    def test_data_gaps_flag_missing_outcomes(self):
        gaps = wf._data_gaps({"size_sqft": 1000, "lease_term_months": 12}, _baseline())
        self.assertTrue(any("No WON/LOST" in g for g in gaps))

    def test_unsupported_win_claim_detection(self):
        bad = Narrative(
            winning_strategy="We have a 65% chance of winning this.",
            key_risks_and_mitigations=[],
            recommended_resources=[],
            referenced_historical_deals=[],
        )
        ok = Narrative(
            winning_strategy="Median gross fee SGD 12,000 across 30 comparables.",
            key_risks_and_mitigations=["Risk: few comparables. Mitigation: validate."],
            recommended_resources=[],
            referenced_historical_deals=[],
        )
        self.assertTrue(wf._unsupported_win_claim(bad))
        self.assertFalse(wf._unsupported_win_claim(ok))

    def test_template_narrative_without_outcomes_is_descriptive(self):
        n = wf._template_narrative(norm("Technology", 3000), _baseline(), [])
        self.assertTrue(any("no WON/LOST" in r for r in n["key_risks_and_mitigations"]))
        self.assertFalse(wf._unsupported_win_claim(Narrative(**n)))

    def test_need_raises_clear_error(self):
        with self.assertRaises(KeyError):
            wf._need({"deal": {}, "llm": {}}, "normalized")
        self.assertEqual(wf._need({"deal": {}, "llm": {}, "analogues": []}, "analogues"), [])

    def test_redacted_payload_leaks_no_names(self):
        deal = {
            "deal_name": "Project Falcon",
            "account_name": "Acme Holdings Pte Ltd",
            "agent_name": "John Tan",
            "property_name": "Marina Tower",
            "notes": "Call JOHN tan on +65 9123 4567 or john@acme.com about acme expansion at Marina Tower.",
        }
        normalized = norm("Technology", 3000, 36, property_name="Marina Tower", deal_name="Project Falcon")
        analogues = [
            Analogue(
                deal_name="Secret Client Deal",
                industry="Technology",
                size_sqft=3000,
                lease_term_months=36,
                gross_fee_sgd=10_000,
                outcome=None,
                similarity=0.9,
            )
        ]
        payload = wf._redacted_payload(normalized, _baseline(), analogues, deal)
        dumped = json.dumps(payload, default=str)
        for forbidden in ["falcon", "acme", "john", "tan", "marina", "tower", "holdings", "secret", "9123", "@"]:
            self.assertIsNone(
                re.search(rf"(?<!\w){forbidden}(?!\w)", dumped, flags=re.IGNORECASE),
                f"payload leaked {forbidden!r}: {dumped}",
            )
        self.assertTrue(payload["new_deal"]["property_alias"].startswith("PROPERTY-"))
        self.assertEqual(payload["analogues"][0]["alias"], "HIST-01")
        self.assertNotIn("deal_name", payload["analogues"][0])
        self.assertFalse(payload["has_outcome_data"])


if __name__ == "__main__":
    unittest.main()
