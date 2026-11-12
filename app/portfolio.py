from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import date
from typing import Any, Callable, Iterable, Optional

from app.db import Deal

SHRINKAGE_K = 5  # pseudo-observations pulling a group's mean log fee toward the overall mean
DAYS_PER_MONTH = 30.4375
NOT_RECORDED = "Not recorded"
FEE_BIN_COUNT = 12
MIN_FEES_FOR_BINS = 5
TOP_INDUSTRIES = 15
TOP_N = 10
MAX_CALLS = 25
CALL_WINDOW_MONTHS = 18
TIER_ORDER = ("S", "M", "L", "XL")

UNBILLED_BUCKETS = ("Under 3 months", "3-6 months", "6-12 months", "Over 12 months", "Date unknown")
EXPIRY_BUCKETS = ("Already expired", "0-6 months", "6-12 months", "12-18 months", "18-24 months", "Over 24 months")


def _fee(deal: Deal) -> Optional[float]:
    fee = deal.gross_fee_sgd
    if fee is None or not math.isfinite(fee) or fee <= 0:
        return None
    return float(fee)


def _text(value: Optional[str]) -> Optional[str]:
    text = (value or "").strip()
    return text or None


def _number(value: Optional[float]) -> bool:
    return value is not None and math.isfinite(value)


def _money(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(float(value), 2)


def _pct(part: float, whole: float) -> Optional[float]:
    return round(part / whole * 100, 1) if whole else None


def _median(values: list[float]) -> Optional[float]:
    return _money(statistics.median(values)) if values else None


def _percentile(sorted_values: list[float], q: float) -> Optional[float]:
    if not sorted_values:
        return None
    position = (len(sorted_values) - 1) * q
    low = math.floor(position)
    high = math.ceil(position)
    value = sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (position - low)
    return _money(value)


def _mean_log(fees: list[float]) -> Optional[float]:
    return statistics.fmean(math.log(f) for f in fees) if fees else None


def _shrunk_median(fees: list[float], global_mean_log: Optional[float]) -> Optional[float]:
    if not fees or global_mean_log is None:
        return None
    n = len(fees)
    blended = (n * _mean_log(fees) + SHRINKAGE_K * global_mean_log) / (n + SHRINKAGE_K)
    return _money(math.exp(blended))


def _months_between(later: date, earlier: date) -> float:
    return (later - earlier).days / DAYS_PER_MONTH


def _group(deals: Iterable[Deal], key: Callable[[Deal], Optional[str]]) -> dict[str, list[Deal]]:
    groups: dict[str, list[Deal]] = defaultdict(list)
    for deal in deals:
        name = key(deal)
        if name is not None:
            groups[name].append(deal)
    return groups


def _fees(deals: Iterable[Deal]) -> list[float]:
    return [f for f in (_fee(d) for d in deals) if f is not None]


def _coverage(deals: list[Deal]) -> list[dict[str, Any]]:
    checks: list[tuple[str, str, Callable[[Deal], bool]]] = [
        ("fee", "Fee recorded", lambda d: _fee(d) is not None),
        ("industry", "Industry recorded", lambda d: _text(d.industry) is not None),
        ("size", "Size recorded", lambda d: _number(d.size_sqft)),
        ("lease_term", "Lease term recorded", lambda d: _number(d.lease_term_months)),
        ("rent", "Signing rent recorded", lambda d: _number(d.gross_signing_rent_psf)),
        ("done_date", "Deal done date recorded", lambda d: d.deal_done_date is not None),
        ("lease_expiry", "Lease expiry date recorded", lambda d: d.lease_expiry_date is not None),
        ("property", "Property recorded", lambda d: _text(d.property_name) is not None),
    ]
    total = len(deals)
    rows = []
    for field, label, present in checks:
        n = sum(1 for d in deals if present(d))
        rows.append({"field": field, "label": label, "n": n, "total": total, "pct": _pct(n, total)})
    return rows


def _fee_bins(fees: list[float]) -> list[dict[str, Any]]:
    if len(fees) < MIN_FEES_FOR_BINS:
        return []
    low, high = min(fees), max(fees)
    if low == high:
        return [{"lo": _money(low), "hi": _money(high), "count": len(fees)}]
    log_low = math.log(low)
    width = (math.log(high) - log_low) / FEE_BIN_COUNT
    counts = [0] * FEE_BIN_COUNT
    for fee in fees:
        index = min(int((math.log(fee) - log_low) / width), FEE_BIN_COUNT - 1)
        counts[index] += 1
    return [
        {
            "lo": _money(math.exp(log_low + i * width)),
            "hi": _money(high if i == FEE_BIN_COUNT - 1 else math.exp(log_low + (i + 1) * width)),
            "count": count,
        }
        for i, count in enumerate(counts)
    ]


def _fee_distribution(deals: list[Deal], fees: list[float]) -> dict[str, Any]:
    ordered = sorted(fees)
    return {
        "n": len(fees),
        "n_zero_or_missing": len(deals) - len(fees),
        "p10": _percentile(ordered, 0.10),
        "p25": _percentile(ordered, 0.25),
        "p50": _percentile(ordered, 0.50),
        "p75": _percentile(ordered, 0.75),
        "p90": _percentile(ordered, 0.90),
        "max": _money(ordered[-1]) if ordered else None,
        "bins": _fee_bins(fees),
    }


def _by_industry(deals: list[Deal], total_fee: float, global_mean_log: Optional[float]) -> list[dict[str, Any]]:
    groups = _group(deals, lambda d: _text(d.industry) or NOT_RECORDED)
    rows = []
    for name, members in groups.items():
        fees = _fees(members)
        rows.append(
            {
                "industry": name,
                "n": len(members),
                "n_with_fee": len(fees),
                "median_fee_sgd": _median(fees),
                "shrunk_median_fee_sgd": _shrunk_median(fees, global_mean_log),
                "total_fee_sgd": _money(sum(fees)),
                "share_of_fees_pct": _pct(sum(fees), total_fee),
            }
        )
    rows.sort(key=lambda r: (-r["total_fee_sgd"], -r["n"], r["industry"]))
    return rows[:TOP_INDUSTRIES]


def _tier_rank(tier: str) -> int:
    if tier == NOT_RECORDED:
        return len(TIER_ORDER) + 1
    head = tier.split(" ", 1)[0]
    return TIER_ORDER.index(head) if head in TIER_ORDER else len(TIER_ORDER)


def _by_size_tier(deals: list[Deal], total_fee: float) -> list[dict[str, Any]]:
    groups = _group(deals, lambda d: _text(d.size_tier) or NOT_RECORDED)
    rows = []
    for name in sorted(groups, key=lambda t: (_tier_rank(t), t)):
        members = groups[name]
        fees = _fees(members)
        rows.append(
            {
                "tier": name,
                "n": len(members),
                "share_of_deals_pct": _pct(len(members), len(deals)),
                "total_fee_sgd": _money(sum(fees)),
                "share_of_fees_pct": _pct(sum(fees), total_fee),
                "median_fee_sgd": _median(fees),
            }
        )
    return rows


def _top_by_fee(
    deals: list[Deal], key: Callable[[Deal], Optional[str]], total_fee: float
) -> list[dict[str, Any]]:
    rows = []
    for name, members in _group(deals, key).items():
        fee = sum(_fees(members))
        rows.append(
            {"name": name, "deals": len(members), "total_fee_sgd": _money(fee), "share_pct": _pct(fee, total_fee)}
        )
    rows.sort(key=lambda r: (-r["total_fee_sgd"], -r["deals"], r["name"]))
    return rows[:TOP_N]


def _concentration(deals: list[Deal], total_fee: float) -> dict[str, Any]:
    accounts = _top_by_fee(deals, lambda d: _text(d.account_name), total_fee)
    top5 = sum(r["total_fee_sgd"] for r in accounts[:5])
    return {
        "top_accounts": accounts,
        "top_properties": _top_by_fee(deals, lambda d: _text(d.property_name), total_fee),
        "top_agents": _top_by_fee(deals, lambda d: _text(d.lead_agent), total_fee),
        "top5_accounts_share_pct": _pct(top5, total_fee),
    }


def _repeat_clients(deals: list[Deal], total_fee: float) -> dict[str, Any]:
    repeats = {n: m for n, m in _group(deals, lambda d: _text(d.account_name)).items() if len(m) >= 2}
    rows = []
    for name, members in repeats.items():
        done = [d.deal_done_date for d in members if d.deal_done_date is not None]
        rows.append(
            {
                "name": name,
                "deals": len(members),
                "total_fee_sgd": _money(sum(_fees(members))),
                "last_done": max(done).isoformat() if done else None,
            }
        )
    rows.sort(key=lambda r: (-r["deals"], -r["total_fee_sgd"], r["name"]))
    repeat_fee = sum(r["total_fee_sgd"] for r in rows)
    return {
        "accounts_with_repeat": len(rows),
        "repeat_share_of_fees_pct": _pct(repeat_fee, total_fee),
        "accounts": rows[:TOP_N],
    }


def _seasonality(deals: list[Deal]) -> dict[str, Any]:
    dated = [d for d in deals if d.deal_done_date is not None]
    years: dict[int, list[Deal]] = defaultdict(list)
    months = [0] * 12
    for d in dated:
        years[d.deal_done_date.year].append(d)
        months[d.deal_done_date.month - 1] += 1
    return {
        "by_year": [
            {"year": year, "deals": len(years[year]), "total_fee_sgd": _money(sum(_fees(years[year])))}
            for year in sorted(years)
        ],
        "by_month": [{"month": i + 1, "deals": count} for i, count in enumerate(months)],
        "n_dated": len(dated),
        "n_total": len(deals),
    }


def _billing_state(deal: Deal) -> str:
    status = (deal.billing_status or "").strip().lower()
    if status == "billed":
        return "billed"
    if status == "not billed":
        return "not_billed"
    return "unknown"


def _unbilled_bucket(deal: Deal, today: date) -> str:
    if deal.deal_done_date is None:
        return "Date unknown"
    age = _months_between(today, deal.deal_done_date)
    if age < 3:
        return "Under 3 months"
    if age < 6:
        return "3-6 months"
    if age < 12:
        return "6-12 months"
    return "Over 12 months"


def _billing(deals: list[Deal], today: date) -> dict[str, Any]:
    states: dict[str, list[Deal]] = {"billed": [], "not_billed": [], "unknown": []}
    for d in deals:
        states[_billing_state(d)].append(d)
    ageing = {bucket: [] for bucket in UNBILLED_BUCKETS}
    for d in states["not_billed"]:
        ageing[_unbilled_bucket(d, today)].append(d)

    def summary(members: list[Deal]) -> dict[str, Any]:
        return {"deals": len(members), "fee_sgd": _money(sum(_fees(members)))}

    return {
        "billed": summary(states["billed"]),
        "not_billed": summary(states["not_billed"]),
        "unknown": summary(states["unknown"]),
        "unbilled_by_age": [{"bucket": b, **summary(ageing[b])} for b in UNBILLED_BUCKETS],
        "n_dated": sum(1 for d in states["not_billed"] if d.deal_done_date is not None),
    }


def _expiry_bucket(months_left: float) -> str:
    if months_left < 0:
        return "Already expired"
    for limit, label in zip((6, 12, 18, 24), EXPIRY_BUCKETS[1:5]):
        if months_left < limit:
            return label
    return "Over 24 months"


def _lease_expiry(deals: list[Deal], today: date) -> dict[str, Any]:
    with_expiry = [d for d in deals if d.lease_expiry_date is not None]
    buckets = {label: [] for label in EXPIRY_BUCKETS}
    upcoming: list[tuple[Deal, float]] = []
    for d in with_expiry:
        months_left = _months_between(d.lease_expiry_date, today)
        buckets[_expiry_bucket(months_left)].append(d)
        if 0 <= months_left <= CALL_WINDOW_MONTHS:
            upcoming.append((d, months_left))
    upcoming.sort(key=lambda item: (item[0].lease_expiry_date, item[0].deal_name))
    return {
        "n_with_expiry": len(with_expiry),
        "n_total": len(deals),
        "buckets": [
            {"label": label, "deals": len(buckets[label]), "fee_sgd": _money(sum(_fees(buckets[label])))}
            for label in EXPIRY_BUCKETS
        ],
        "calls": [
            {
                "deal_name": d.deal_name,
                "account_name": _text(d.account_name),
                "property_name": _text(d.property_name),
                "lead_agent": _text(d.lead_agent),
                "expiry": d.lease_expiry_date.isoformat(),
                "months_left": round(months_left, 1),
                "past_fee_sgd": _money(_fee(d)),
            }
            for d, months_left in upcoming[:MAX_CALLS]
        ],
    }


def _agents(deals: list[Deal], global_mean_log: Optional[float]) -> list[dict[str, Any]]:
    rows = []
    for name, members in _group(deals, lambda d: _text(d.lead_agent)).items():
        fees = _fees(members)
        rows.append(
            {
                "agent": name,
                "deals": len(members),
                "median_fee_sgd": _median(fees),
                "shrunk_median_fee_sgd": _shrunk_median(fees, global_mean_log),
            }
        )
    rows.sort(key=lambda r: (-r["deals"], r["agent"]))
    return rows


def _notes(deals: list[Deal], fees: list[float], billing: dict[str, Any], expiry: dict[str, Any]) -> list[str]:
    total = len(deals)
    if not total:
        return ["No deals are loaded yet. Upload a workbook to see portfolio statistics."]
    notes = [
        "The ledger holds completed deals only, so fees show what was earned on deals that closed. "
        "They are not forecasts for deals still being pursued."
    ]
    outcomes = sum(1 for d in deals if (d.outcome or "").upper() in {"WON", "LOST"})
    if outcomes:
        notes.append(f"Won/lost outcomes are recorded for {outcomes} of {total} deals.")
    else:
        notes.append("No won/lost outcomes are recorded, so a win rate cannot be calculated.")
    if len(fees) < total:
        notes.append(
            f"A fee is recorded for {len(fees)} of {total} deals ({_pct(len(fees), total)}%). "
            "Fee totals and medians cover only those deals; missing fees are not estimated."
        )
    if fees:
        notes.append(
            f"Medians for industries and agents with few deals are pulled toward the overall median "
            f"(weight equal to {SHRINKAGE_K} deals) so small groups do not look extreme."
        )
    if expiry["n_with_expiry"] < total:
        missing = total - expiry["n_with_expiry"]
        notes.append(
            f"{missing} of {total} deals ({_pct(missing, total)}%) have no lease expiry date, "
            "so renewal timing covers only the deals that do."
        )
    undated = sum(1 for d in deals if d.deal_done_date is None)
    if undated:
        notes.append(f"{undated} of {total} deals have no done date and are left out of the yearly and monthly views.")
    if billing["unknown"]["deals"]:
        notes.append(f"{billing['unknown']['deals']} of {total} deals have no recognised billing status.")
    return notes


def compute_portfolio(deals: list[Deal], today: Optional[date] = None) -> dict[str, Any]:
    today = today or date.today()
    fees = _fees(deals)
    total_fee = sum(fees)
    global_mean_log = _mean_log(fees)
    billing = _billing(deals, today)
    expiry = _lease_expiry(deals, today)
    return {
        "as_of": today.isoformat(),
        "totals": {
            "deals": len(deals),
            "accounts": len(_group(deals, lambda d: _text(d.account_name))),
            "properties": len(_group(deals, lambda d: _text(d.property_name))),
            "agents": len(_group(deals, lambda d: _text(d.lead_agent))),
            "industries": len(_group(deals, lambda d: _text(d.industry))),
            "n_with_fee": len(fees),
            "total_fee_sgd": _money(total_fee),
            "median_fee_sgd": _median(fees),
        },
        "coverage": _coverage(deals),
        "fee_distribution": _fee_distribution(deals, fees),
        "by_industry": _by_industry(deals, total_fee, global_mean_log),
        "by_size_tier": _by_size_tier(deals, total_fee),
        "concentration": _concentration(deals, total_fee),
        "repeat_clients": _repeat_clients(deals, total_fee),
        "seasonality": _seasonality(deals),
        "billing": billing,
        "lease_expiry": expiry,
        "agents": _agents(deals, global_mean_log),
        "notes": _notes(deals, fees, billing, expiry),
    }
