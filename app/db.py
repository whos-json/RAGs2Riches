from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

from sqlalchemy import Date, Float, Integer, String, create_engine
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
    source_row_count: Mapped[int] = mapped_column(Integer, default=0)


def make_engine(url: Optional[str] = None) -> Engine:
    url = url or get_settings().database_url
    connect_args: dict = {}
    if url.startswith("sqlite:///"):
        db_path = Path(url.removeprefix("sqlite:///"))
        db_path.parent.mkdir(parents=True, exist_ok=True)
        connect_args["check_same_thread"] = False
    return create_engine(url, connect_args=connect_args)


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)
