from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from app.db import Deal
from app.normalize import is_missing, parse_lease_term_months, size_tier


def _first_text(series: pd.Series) -> Optional[str]:
    for value in series:
        if is_missing(value):
            continue
        text = str(value).strip()
        if text and text.lower() != "nan":
            return text
    return None


def _max_number(group: pd.DataFrame, column: str) -> Optional[float]:
    numbers = pd.to_numeric(group[column], errors="coerce").dropna()
    return float(numbers.max()) if len(numbers) else None


def _first_int(series: pd.Series) -> Optional[int]:
    numbers = pd.to_numeric(series, errors="coerce").dropna()
    return int(numbers.iloc[0]) if len(numbers) else None


def _outcome(group: pd.DataFrame) -> Optional[str]:
    # The UAT spreadsheet has no WON/LOST column. Read one if a future export adds it.
    if "Outcome" not in group.columns:
        return None
    value = (_first_text(group["Outcome"]) or "").upper()
    return value if value in {"WON", "LOST"} else None


def read_leasing_xlsx(path: str) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name=0)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def build_deal_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Collapse broker-level rows into one row per deal.

    The source repeats deal-level values (fee, size) on every broker row, so
    numeric fields take the per-deal maximum. Summing them would overcount.
    """
    rows: list[dict[str, Any]] = []
    for deal_name, group in df.groupby("Deal Name", sort=False):
        size = _max_number(group, "Size (sq/ft)")
        terms = [t for t in (parse_lease_term_months(v) for v in group["Lease Term"]) if t is not None]
        lead_agents = group.loc[group["Role"] == "Lead Broker", "Agent Name"]
        done = pd.to_datetime(_first_text(group["Deal Done Date"]), dayfirst=True, errors="coerce")
        rows.append(
            {
                "deal_name": str(deal_name).strip(),
                "account_name": _first_text(group["Account Name"]),
                "industry": _first_text(group["Leasing Industry"]),
                "size_sqft": size,
                "size_tier": size_tier(size),
                "lease_term_months": max(terms) if terms else None,
                "gross_signing_rent_psf": _max_number(group, "Gross Signing Rent (psf/mth)"),
                "gross_fee_sgd": _max_number(group, "Gross Fee (SGD)"),
                "net_fee_collected_sgd": _max_number(group, "Net Fee Collected"),
                "property_name": _first_text(group["Property Name"]),
                "lead_agent": _first_text(lead_agents) or _first_text(group["Agent Name"]),
                "deal_done_date": None if pd.isna(done) else done.date(),
                "billing_status": _first_text(group["Billing Status"]),
                "billing_fy_year": _first_int(group["Billing FY Year"]),
                "outcome": _outcome(group),
                "source_row_count": int(len(group)),
            }
        )
    return rows


def ingest_xlsx(path: str, session_factory) -> dict[str, Any]:
    df = read_leasing_xlsx(path)
    rows = build_deal_rows(df)
    with session_factory() as session:
        for row in rows:
            session.merge(Deal(**row))
        session.commit()
    return {"source": path, "source_rows": int(len(df)), "deals_loaded": len(rows)}
