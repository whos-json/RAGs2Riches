from __future__ import annotations

import math
import re
from collections import Counter
from typing import Optional

from app.db import Deal
from app.normalize import term_band
from app.schemas import Analogue

TOKEN_RE = re.compile(r"[a-z0-9]+")

# Feature prefixes that count as a "meaningful" overlap. A shared lease-term
# band alone is too weak to call a deal an analogue.
CORE_FEATURE_PREFIXES = ("ind_", "size_", "prop_")
# Uncalibrated floor on cosine similarity below which a match is noise.
MIN_SIMILARITY = 0.15
# Similarities are compared at this precision when ranking so float noise
# cannot reorder genuine ties; ties then break on deal_name.
_RANK_PRECISION = 9


def _slug(text: str) -> str:
    return "_".join(TOKEN_RE.findall(text.lower()))


def _features(
    industry: Optional[str],
    tier: Optional[str],
    band: Optional[str],
    property_name: Optional[str],
) -> list[str]:
    features: list[str] = []
    if industry:
        features += [f"ind_{token}" for token in TOKEN_RE.findall(industry.lower())]
    if tier:
        features.append(f"size_{_slug(tier)}")
    if band:
        features.append(f"term_{_slug(band)}")
    if property_name:
        slug = _slug(property_name)
        if slug:
            features.append(f"prop_{slug}")
    return features


def _norm(vector: dict[str, float]) -> float:
    return math.sqrt(sum(v * v for v in vector.values()))


def _has_core_overlap(shared: set[str]) -> bool:
    return any(feature.startswith(CORE_FEATURE_PREFIXES) for feature in shared)


def _matched_on(shared: set[str]) -> list[str]:
    """Plain-English reasons a deal matched, derived from the shared features."""
    reasons: list[str] = []
    if any(f.startswith("ind_") for f in shared):
        reasons.append("same industry")
    if any(f.startswith("size_") for f in shared):
        reasons.append("same size band")
    if any(f.startswith("term_") for f in shared):
        reasons.append("similar lease length")
    if any(f.startswith("prop_") for f in shared):
        reasons.append("same building")
    return reasons


def find_analogues(
    deals: list[Deal],
    query: dict,
    k: int = 5,
    exclude_name: Optional[str] = None,
    outcome: Optional[str] = None,
) -> list[Analogue]:
    """Local TF-IDF cosine search over structured deal features.

    Pure Python, no paid embedding service. Swap in an embedding model later
    without changing callers. Account names are excluded from the features.

    A deal is returned only if it shares at least one core feature (industry
    token, size tier or property) with the query and scores at least
    ``MIN_SIMILARITY``. Results are ordered by similarity, then ``deal_name``,
    so equal scores always come back in the same order.
    """
    if k <= 0:
        return []
    wanted_outcome = outcome.strip().upper() if outcome else None

    docs: list[tuple[Deal, Counter]] = []
    for deal in deals:
        if exclude_name is not None and deal.deal_name == exclude_name:
            continue
        if wanted_outcome and (deal.outcome or "").strip().upper() != wanted_outcome:
            continue
        feats = _features(
            deal.industry, deal.size_tier, term_band(deal.lease_term_months), deal.property_name
        )
        docs.append((deal, Counter(feats)))

    query_counts = Counter(
        _features(
            query.get("industry"),
            query.get("size_tier"),
            term_band(query.get("lease_term_months")),
            query.get("property_name"),
        )
    )
    if not query_counts or not docs:
        return []

    doc_freq: Counter = Counter()
    for _, counts in docs:
        doc_freq.update(counts.keys())
    n_docs = len(docs)

    def idf(term: str) -> float:
        # Query terms absent from the corpus get the highest idf (df=0) rather
        # than being dropped: dropping them would let a deal that matches only
        # the remaining terms look like a perfect match.
        return math.log((n_docs + 1) / (doc_freq.get(term, 0) + 1)) + 1

    q_vec = {t: tf * idf(t) for t, tf in query_counts.items()}
    q_norm = _norm(q_vec)
    if q_norm == 0:
        return []

    scored: list[tuple[float, Deal, list[str]]] = []
    for deal, counts in docs:
        d_vec = {t: tf * idf(t) for t, tf in counts.items()}
        d_norm = _norm(d_vec)
        if d_norm == 0:
            continue
        shared = set(q_vec) & set(d_vec)
        if not _has_core_overlap(shared):
            continue
        dot = sum(q_vec[t] * d_vec[t] for t in sorted(shared))
        similarity = dot / (q_norm * d_norm)
        if similarity >= MIN_SIMILARITY:
            scored.append((similarity, deal, _matched_on(shared)))

    scored.sort(key=lambda item: (-round(item[0], _RANK_PRECISION), item[1].deal_name))
    return [
        Analogue(
            deal_name=deal.deal_name,
            industry=deal.industry,
            size_sqft=deal.size_sqft,
            lease_term_months=deal.lease_term_months,
            gross_fee_sgd=deal.gross_fee_sgd,
            outcome=deal.outcome,
            similarity=round(min(similarity, 1.0), 3),
            matched_on=matched_on,
        )
        for similarity, deal, matched_on in scored[:k]
    ]
