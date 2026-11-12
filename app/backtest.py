"""Leave-one-out backtest of the engine's fee comparables.

The ledger has no WON/LOST outcome, so win probability cannot be backtested.
What *is* verifiable is the gross fee: for every deal with a known positive
fee we hide that deal, ask the engine what it would have predicted from the
remaining deals, and compare with the fee actually earned.

Everything here is pure (no DB, no I/O): functions take a list of ``Deal``
objects and return plain dicts, so results are JSON-serialisable and easy to
test. The engine's own public functions (``compute_baseline`` and
``find_analogues``) are called exactly as the workflow calls them.

Predictors compared (all leave-one-out):

* ``engine``        median fee of the comparable pool from ``compute_baseline``;
                    interval = its P25-P75 (what the scorecard shows).
* ``analogue_knn``  median fee of the top-k ``find_analogues`` results;
                    interval = quartiles of those fees when >= 4 exist.
* ``nn1``           fee of the single nearest analogue (no interval).
* ``naive``         global median of every other deal; interval = global P25-P75.
* ``analogue_psf``  diagnostic: median fee-per-sqft of the analogues x the
                    deal's size. Only defined when the deal has a size.
* ``naive_psf``     diagnostic: global median fee-per-sqft x the deal's size.

Two pool regimes: ``same_client_allowed`` (what the engine does today, only the
deal itself is hidden) and ``client_held_out`` (every deal from the same
account is hidden too, which removes repeat-client leakage).
"""

from __future__ import annotations

import math
import random
from collections import Counter
from statistics import median, quantiles
from typing import Any, Callable, Iterable, Optional

from app.baseline import compute_baseline
from app.db import Deal
from app.normalize import size_tier as compute_size_tier
from app.normalize import term_band
from app.retrieval import find_analogues

METHODS = ("engine", "analogue_knn", "nn1", "naive", "analogue_psf", "naive_psf")
HEADLINE_METHODS = ("engine", "analogue_knn", "naive")
UNKNOWN = "(unknown)"
OTHER = "(other, small groups)"
SIMILARITY_EDGES = (0.4, 0.7, 0.9)
MIN_QUARTILE_POINTS = 4


# --------------------------------------------------------------------------- helpers
def _key(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = " ".join(str(value).split()).casefold()
    return text or None


def _usable(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _quartiles(values: list[float]) -> tuple[Optional[float], Optional[float]]:
    if len(values) < MIN_QUARTILE_POINTS:
        return None, None
    q1, _, q3 = quantiles(values, n=4, method="inclusive")
    return q1, q3


def _pred(point: Optional[float], lo: Optional[float] = None, hi: Optional[float] = None) -> Optional[dict]:
    if point is None:
        return None
    return {"pred": float(point), "lo": lo, "hi": hi}


def build_query(deal: Deal, include_property: bool = True) -> dict:
    """The normalized dict the workflow would build for this deal (minus the fee)."""
    size = _usable(deal.size_sqft)
    term = _usable(deal.lease_term_months)
    industry = (deal.industry or "").strip() or None
    return {
        "deal_name": deal.deal_name,
        "industry": industry,
        "size_sqft": size,
        "size_tier": compute_size_tier(size) if size is not None else None,
        "lease_term_months": term,
        "lease_term_band": term_band(term),
        "gross_signing_rent_psf": _usable(deal.gross_signing_rent_psf),
        "property_name": deal.property_name if include_property else None,
    }


def _pool(deals: list[Deal], target: Deal, hold_out_client: bool) -> list[Deal]:
    account = _key(target.account_name)
    pool = []
    for d in deals:
        if d.deal_name == target.deal_name:
            continue
        if hold_out_client and account is not None and _key(d.account_name) == account:
            continue
        pool.append(d)
    return pool


# --------------------------------------------------------------------------- per-deal
def predict_one(
    target: Deal,
    deals: list[Deal],
    k: int = 5,
    hold_out_client: bool = False,
    include_property: bool = True,
) -> dict:
    """Predict ``target``'s fee from every other deal; return a record dict."""
    actual = _usable(target.gross_fee_sgd)
    if actual is None:
        raise ValueError(f"{target.deal_name!r} has no positive fee to backtest")
    pool = _pool(deals, target, hold_out_client)
    query = build_query(target, include_property)
    size = query["size_sqft"]

    metrics = compute_baseline(pool, query, exclude_name=target.deal_name)
    analogues = find_analogues(pool, query, k=k, exclude_name=target.deal_name)
    by_name = {d.deal_name: d for d in pool}

    preds: dict[str, Optional[dict]] = {}
    preds["engine"] = _pred(
        getattr(metrics, "median_fee_sgd", None),
        getattr(metrics, "fee_p25_sgd", None),
        getattr(metrics, "fee_p75_sgd", None),
    )

    an_fees = [f for f in (_usable(a.gross_fee_sgd) for a in analogues) if f is not None]
    lo, hi = _quartiles(an_fees)
    preds["analogue_knn"] = _pred(median(an_fees), lo, hi) if an_fees else None
    nn_fee = _usable(analogues[0].gross_fee_sgd) if analogues else None
    preds["nn1"] = _pred(nn_fee)

    pool_fees = [f for f in (_usable(d.gross_fee_sgd) for d in pool) if f is not None]
    glo, ghi = _quartiles(pool_fees)
    preds["naive"] = _pred(median(pool_fees), glo, ghi) if pool_fees else None

    preds["analogue_psf"] = preds["naive_psf"] = None
    if size is not None:
        an_psf = [
            f / s
            for a in analogues
            if (f := _usable(a.gross_fee_sgd)) is not None and (s := _usable(a.size_sqft)) is not None
        ]
        if an_psf:
            plo, phi = _quartiles(an_psf)
            preds["analogue_psf"] = _pred(
                median(an_psf) * size,
                plo * size if plo is not None else None,
                phi * size if phi is not None else None,
            )
        pool_psf = [
            f / s
            for d in pool
            if (f := _usable(d.gross_fee_sgd)) is not None and (s := _usable(d.size_sqft)) is not None
        ]
        if pool_psf:
            plo, phi = _quartiles(pool_psf)
            preds["naive_psf"] = _pred(
                median(pool_psf) * size,
                plo * size if plo is not None else None,
                phi * size if phi is not None else None,
            )

    # Analogue quality: did the retrieved deals really resemble the query?
    t_ind, t_tier = _key(target.industry), target.size_tier
    nn = by_name.get(analogues[0].deal_name) if analogues else None
    top = [by_name[a.deal_name] for a in analogues if a.deal_name in by_name]
    return {
        "deal_name": target.deal_name,
        "industry": target.industry,
        "size_tier": target.size_tier,
        "actual": actual,
        "match_level": getattr(metrics, "match_level", UNKNOWN),
        "n_comparables": getattr(metrics, "n_comparables", None),
        "preds": preds,
        "n_analogues": len(analogues),
        "nn_similarity": analogues[0].similarity if analogues else None,
        "nn_same_industry": (_key(nn.industry) == t_ind) if nn is not None and t_ind else None,
        "nn_same_tier": (nn.size_tier == t_tier) if nn is not None and t_tier else None,
        "topk_same_industry": _share(top, lambda d: _key(d.industry) == t_ind) if t_ind else None,
        "topk_same_tier": _share(top, lambda d: d.size_tier == t_tier) if t_tier else None,
    }


def _share(items: list[Any], pred: Callable[[Any], bool]) -> Optional[float]:
    return sum(1 for i in items if pred(i)) / len(items) if items else None


# --------------------------------------------------------------------------- metrics
def error_metrics(rows: Iterable[tuple[float, Optional[dict]]]) -> dict:
    """Accuracy summary for ``(actual, prediction-or-None)`` pairs.

    * ``mape`` / ``mdape``: mean / median absolute % error vs. actual. The mean is
      dominated by a few over-predictions of small deals; read the median first.
    * ``wmape``: sum|error| / sum(actual): weights by fee, so it tracks revenue.
    * ``bias_pct``: mean signed % error (pred-actual)/actual. Positive = over-predicts.
    * ``median_signed_pct``: the robust version of bias.
    * ``within_iqr_pct``: % of deals whose actual fee lies in [lo, hi]; the
      denominator is only deals that had an interval (``n_interval``).
    * ``within_50pct``: % of deals predicted within +/-50% of actual.
    """
    actuals, preds, signed, ape = [], [], [], []
    inside = n_interval = 0
    for actual, p in rows:
        if p is None or p.get("pred") is None:
            continue
        a, point = float(actual), float(p["pred"])
        actuals.append(a)
        preds.append(point)
        signed.append((point - a) / a)
        ape.append(abs(point - a) / a)
        lo, hi = p.get("lo"), p.get("hi")
        if lo is not None and hi is not None:
            n_interval += 1
            inside += lo <= a <= hi
    n = len(actuals)
    if n == 0:
        return {"n": 0}
    abs_err = [abs(p - a) for p, a in zip(preds, actuals)]
    return {
        "n": n,
        "mape_pct": round(100 * sum(ape) / n, 1),
        "mdape_pct": round(100 * median(ape), 1),
        "wmape_pct": round(100 * sum(abs_err) / sum(actuals), 1),
        "bias_pct": round(100 * sum(signed) / n, 1),
        "median_signed_pct": round(100 * median(signed), 1),
        "median_abs_error_sgd": round(median(abs_err), 0),
        "within_50pct": round(100 * sum(1 for e in ape if e <= 0.5) / n, 1),
        "n_interval": n_interval,
        "within_iqr_pct": round(100 * inside / n_interval, 1) if n_interval else None,
    }


def _method_metrics(records: list[dict], methods: Iterable[str] = METHODS) -> dict:
    return {m: error_metrics((r["actual"], r["preds"].get(m)) for r in records) for m in methods}


def _ape(record: dict, method: str) -> Optional[float]:
    p = record["preds"].get(method)
    return None if p is None else abs(p["pred"] - record["actual"]) / record["actual"]


def head_to_head(
    records: list[dict], method: str, rival: str = "naive", n_boot: int = 1000, seed: int = 0
) -> dict:
    """Paired comparison of ``method`` against ``rival`` on deals both predict.

    Reports how often ``method`` has the smaller absolute % error and a
    bootstrap 95% interval for median-APE(method) - median-APE(rival), in
    percentage points (negative = ``method`` is better).
    """
    pairs = [(a, b) for r in records if (a := _ape(r, method)) is not None and (b := _ape(r, rival)) is not None]
    n = len(pairs)
    if n == 0:
        return {"method": method, "rival": rival, "n": 0}
    wins = sum(1 for a, b in pairs if a < b)
    ties = sum(1 for a, b in pairs if a == b)
    rng = random.Random(seed)
    diffs = []
    for _ in range(n_boot):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        diffs.append(100 * (median(a for a, _ in sample) - median(b for _, b in sample)))
    diffs.sort()
    return {
        "method": method,
        "rival": rival,
        "n": n,
        "win_pct": round(100 * wins / n, 1),
        "tie_pct": round(100 * ties / n, 1),
        "mdape_diff_pp": round(100 * (median(a for a, _ in pairs) - median(b for _, b in pairs)), 1),
        "mdape_diff_ci95_pp": [round(diffs[int(0.025 * n_boot)], 1), round(diffs[int(0.975 * n_boot) - 1], 1)],
    }


def _breakdown(
    records: list[dict],
    label: Callable[[dict], str],
    min_group: int = 1,
    methods: Iterable[str] = HEADLINE_METHODS,
) -> dict:
    groups: dict[str, list[dict]] = {}
    for r in records:
        groups.setdefault(label(r), []).append(r)
    if min_group > 1:
        small = [g for g, rs in groups.items() if len(rs) < min_group and g != UNKNOWN]
        for g in small:
            groups.setdefault(OTHER, []).extend(groups.pop(g))
    ordered = sorted(groups.items(), key=lambda kv: (kv[0] in (OTHER, UNKNOWN), -len(kv[1]), kv[0]))
    return {g: _method_metrics(rs, methods) for g, rs in ordered}


def _fee_band_labeller(records: list[dict]) -> Callable[[dict], str]:
    fees = sorted(r["actual"] for r in records)
    if len(fees) < MIN_QUARTILE_POINTS:
        return lambda r: "all"
    q1, q2, q3 = quantiles(fees, n=4, method="inclusive")

    def label(r: dict) -> str:
        a = r["actual"]
        if a <= q1:
            return f"Q1 lowest fees (<= {q1:,.0f})"
        if a <= q2:
            return f"Q2 ({q1:,.0f}-{q2:,.0f})"
        if a <= q3:
            return f"Q3 ({q2:,.0f}-{q3:,.0f})"
        return f"Q4 highest fees (> {q3:,.0f})"

    return label


def _similarity_label(r: dict) -> str:
    s = r["nn_similarity"]
    if s is None:
        return "no analogue"
    lo = 0.0
    for edge in SIMILARITY_EDGES:
        if s < edge:
            return f"nn similarity {lo:.1f}-{edge:.1f}"
        lo = edge
    return f"nn similarity >= {lo:.1f}"


def analogue_quality(records: list[dict], deals: list[Deal]) -> dict:
    """How often the nearest analogue (and the top-k on average) shares industry / size tier.

    ``chance_*`` is the probability two random distinct deals share the attribute,
    i.e. what a random "analogue" would score; the lift over chance is the real signal.
    """

    def rate(field: str) -> tuple[Optional[float], int]:
        vals = [r[field] for r in records if r[field] is not None]
        return (round(100 * sum(vals) / len(vals), 1) if vals else None), len(vals)

    def chance(values: list[Optional[str]]) -> Optional[float]:
        known = [v for v in values if v]
        n = len(known)
        if n < 2:
            return None
        same = sum(c * (c - 1) for c in Counter(known).values())
        return round(100 * same / (n * (n - 1)), 1)

    ind_rate, ind_n = rate("nn_same_industry")
    tier_rate, tier_n = rate("nn_same_tier")
    topk_ind, _ = rate("topk_same_industry")
    topk_tier, _ = rate("topk_same_tier")
    sims = [r["nn_similarity"] for r in records if r["nn_similarity"] is not None]
    return {
        "deals": len(records),
        "with_any_analogue_pct": round(100 * len(sims) / len(records), 1) if records else None,
        "median_nn_similarity": round(median(sims), 3) if sims else None,
        "nn_same_industry_pct": ind_rate,
        "nn_same_industry_n": ind_n,
        "nn_same_tier_pct": tier_rate,
        "nn_same_tier_n": tier_n,
        "topk_same_industry_pct": None if topk_ind is None else topk_ind,
        "topk_same_tier_pct": None if topk_tier is None else topk_tier,
        "chance_same_industry_pct": chance([_key(d.industry) for d in deals]),
        "chance_same_tier_pct": chance([d.size_tier for d in deals]),
    }


# --------------------------------------------------------------------------- top level
def run_backtest(
    deals: list[Deal],
    k: int = 5,
    hold_out_client: bool = False,
    min_group: int = 10,
    include_property: bool = True,
    n_boot: int = 1000,
) -> dict:
    """Leave-one-out backtest over every deal with a positive gross fee."""
    targets = [d for d in deals if _usable(d.gross_fee_sgd) is not None]
    records = [predict_one(d, deals, k, hold_out_client, include_property) for d in targets]
    return {
        "regime": "client_held_out" if hold_out_client else "same_client_allowed",
        "k": k,
        "n_deals": len(deals),
        "n_backtested": len(records),
        "overall": _method_metrics(records),
        "head_to_head": [head_to_head(records, m, "naive", n_boot) for m in METHODS if m != "naive"],
        "by_match_level": _breakdown(records, lambda r: r["match_level"]),
        "by_industry": _breakdown(records, lambda r: r["industry"] or UNKNOWN, min_group),
        "by_size_tier": _breakdown(records, lambda r: r["size_tier"] or UNKNOWN),
        "by_actual_fee_quartile": _breakdown(records, _fee_band_labeller(records)),
        "by_nn_similarity": _breakdown(records, _similarity_label),
        "analogue_quality": analogue_quality(records, deals),
        "records": records,
    }


def run_all(deals: list[Deal], k: int = 5, **kwargs: Any) -> dict:
    """Both pool regimes, so leakage from repeat clients is visible side by side."""
    return {
        "same_client_allowed": run_backtest(deals, k=k, hold_out_client=False, **kwargs),
        "client_held_out": run_backtest(deals, k=k, hold_out_client=True, **kwargs),
    }


# --------------------------------------------------------------------------- text report
def _fmt(value: Any, suffix: str = "") -> str:
    return "-" if value is None else f"{value}{suffix}"


def _overall_table(report: dict) -> list[str]:
    cols = ["n", "mape_pct", "mdape_pct", "wmape_pct", "bias_pct", "median_signed_pct", "within_iqr_pct", "within_50pct"]
    head = ["method", "n", "MAPE%", "MdAPE%", "wMAPE%", "bias%", "medSgn%", "inIQR%", "in50%"]
    lines = ["  ".join(f"{h:>9}" if i else f"{h:<13}" for i, h in enumerate(head))]
    for m in METHODS:
        s = report["overall"][m]
        cells = [_fmt(s.get(c)) for c in cols]
        lines.append(f"{m:<13}" + "  ".join(f"{c:>9}" for c in cells))
    return lines


def _group_table(title: str, groups: dict) -> list[str]:
    lines = [f"{title}", f"  {'group':<38}{'n':>5}  {'eng MdAPE':>9} {'naive MdAPE':>11} {'eng MAPE':>9} {'naive MAPE':>10} {'eng inIQR':>9} {'eng bias':>8}"]
    for name, by_method in groups.items():
        e, nv = by_method["engine"], by_method["naive"]
        lines.append(
            f"  {name[:37]:<38}{e.get('n', 0):>5}  {_fmt(e.get('mdape_pct')):>9} {_fmt(nv.get('mdape_pct')):>11} "
            f"{_fmt(e.get('mape_pct')):>9} {_fmt(nv.get('mape_pct')):>10} {_fmt(e.get('within_iqr_pct')):>9} {_fmt(e.get('bias_pct')):>8}"
        )
    return lines


def format_report(report: dict) -> str:
    out = [
        f"=== Regime: {report['regime']}  (k={report['k']}, backtested {report['n_backtested']} of {report['n_deals']} deals) ===",
        "",
        *_overall_table(report),
        "",
        "Head-to-head vs naive (paired; diff = median APE method - naive, pp, negative is better):",
    ]
    for h in report["head_to_head"]:
        if h["n"]:
            out.append(
                f"  {h['method']:<13} n={h['n']:<4} wins {h['win_pct']}%  diff {h['mdape_diff_pp']:+.1f}pp  95% CI {h['mdape_diff_ci95_pp']}"
            )
    for title, key in (
        ("By match level (engine's chosen level):", "by_match_level"),
        ("By industry:", "by_industry"),
        ("By size tier:", "by_size_tier"),
        ("By actual fee quartile (conditions on the outcome; shows regression to the mean):", "by_actual_fee_quartile"),
        ("By nearest-analogue similarity:", "by_nn_similarity"),
    ):
        out += ["", *_group_table(title, report[key])]
    q = report["analogue_quality"]
    out += [
        "",
        "Analogue quality:",
        f"  deals with >=1 analogue: {_fmt(q['with_any_analogue_pct'], '%')}   median nearest similarity: {_fmt(q['median_nn_similarity'])}",
        f"  nearest shares industry: {_fmt(q['nn_same_industry_pct'], '%')} (n={q['nn_same_industry_n']}; chance {_fmt(q['chance_same_industry_pct'], '%')})",
        f"  nearest shares size tier: {_fmt(q['nn_same_tier_pct'], '%')} (n={q['nn_same_tier_n']}; chance {_fmt(q['chance_same_tier_pct'], '%')})",
        f"  top-k avg share industry: {_fmt(q['topk_same_industry_pct'], '%')}   size tier: {_fmt(q['topk_same_tier_pct'], '%')}",
    ]
    return "\n".join(out)
