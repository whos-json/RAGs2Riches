import copy
import json
import unittest
from pathlib import Path

from engine import load_history, make_deal_id, score_deal, size_tier, validate_input

HISTORY = load_history(Path(__file__).resolve().parent / "data" / "historical_deals.json")

VALID = {
    "account_name": "Northwind Payments",
    "industry": "Fintech",
    "employees": 900,
    "deal_value_usd": 95000,
    "stage": "Proposal",
    "expected_close_days": 70,
    "budget_confirmed": True,
    "sponsor": "Executive engaged",
    "need": "High",
    "notes": "Migrating off a legacy vendor. Needs API latency and compliance reporting.",
}


def payload(**overrides):
    data = copy.deepcopy(VALID)
    data.update(overrides)
    return data


class ValidationTests(unittest.TestCase):
    def test_valid_payload_is_accepted(self):
        deal = validate_input(payload())
        self.assertEqual(deal["account_name"], "Northwind Payments")
        self.assertEqual(deal["employees"], 900)

    def test_rejects_non_object_body(self):
        with self.assertRaisesRegex(ValueError, "JSON object"):
            validate_input(["not", "an", "object"])

    def test_rejects_missing_account_name(self):
        with self.assertRaisesRegex(ValueError, "Account name"):
            validate_input(payload(account_name="   "))

    def test_rejects_unknown_choice(self):
        with self.assertRaisesRegex(ValueError, "industry must be one of"):
            validate_input(payload(industry="Aerospace"))

    def test_rejects_non_positive_and_non_numeric_numbers(self):
        with self.assertRaisesRegex(ValueError, "deal_value_usd must be greater than zero"):
            validate_input(payload(deal_value_usd=0))
        with self.assertRaisesRegex(ValueError, "employees must be a number"):
            validate_input(payload(employees="lots"))
        with self.assertRaisesRegex(ValueError, "deal_value_usd must be greater than zero"):
            validate_input(payload(deal_value_usd=float("inf")))

    def test_rejects_non_boolean_budget_flag(self):
        with self.assertRaisesRegex(ValueError, "budget_confirmed"):
            validate_input(payload(budget_confirmed="yes"))


class ScorecardTests(unittest.TestCase):
    def setUp(self):
        self.card = score_deal(payload(), HISTORY)

    def test_scorecard_has_schema_sections(self):
        for key in ("deal_id", "qualification", "estimates", "effort_allocation", "closing_playbook"):
            self.assertIn(key, self.card)
        self.assertEqual(
            set(self.card["qualification"]),
            {"pursue_recommendation", "fit_score", "framework_breakdown", "fit_points"},
        )
        self.assertEqual(
            set(self.card["estimates"]),
            {"win_probability_pct", "estimated_revenue_usd", "estimated_timeframe_days", "confidence_level"},
        )

    def test_deal_id_is_new_style_and_stable(self):
        self.assertRegex(self.card["deal_id"], r"^DEAL-\d{5}$")
        self.assertEqual(self.card["deal_id"], score_deal(payload(), HISTORY)["deal_id"])

    def test_fit_points_sum_to_fit_score(self):
        q = self.card["qualification"]
        self.assertEqual(sum(q["fit_points"].values()), q["fit_score"])
        self.assertTrue(0 <= q["fit_score"] <= 100)

    def test_strong_deal_is_high_priority_and_tier_one(self):
        strong = score_deal(
            payload(deal_value_usd=250000, budget_confirmed=True, sponsor="Executive engaged",
                    need="High", stage="Negotiation", expected_close_days=60),
            HISTORY,
        )
        self.assertEqual(strong["qualification"]["pursue_recommendation"], "PURSUE_HIGH_PRIORITY")
        self.assertEqual(strong["effort_allocation"]["tier"], "Tier 1 - High Touch")
        self.assertEqual(strong["effort_allocation"]["max_recommended_hours"], 25)

    def test_weak_deal_is_deprioritized_with_light_touch(self):
        weak = score_deal(
            payload(budget_confirmed=False, sponsor="No access yet", need="Low",
                    stage="Discovery", expected_close_days=365),
            HISTORY,
        )
        self.assertEqual(weak["qualification"]["pursue_recommendation"], "DEPRIORITIZE")
        self.assertEqual(weak["effort_allocation"]["tier"], "Tier 3 - Light Touch")
        self.assertIn("Confirm budget range with the economic buyer", weak["effort_allocation"]["recommended_resources"])

    def test_win_probability_and_expected_value_are_consistent(self):
        est = self.card["estimates"]
        self.assertTrue(1 <= est["win_probability_pct"] <= 99)
        self.assertEqual(est["estimated_revenue_usd"], round(95000 * est["win_probability_pct"] / 100))

    def test_analogues_are_ranked_and_referenced(self):
        analogues = self.card["analogues"]
        self.assertEqual(len(analogues), 5)
        scores = [a["similarity_pct"] for a in analogues]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(
            self.card["closing_playbook"]["referenced_historical_deals"],
            [a["deal_id"] for a in analogues],
        )

    def test_risks_are_never_empty(self):
        self.assertTrue(self.card["closing_playbook"]["key_risks_and_mitigations"])


class HelperTests(unittest.TestCase):
    def test_size_tiers(self):
        self.assertEqual(size_tier(200), "SMB")
        self.assertEqual(size_tier(201), "Mid-market")
        self.assertEqual(size_tier(1001), "Enterprise")

    def test_make_deal_id_is_deterministic(self):
        self.assertEqual(make_deal_id("A", "Retail", 10), make_deal_id("A", "Retail", 10))

    def test_history_has_both_outcomes_and_required_fields(self):
        outcomes = {d["outcome"] for d in HISTORY}
        self.assertEqual(outcomes, {"WON", "LOST"})
        for deal in HISTORY:
            if deal["outcome"] == "WON":
                self.assertTrue(deal.get("tactics"), deal["deal_id"])
            else:
                self.assertTrue(deal.get("failure_reason"), deal["deal_id"])
                self.assertTrue(deal.get("mitigation"), deal["deal_id"])
        json.dumps(HISTORY)


if __name__ == "__main__":
    unittest.main()
