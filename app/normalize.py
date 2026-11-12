from __future__ import annotations

import math
import re
from typing import Any, Optional

SIZE_TIERS = [
    (5_000, "S (<=5k sqft)"),
    (10_000, "M (5k-10k sqft)"),
    (20_000, "L (10k-20k sqft)"),
]
XL_TIER = "XL (>20k sqft)"

_YEARS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:years?|yrs?|y)\b")
_MONTHS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:months?|mths?|mth)\b")


def is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def size_tier(size_sqft: Optional[float]) -> Optional[str]:
    if size_sqft is None or math.isnan(size_sqft):
        return None
    for limit, label in SIZE_TIERS:
        if size_sqft <= limit:
            return label
    return XL_TIER


def parse_lease_term_months(raw: Any) -> Optional[float]:
    """Parse messy lease-term text such as '3 years', '36 mths', '2 years 15 days'.

    Days are ignored. A bare number is treated as months.
    """
    if is_missing(raw):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().lower()
    if not text:
        return None
    years = _YEARS.search(text)
    months = _MONTHS.search(text)
    if years or months:
        total = 0.0
        if years:
            total += float(years.group(1)) * 12
        if months:
            total += float(months.group(1))
        return total
    try:
        return float(text)
    except ValueError:
        return None


def term_band(months: Optional[float]) -> Optional[str]:
    if months is None or math.isnan(months):
        return None
    if months <= 12:
        return "<=12m"
    if months <= 24:
        return "13-24m"
    if months <= 36:
        return "25-36m"
    if months <= 60:
        return "37-60m"
    return ">60m"
