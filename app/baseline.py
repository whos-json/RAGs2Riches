from __future__ import annotations

from statistics import mean, median
from typing import Callable, Optional

from app.db import Deal
from app.schemas import BaselineMetrics

MIN_COMPARABLES = 5


def _positive(values: list[Optional[float]]) -> list[float]:
    return [v for v in values if v is not None and v > 0]


def compute_baseline(
    deals: list[Deal], normalized: dict, exclude_name: Optional[str] = None
) -> BaselineMetrics:
    """Aggregate comparables, widening the match until enough deals are found.

    Match order: industry + size tier, size tier, industry, then all deals.
    """
    industry = normalized.get("industry")
    tier = normalized.get("size_tier")
    pool = [d for d in deals if d.deal_name != exclude_name]

    levels: list[tuple[str, Callable[[Deal], bool]]] = []
    if industry and tier:
        levels.append(("industry + size tier", lambda d: d.industry == industry and d.size_tier == tier))
    if tier:
        levels.append(("size tier", lambda d: d.size_tier == tier))
    if industry:
        levels.append(("industry", lambda d: d.industry == industry))
    levels.append(("all deals", lambda d: True))

    match_level, comps = "all deals (insufficient matches)", pool
    for label, predicate in levels:
        matched = [d for d in pool if predicate(d)]
        if len(matched) >= MIN_COMPARABLES:
            match_level, comps = label, matched
            break

    fees = _positive([d.gross_fee_sgd for d in comps])
    sizes = _positive([d.size_sqft for d in comps])
    terms = _positive([d.lease_term_months for d in comps])
    won = sum(1 for d in comps if d.outcome == "WON")
    lost = sum(1 for d in comps if d.outcome == "LOST")
    decided = won + lost

    return BaselineMetrics(
        match_level=match_level,
        n_comparables=len(comps),
        n_with_fee=len(fees),
        median_fee_sgd=round(median(fees), 2) if fees else None,
        mean_fee_sgd=round(mean(fees), 2) if fees else None,
        median_size_sqft=round(median(sizes), 1) if sizes else None,
        median_lease_term_months=round(median(terms), 1) if terms else None,
        outcome_coverage=decided,
        win_rate_pct=round(100 * won / decided, 1) if decided else None,
    )
