from __future__ import annotations

import math
from statistics import mean, median, quantiles
from typing import Any, Callable, Iterable, Optional

from app.db import Deal
from app.schemas import BaselineMetrics

# Minimum pool size before a match level is accepted. Uncalibrated: chosen so a
# median is not driven by one or two deals. Revisit once outcome data exists.
MIN_COMPARABLES = 5
# Quartiles need a handful of points to mean anything; below this they are omitted.
MIN_FEES_FOR_QUARTILES = 4


def _positive(values: Iterable[Any]) -> list[float]:
    """Keep finite, strictly positive numbers.

    Drops None, NaN, +/-inf, zero and negatives so a single bad ledger row
    cannot poison a median (or make it non-JSON-serialisable).
    """
    cleaned: list[float] = []
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number > 0:
            cleaned.append(number)
    return cleaned


def _text_key(value: Optional[str]) -> Optional[str]:
    """Case/whitespace-insensitive key for category matching."""
    if value is None:
        return None
    key = " ".join(str(value).split()).casefold()
    return key or None


def _outcome(deal: Deal) -> Optional[str]:
    value = (deal.outcome or "").strip().upper()
    return value if value in {"WON", "LOST"} else None


def _fee_quartiles(fees: list[float]) -> tuple[Optional[float], Optional[float]]:
    if len(fees) < MIN_FEES_FOR_QUARTILES:
        return None, None
    q1, _, q3 = quantiles(fees, n=4, method="inclusive")
    return round(q1, 2), round(q3, 2)


def fee_percentile(fees: Iterable[float], value: float) -> Optional[float]:
    """Percent (0-100, 1 dp) of usable comparable fees at or below ``value``.

    Mid-rank convention: fees strictly below count fully, equal fees count half.
    Non-positive and non-finite fees are ignored. None when no usable fee exists
    or ``value`` is not a finite number.
    """
    usable = _positive(fees)
    if not usable:
        return None
    try:
        target = float(value)
    except (TypeError, ValueError):
        return None
    if isinstance(value, bool) or not math.isfinite(target):
        return None
    below = sum(1 for f in usable if f < target)
    equal = sum(1 for f in usable if f == target)
    return round(100 * (below + 0.5 * equal) / len(usable), 1)


def compute_baseline(
    deals: list[Deal], normalized: dict, exclude_name: Optional[str] = None
) -> BaselineMetrics:
    """Aggregate comparables, widening the match until enough deals are found.

    Match order: industry + size tier, size tier, industry, then all deals.
    Medians (not means) are the headline figures because ledger fees and sizes
    are heavily right-skewed. Non-positive, NaN and infinite values are ignored.
    Win rate is only reported when at least one WON/LOST outcome exists; it is
    never inferred from missing outcomes.
    """
    industry = _text_key(normalized.get("industry"))
    tier = normalized.get("size_tier")
    pool = [d for d in deals if exclude_name is None or d.deal_name != exclude_name]

    levels: list[tuple[str, Callable[[Deal], bool]]] = []
    if industry and tier:
        levels.append(
            ("industry + size tier", lambda d: _text_key(d.industry) == industry and d.size_tier == tier)
        )
    if tier:
        levels.append(("size tier", lambda d: d.size_tier == tier))
    if industry:
        levels.append(("industry", lambda d: _text_key(d.industry) == industry))
    levels.append(("all deals", lambda d: True))

    match_level, comps = "all deals (insufficient matches)", pool
    for label, predicate in levels:
        matched = [d for d in pool if predicate(d)]
        if len(matched) >= MIN_COMPARABLES:
            match_level, comps = label, matched
            break

    fees = _positive(d.gross_fee_sgd for d in comps)
    sizes = _positive(d.size_sqft for d in comps)
    terms = _positive(d.lease_term_months for d in comps)
    won = sum(1 for d in comps if _outcome(d) == "WON")
    lost = sum(1 for d in comps if _outcome(d) == "LOST")
    decided = won + lost
    fee_p25, fee_p75 = _fee_quartiles(fees)

    return BaselineMetrics(
        match_level=match_level,
        n_comparables=len(comps),
        n_with_fee=len(fees),
        median_fee_sgd=round(median(fees), 2) if fees else None,
        mean_fee_sgd=round(mean(fees), 2) if fees else None,
        fee_p25_sgd=fee_p25,
        fee_p75_sgd=fee_p75,
        fee_min_sgd=round(min(fees), 2) if fees else None,
        fee_max_sgd=round(max(fees), 2) if fees else None,
        median_size_sqft=round(median(sizes), 1) if sizes else None,
        median_lease_term_months=round(median(terms), 1) if terms else None,
        outcome_coverage=decided,
        win_rate_pct=round(100 * won / decided, 1) if decided else None,
    )
