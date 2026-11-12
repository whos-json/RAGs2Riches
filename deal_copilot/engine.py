"""Local scoring engine for the Deal Intelligence & Sales Copilot.

Runs the three inference steps from the build guide without external services:
  1. Baseline aggregation over historical deals (stands in for PostgreSQL SQL).
  2. Analogue retrieval by keyword overlap (stands in for Pinecone search).
  3. Rule-based synthesis into the Structured Deal Scorecard (stands in for the LLM).

The weights and thresholds are placeholders. Calibrate them against real
outcomes (build guide, Phase 3 backtesting) before relying on the numbers.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from pathlib import Path
from typing import Any

OPTIONS: dict[str, list[str]] = {
    "industries": ["Fintech", "Healthcare", "Retail", "Manufacturing", "Software"],
    "stages": ["Discovery", "Proposal", "Negotiation"],
    "sponsors": ["Executive engaged", "Champion only", "No access yet"],
    "needs": ["High", "Medium", "Low"],
}

# Fit points per factor. Budget 20 + sponsor 25 + need 20 + timeline 15 + stage 20 = 100.
BUDGET_POINTS = 20
SPONSOR_POINTS = {"Executive engaged": 25, "Champion only": 12, "No access yet": 0}
NEED_POINTS = {"High": 20, "Medium": 10, "Low": 0}
STAGE_POINTS = {"Discovery": 5, "Proposal": 10, "Negotiation": 20}

MIN_SCOPE_SAMPLE = 3
MAX_ANALOGUE_SCORE = 1.35  # keyword overlap (max 1.0) + same-industry bonus + same-size-tier bonus
ANALOGUE_LIMIT = 5
STOP_WORDS = {"and", "the", "for", "with", "that", "before", "after", "from", "into", "our", "their"}


def load_history(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def size_tier(employees: int) -> str:
    if employees <= 200:
        return "SMB"
    if employees <= 1000:
        return "Mid-market"
    return "Enterprise"


def validate_input(payload: Any) -> dict[str, Any]:
    """Return a cleaned copy of the request payload, or raise ValueError with a user-facing message."""
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")

    account = str(payload.get("account_name") or "").strip()
    if not account or len(account) > 120:
        raise ValueError("Account name is required (max 120 characters).")

    return {
        "account_name": account,
        "industry": _choice(payload, "industry", OPTIONS["industries"]),
        "stage": _choice(payload, "stage", OPTIONS["stages"]),
        "sponsor": _choice(payload, "sponsor", OPTIONS["sponsors"]),
        "need": _choice(payload, "need", OPTIONS["needs"]),
        "employees": _positive(payload, "employees", whole=True),
        "deal_value_usd": _positive(payload, "deal_value_usd"),
        "expected_close_days": _positive(payload, "expected_close_days", whole=True),
        "budget_confirmed": _flag(payload, "budget_confirmed"),
        "notes": str(payload.get("notes") or "").strip()[:2000],
    }


def _choice(payload: dict[str, Any], key: str, allowed: list[str]) -> str:
    value = payload.get(key)
    if value not in allowed:
        raise ValueError(f"{key} must be one of: {', '.join(allowed)}.")
    return value


def _positive(payload: dict[str, Any], key: str, whole: bool = False) -> float | int:
    try:
        value = float(payload.get(key))
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be a number.") from None
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{key} must be greater than zero.")
    return max(1, int(value)) if whole else value


def _flag(payload: dict[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be true or false.")
    return value


def make_deal_id(account: str, industry: str, deal_value: float) -> str:
    # Five digits keeps new IDs clear of the four-digit IDs in the sample history.
    digest = hashlib.sha256(f"{account}|{industry}|{deal_value}".encode("utf-8")).hexdigest()
    return f"DEAL-{int(digest[:8], 16) % 90000 + 10000}"


def baseline(history: list[dict[str, Any]], industry: str, tier: str) -> dict[str, Any]:
    """Step 1: win rate and medians for the narrowest scope with enough history."""
    scopes = [
        (f"{industry}, {tier}", [d for d in history if d["industry"] == industry and size_tier(d["employees"]) == tier]),
        (industry, [d for d in history if d["industry"] == industry]),
        ("all industries", history),
    ]
    basis, deals = next(((name, ds) for name, ds in scopes if len(ds) >= MIN_SCOPE_SAMPLE), scopes[-1])
    wins = sum(1 for d in deals if d["outcome"] == "WON")
    return {
        "basis": basis,
        "sample_size": len(deals),
        "win_rate_pct": round(100 * wins / len(deals), 1),
        "median_deal_value_usd": round(statistics.median(d["deal_value_usd"] for d in deals)),
        "median_cycle_days": round(statistics.median(d["sales_cycle_days"] for d in deals)),
    }


def _keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 2 and w not in STOP_WORDS}


def find_analogues(history: list[dict[str, Any]], deal: dict[str, Any], limit: int = ANALOGUE_LIMIT) -> list[dict[str, Any]]:
    """Step 2: rank historical deals by note overlap, boosted for same industry and size tier."""
    new_words = _keywords(deal["notes"])
    tier = size_tier(deal["employees"])
    scored = []
    for past in history:
        past_words = _keywords(past["notes"])
        union = new_words | past_words
        score = len(new_words & past_words) / len(union) if union else 0.0
        if past["industry"] == deal["industry"]:
            score += 0.25
        if size_tier(past["employees"]) == tier:
            score += 0.10
        scored.append((score, past))
    scored.sort(key=lambda item: (-item[0], item[1]["deal_id"]))
    return [
        {
            "deal_id": past["deal_id"],
            "account_name": past["account_name"],
            "industry": past["industry"],
            "outcome": past["outcome"],
            "deal_value_usd": past["deal_value_usd"],
            "notes": past["notes"],
            "similarity_pct": round(100 * score / MAX_ANALOGUE_SCORE),
            "tactics": past.get("tactics"),
            "failure_reason": past.get("failure_reason"),
            "mitigation": past.get("mitigation"),
        }
        for score, past in scored[:limit]
    ]


def _timeline_points(days: int) -> int:
    if days <= 90:
        return 15
    if days <= 180:
        return 8
    return 0


def fit_breakdown(deal: dict[str, Any]) -> dict[str, int]:
    return {
        "budget": BUDGET_POINTS if deal["budget_confirmed"] else 0,
        "authority": SPONSOR_POINTS[deal["sponsor"]],
        "need": NEED_POINTS[deal["need"]],
        "timeline": _timeline_points(deal["expected_close_days"]),
        "stage": STAGE_POINTS[deal["stage"]],
    }


def _recommendation(fit: int) -> str:
    if fit >= 75:
        return "PURSUE_HIGH_PRIORITY"
    if fit >= 50:
        return "PURSUE"
    if fit >= 35:
        return "QUALIFY_FURTHER"
    return "DEPRIORITIZE"


def _effort(recommendation: str, deal: dict[str, Any]) -> dict[str, Any]:
    if recommendation == "PURSUE_HIGH_PRIORITY" and deal["deal_value_usd"] >= 100_000:
        tier, hours = "Tier 1 - High Touch", 25
        resources = [
            "Assign dedicated Solutions Architect for custom POC",
            "Executive sponsor alignment call by Week 2",
        ]
    elif recommendation in ("PURSUE_HIGH_PRIORITY", "PURSUE"):
        tier, hours = "Tier 2 - Standard", 12
        resources = [
            "Assign account executive with a solutions engineer on call",
            "Share the case study from the closest WON analogue",
        ]
    else:
        tier, hours = "Tier 3 - Light Touch", 4
        resources = [
            "Run one discovery call to confirm budget and sponsor",
            "Keep on nurture until qualification improves",
        ]
    if not deal["budget_confirmed"]:
        resources.append("Confirm budget range with the economic buyer")
    if deal["sponsor"] != "Executive engaged":
        resources.append("Map and engage an executive sponsor")
    return {"tier": tier, "recommended_resources": resources, "max_recommended_hours": hours}


def _winning_strategy(analogues: list[dict[str, Any]]) -> str:
    won = [a for a in analogues if a["outcome"] == "WON" and a["tactics"]]
    if not won:
        return "None of the closest analogues were won. Confirm qualification gaps before investing in a proposal."
    won_count = sum(1 for a in analogues if a["outcome"] == "WON")
    return f"{won[0]['tactics']} {won_count} of the {len(analogues)} closest analogues were won."


def _risks(deal: dict[str, Any], analogues: list[dict[str, Any]]) -> list[str]:
    risks = []
    if not deal["budget_confirmed"]:
        risks.append("Risk: Budget is not confirmed. Mitigation: Confirm budget owner and range before the demo.")
    if deal["sponsor"] == "No access yet":
        risks.append("Risk: No executive access. Mitigation: Secure an executive sponsor before the proposal stage.")
    for a in [a for a in analogues if a["outcome"] == "LOST"][:3]:
        risks.append(f"Risk: {a['failure_reason']} Mitigation: {a['mitigation']}")
    return risks[:4] or ["No specific close risks found in the closest analogues."]


def score_deal(payload: Any, history: list[dict[str, Any]]) -> dict[str, Any]:
    """Run all three steps and return the Structured Deal Scorecard."""
    deal = validate_input(payload)
    tier = size_tier(deal["employees"])
    base = baseline(history, deal["industry"], tier)
    analogues = find_analogues(history, deal)

    parts = fit_breakdown(deal)
    fit = sum(parts.values())
    win = min(99, max(1, round(0.6 * base["win_rate_pct"] + 0.4 * fit)))
    recommendation = _recommendation(fit)
    confidence = "HIGH" if base["sample_size"] >= 8 else "MEDIUM" if base["sample_size"] >= 5 else "LOW"

    return {
        "deal_id": make_deal_id(deal["account_name"], deal["industry"], deal["deal_value_usd"]),
        "account_name": deal["account_name"],
        "qualification": {
            "pursue_recommendation": recommendation,
            "fit_score": fit,
            "framework_breakdown": {
                "budget": "Confirmed" if deal["budget_confirmed"] else "Not confirmed",
                "authority": deal["sponsor"],
                "need": f"{deal['need']} urgency",
                "timeline": f"{deal['expected_close_days']} days expected",
                "stage": deal["stage"],
            },
            "fit_points": parts,
        },
        "estimates": {
            "win_probability_pct": win,
            # Expected value: deal value x win probability.
            "estimated_revenue_usd": round(deal["deal_value_usd"] * win / 100),
            # Blend of the stated close date and the historical median cycle.
            "estimated_timeframe_days": round(0.5 * deal["expected_close_days"] + 0.5 * base["median_cycle_days"]),
            "confidence_level": confidence,
        },
        "effort_allocation": _effort(recommendation, deal),
        "closing_playbook": {
            "winning_strategy": _winning_strategy(analogues),
            "key_risks_and_mitigations": _risks(deal, analogues),
            "referenced_historical_deals": [a["deal_id"] for a in analogues],
        },
        "baseline": base,
        "analogues": analogues,
    }
