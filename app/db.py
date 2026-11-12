from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


class Deal(Base):
    __tablename__ = "deals"

    deal_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    account_name: Mapped[Optional[str]] = mapped_column(String(255))
    industry: Mapped[Optional[str]] = mapped_column(String(120), index=True)
    size_sqft: Mapped[Optional[float]] = mapped_column(Float)
    size_tier: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    lease_term_months: Mapped[Optional[float]] = mapped_column(Float)
    gross_signing_rent_psf: Mapped[Optional[float]] = mapped_column(Float)
    gross_fee_sgd: Mapped[Optional[float]] = mapped_column(Float)
    net_fee_collected_sgd: Mapped[Optional[float]] = mapped_column(Float)
    property_name: Mapped[Optional[str]] = mapped_column(String(255))
    lead_agent: Mapped[Optional[str]] = mapped_column(String(120))
    deal_done_date: Mapped[Optional[date]] = mapped_column(Date)
    billing_status: Mapped[Optional[str]] = mapped_column(String(30))
    billing_fy_year: Mapped[Optional[int]] = mapped_column(Integer)
    outcome: Mapped[Optional[str]] = mapped_column(String(10))
    lease_commence_date: Mapped[Optional[date]] = mapped_column(Date)
    lease_expiry_date: Mapped[Optional[date]] = mapped_column(Date)
    source_row_count: Mapped[int] = mapped_column(Integer, default=0)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    deal_id: Mapped[str] = mapped_column(String(255), index=True)
    outcome: Mapped[Optional[str]] = mapped_column(String(10))
    useful: Mapped[Optional[bool]] = mapped_column(Boolean)
    note: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


ADDED_DEAL_COLUMNS = {"lease_commence_date": "DATE", "lease_expiry_date": "DATE"}


def make_engine(url: Optional[str] = None) -> Engine:
    url = url or get_settings().database_url
    connect_args: dict = {}
    if url.startswith("sqlite:///"):
        db_path = Path(url.removeprefix("sqlite:///"))
        db_path.parent.mkdir(parents=True, exist_ok=True)
        connect_args["check_same_thread"] = False
    return create_engine(url, connect_args=connect_args)


def _add_missing_deal_columns(engine: Engine) -> None:
    existing = {c["name"] for c in inspect(engine).get_columns(Deal.__tablename__)}
    missing = [(name, ddl) for name, ddl in ADDED_DEAL_COLUMNS.items() if name not in existing]
    if not missing:
        return
    with engine.begin() as conn:
        for name, ddl in missing:
            conn.execute(text(f"ALTER TABLE {Deal.__tablename__} ADD COLUMN {name} {ddl}"))


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    _add_missing_deal_columns(engine)


def session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)
