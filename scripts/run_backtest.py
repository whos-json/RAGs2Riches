"""Leave-one-out fee backtest over a leasing workbook.

Ingests the workbook into a throwaway SQLite DB (the real DB is never touched),
runs the backtest in both pool regimes, prints tables and writes JSON.

Usage:
    python scripts/run_backtest.py [workbook.xlsx] [--k 5] [--out data/backtest_report.json]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.backtest import format_report, run_all  # noqa: E402
from app.db import Deal, init_db, make_engine, session_factory  # noqa: E402
from app.ingest import ingest_xlsx  # noqa: E402

DEFAULT_WORKBOOK = Path.home() / "Downloads" / "mock leasing data.xlsx"


def load_deals(workbook: str) -> list[Deal]:
    with tempfile.TemporaryDirectory() as tmp:
        db_url = "sqlite:///" + (Path(tmp) / "backtest.db").as_posix()
        engine = make_engine(db_url)
        init_db(engine)
        factory = session_factory(engine)
        ingest_xlsx(workbook, factory)
        with factory() as session:
            deals = list(session.scalars(select(Deal)).all())
        engine.dispose()
    return deals


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__