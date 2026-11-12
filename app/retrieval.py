from __future__ import annotations

import math
import re
from collections import Counter
from typing import Optional

from app.db import Deal
from app.normalize import term_band
from app.schemas import Analogue

TOKEN_RE = re.compile(r"[a-z0-9]+")


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
        features.append(f"prop_{_slug(property_name)}")
    return features


def _norm(vector: dict[str, float]) -> float:
    return math.sqrt(sum(v * v for v in vector.values()))


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
    """
    docs: list[tuple[Deal, Counter]] = []
    for deal in deals:
        if deal.deal_name == exclude_name:
            continue
        if outcome and deal.outcome != outcome:
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
    idf = {t: math.log((n_docs + 1) / (df + 1)) + 1 for t, df in doc_freq.items()}

    q_vec = {t: tf * idf[t] for t, tf in query_counts.items() if t in idf}
    q_norm = _norm(q_vec)
    if not q_vec:
        return []

    scored: list[tuple[float, Deal]] = []
    for deal, counts in docs:
        d_vec = {t: tf * idf[t] for t, tf in counts.items()}
        d_norm = _norm(d_vec)
        if d_norm == 0:
            continue
        dot = sum(weight * d_vec[t] for t, weight in q_vec.items() if t in d_vec)
        similarity = dot / (q_norm * d_norm)
        if similarity > 0:
            scored.append((similarity, deal))

    scored.sort(key=lambda item: (-item[0], item[1].deal_name))
    return [
        Analogue(
            deal_name=deal.deal_name,
            industry=deal.industry,
            size_sqft=deal.size_sqft,
            lease_term_months=deal.lease_term_months,
            gross_fee_sgd=deal.gross_fee_sgd,
            outcome=deal.outcome,
            similarity=round(similarity, 3),
        )
        for similarity, deal in scored[:k]
    ]
