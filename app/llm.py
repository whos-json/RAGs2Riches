from __future__ import annotations

import os
import urllib.request
from typing import Any, Optional

from app.config import get_settings

PROVIDER_CATALOG: dict[str, dict[str, Any]] = {
    "template": {
        "label": "Template (offline, no model)",
        "locality": "local",
        "default_model": None,
    },
    "ollama": {
        "label": "Ollama (local)",
        "locality": "local",
        "default_model": "qwen2.5:7b-instruct",
    },
    "openai_compatible": {
        "label": "llama.cpp / LM Studio (local, OpenAI-compatible)",
        "locality": "local",
        "default_model": "local-model",
    },
    "anthropic": {
        "label": "Anthropic (cloud, needs ANTHROPIC_API_KEY)",
        "locality": "cloud",
        "default_model": "claude-haiku-4-5-20251001",
    },
    "openai": {
        "label": "OpenAI (cloud, needs OPENAI_API_KEY)",
        "locality": "cloud",
        "default_model": "gpt-4o-mini",
    },
}


def _probe(url: str, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except Exception:
        return False


def check_provider(name: str) -> dict[str, Any]:
    settings = get_settings()
    if name == "template":
        return {"available": True, "detail": "Built-in, no model needed"}
    if name == "ollama":
        ok = _probe(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
        return {"available": ok, "detail": "reachable" if ok else f"not reachable at {settings.ollama_base_url}"}
    if name == "openai_compatible":
        ok = _probe(f"{settings.openai_compatible_base_url.rstrip('/')}/models")
        detail = "reachable" if ok else f"not reachable at {settings.openai_compatible_base_url}"
        return {"available": ok, "detail": detail}
    env_var = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}[name]
    ok = bool(os.getenv(env_var))
    return {"available": ok, "detail": f"{env_var} set" if ok else f"{env_var} not set"}


def provider_catalog() -> list[dict[str, Any]]:
    catalog = []
    for name, info in PROVIDER_CATALOG.items():
        status = check_provider(name)
        catalog.append({"name": name, **info, **status})
    return catalog


def build_chat_model(provider: str, model: Optional[str]):
    """Return a LangChain chat model for the chosen provider.

    Imports are lazy so template mode works without any LLM packages installed.
    """
    from langchain.chat_models import init_chat_model

    settings = get_settings()
    model = model or PROVIDER_CATALOG[provider]["default_model"]

    if provider == "ollama":
        return init_chat_model(model, model_provider="ollama", base_url=settings.ollama_base_url, temperature=0)
    if provider == "openai_compatible":
        return init_chat_model(
            model,
            model_provider="openai",
            base_url=settings.openai_compatible_base_url,
            api_key=os.getenv("OPENAI_COMPATIBLE_API_KEY", "not-needed"),
            temperature=0,
        )
    if provider == "anthropic":
        _require_env("ANTHROPIC_API_KEY")
        return init_chat_model(model, model_provider="anthropic", temperature=0)
    if provider == "openai":
        _require_env("OPENAI_API_KEY")
        return init_chat_model(model, model_provider="openai", temperature=0)
    raise ValueError(f"Unsupported LLM provider: {provider}")


def _require_env(name: str) -> None:
    if not os.getenv(name):
        raise ValueError(f"{name} is not set in the environment")

