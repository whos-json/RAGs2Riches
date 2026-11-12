from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parent.parent

DEFAULT_LLM_TIMEOUT_SECONDS = 60.0
MAX_LLM_TIMEOUT_SECONDS = 600.0
DEFAULT_ALLOWED_HOSTS = ("localhost", "127.0.0.1", "testserver")


@dataclass(frozen=True)
class Settings:
    database_url: str
    source_xlsx: str
    default_llm_provider: str
    default_llm_model: str | None
    ollama_base_url: str
    openai_compatible_base_url: str
    openai_compatible_model: str | None = None
    llm_timeout_seconds: float = DEFAULT_LLM_TIMEOUT_SECONDS
    ingest_dir: str = ""
    allowed_hosts: tuple[str, ...] = DEFAULT_ALLOWED_HOSTS


def _http_url(name: str, default: str) -> str:
    """Read a base URL from the environment and allow only http(s).

    Base URLs are server configuration only. Rejecting other schemes stops a
    misconfiguration such as `file://` from being fetched by the provider probe.
    """
    value = (os.getenv(name) or default).strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{name} must be an http(s) URL with a host, got {value!r}")
    return value


def _timeout(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number of seconds, got {raw!r}") from exc
    if not 0 < value <= MAX_LLM_TIMEOUT_SECONDS:
        raise ValueError(f"{name} must be between 0 and {MAX_LLM_TIMEOUT_SECONDS:g} seconds")
    return value


def _csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return tuple(part.strip() for part in raw.split(",") if part.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    default_db = (ROOT_DIR / "data" / "deals.db").as_posix()
    return Settings(
        database_url=os.getenv("DATABASE_URL", f"sqlite:///{default_db}"),
        source_xlsx=os.getenv("SOURCE_XLSX", r"C:\Users\justin.fan\Downloads\mock leasing data.xlsx"),
        default_llm_provider=os.getenv("LLM_PROVIDER", "template"),
        default_llm_model=os.getenv("LLM_MODEL") or None,
        ollama_base_url=_http_url("OLLAMA_BASE_URL", "http://localhost:11434"),
        openai_compatible_base_url=_http_url("OPENAI_COMPATIBLE_BASE_URL", "http://localhost:8080/v1"),
        openai_compatible_model=os.getenv("OPENAI_COMPATIBLE_MODEL") or None,
        llm_timeout_seconds=_timeout("LLM_TIMEOUT_SECONDS", DEFAULT_LLM_TIMEOUT_SECONDS),
        ingest_dir=os.getenv("INGEST_DIR") or str(ROOT_DIR / "data" / "uploads"),
        allowed_hosts=_csv("ALLOWED_HOSTS", DEFAULT_ALLOWED_HOSTS),
    )
