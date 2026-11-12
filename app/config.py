from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    database_url: str
    source_xlsx: str
    default_llm_provider: str
    default_llm_model: str | None
    ollama_base_url: str
    openai_compatible_base_url: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    default_db = (ROOT_DIR / "data" / "deals.db").as_posix()
    return Settings(
        database_url=os.getenv("DATABASE_URL", f"sqlite:///{default_db}"),
        source_xlsx=os.getenv("SOURCE_XLSX", r"C:\Users\justin.fan\Downloads\mock leasing data.xlsx"),
        default_llm_provider=os.getenv("LLM_PROVIDER", "template"),
        default_llm_model=os.getenv("LLM_MODEL") or None,
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        openai_compatible_base_url=os.getenv("OPENAI_COMPATIBLE_BASE_URL", "http://localhost:8080/v1"),
    )
