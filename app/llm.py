from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

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
        # llama.cpp ignores the model name. LM Studio uses it to pick a loaded model,
        # so set OPENAI_COMPATIBLE_MODEL (or pick a model in the UI) to match.
        "locality": "local",
        "default_model": get_settings().openai_compatible_model or "local-model",
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

MAX_MODEL_NAME_LENGTH = 200
# Covers Ollama tags (qwen2.5:7b-instruct), HF-style paths (org/model.gguf), and
# vendor ids (gpt-4o-mini). No whitespace, quotes, or control characters.
_MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]*$")

PROBE_TIMEOUT_SECONDS = 1.5
PROBE_CACHE_TTL_SECONDS = 15.0


def validate_model_name(model: Optional[str]) -> Optional[str]:
    """Return a cleaned model name (None when blank) or raise ValueError."""
    if model is None:
        return None
    model = model.strip()
    if not model:
        return None
    if len(model) > MAX_MODEL_NAME_LENGTH:
        raise ValueError(f"Model name must be at most {MAX_MODEL_NAME_LENGTH} characters.")
    if ".." in model or not _MODEL_NAME_RE.match(model):
        raise ValueError("Model name may only contain letters, digits and . _ : / @ + - characters.")
    return model


def default_model_for(provider: str) -> Optional[str]:
    if provider == "openai_compatible":
        return get_settings().openai_compatible_model or PROVIDER_CATALOG[provider]["default_model"]
    return PROVIDER_CATALOG[provider]["default_model"]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D401
        return None


# No redirects (a configured host cannot bounce the probe elsewhere) and no env proxies.
_PROBE_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def _probe(url: str, timeout: float = PROBE_TIMEOUT_SECONDS) -> bool:
    """True if the server answered at all (any status below 500)."""
    try:
        with _PROBE_OPENER.open(url, timeout=timeout):
            return True
    except urllib.error.HTTPError as exc:
        return exc.code < 500
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


_NETWORK_PROVIDERS = ("ollama", "openai_compatible")
_probe_lock = threading.Lock()
_probe_cache: dict[str, Any] = {"key": None, "expires": 0.0, "status": {}}


def _network_status() -> dict[str, dict[str, Any]]:
    """Probe local runtimes in parallel and cache the result briefly.

    The lock makes concurrent page loads share one probe round instead of each
    paying up to PROBE_TIMEOUT_SECONDS per provider. Callers run in FastAPI's
    threadpool (sync endpoints), so waiting here never blocks the event loop.
    """
    settings = get_settings()
    key = (settings.ollama_base_url, settings.openai_compatible_base_url)
    with _probe_lock:
        now = time.monotonic()
        if _probe_cache["key"] == key and now < _probe_cache["expires"]:
            return _probe_cache["status"]
        with ThreadPoolExecutor(max_workers=len(_NETWORK_PROVIDERS)) as pool:
            results = list(pool.map(check_provider, _NETWORK_PROVIDERS))
        status = dict(zip(_NETWORK_PROVIDERS, results))
        _probe_cache.update(key=key, expires=time.monotonic() + PROBE_CACHE_TTL_SECONDS, status=status)
        return status


def reset_probe_cache() -> None:
    with _probe_lock:
        _probe_cache.update(key=None, expires=0.0, status={})


def provider_catalog() -> list[dict[str, Any]]:
    network = _network_status()
    catalog = []
    for name, info in PROVIDER_CATALOG.items():
        status = network[name] if name in network else check_provider(name)
        catalog.append({"name": name, **info, "default_model": default_model_for(name), **status})
    return catalog


def _init_chat_model(*args: Any, **kwargs: Any):
    """Lazy import so template mode works without any LLM packages installed."""
    from langchain.chat_models import init_chat_model

    return init_chat_model(*args, **kwargs)


def build_chat_model(provider: str, model: Optional[str]):
    """Return a LangChain chat model for the chosen provider.

    Base URLs come only from server settings, never from request data. The returned
    model falls back to plain JSON parsing when native structured output fails.
    """
    if provider not in PROVIDER_CATALOG or provider == "template":
        raise ValueError(f"Unsupported LLM provider: {provider}")
    settings = get_settings()
    model = validate_model_name(model) or default_model_for(provider)
    timeout = settings.llm_timeout_seconds

    if provider == "ollama":
        chat_model = _init_chat_model(
            model,
            model_provider="ollama",
            base_url=settings.ollama_base_url,
            temperature=0,
            client_kwargs={"timeout": timeout},
        )
    elif provider == "openai_compatible":
        chat_model = _init_chat_model(
            model,
            model_provider="openai",
            base_url=settings.openai_compatible_base_url,
            api_key=os.getenv("OPENAI_COMPATIBLE_API_KEY", "not-needed"),
            temperature=0,
            timeout=timeout,
            max_retries=1,
        )
    elif provider == "anthropic":
        _require_env("ANTHROPIC_API_KEY")
        chat_model = _init_chat_model(
            model, model_provider="anthropic", temperature=0, timeout=timeout, max_retries=1
        )
    else:
        _require_env("OPENAI_API_KEY")
        chat_model = _init_chat_model(
            model, model_provider="openai", temperature=0, timeout=timeout, max_retries=1
        )
    return StructuredFallbackModel(chat_model)


def _require_env(name: str) -> None:
    if not os.getenv(name):
        raise ValueError(f"{name} is not set in the environment")


# --- Structured output with a JSON-parsing fallback -----------------------------------------

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_MAX_PARSE_CHARS = 50_000
# Failures where retrying the same server with another strategy only doubles the wait.
_TRANSPORT_ERROR_MARKERS = (
    "timeout",
    "connecterror",
    "connectionerror",
    "apiconnection",
    "authentication",
    "permissiondenied",
    "ratelimit",
)


def _is_transport_error(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    return any(marker in cls.__name__.lower() for cls in type(exc).__mro__ for marker in _TRANSPORT_ERROR_MARKERS)


def _message_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") in (None, "text"):
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return str(content)


def parse_structured_text(text: str, schema):
    """Extract the first JSON object in `text` that validates against `schema`.

    Tolerates code fences, <think> blocks and prose around the JSON.
    """
    from pydantic import ValidationError

    text = _THINK_RE.sub("", text or "")[:_MAX_PARSE_CHARS]
    candidates = [m.group(1) for m in _FENCE_RE.finditer(text)] + [text]
    decoder = json.JSONDecoder()
    last_error: Optional[Exception] = None
    for candidate in candidates:
        start = candidate.find("{")
        while start != -1:
            try:
                obj, _end = decoder.raw_decode(candidate[start:])
            except ValueError as exc:
                last_error = exc
            else:
                if isinstance(obj, dict):
                    try:
                        return schema.model_validate(obj)
                    except ValidationError as exc:
                        last_error = exc
            start = candidate.find("{", start + 1)
    raise ValueError(f"Model output did not contain valid {schema.__name__} JSON: {last_error}")


def structured_runnable(model: Any, schema, **kwargs: Any):
    """Runnable producing `schema` instances: native structured output first, then JSON parsing.

    Local models served through llama.cpp/LM Studio/Ollama often lack tool calling or
    schema-constrained decoding, in which case the native call raises. The fallback
    asks for a JSON object in plain text and validates it ourselves. Timeouts and
    connection errors are not retried with the fallback.
    """
    from langchain_core.messages import HumanMessage
    from langchain_core.runnables import RunnableLambda

    try:
        native = model.with_structured_output(schema, **kwargs)
    except Exception as exc:
        logger.info("Native structured output unavailable (%s: %s)", type(exc).__name__, exc)
        native = None

    instructions = (
        "Respond with a single JSON object and nothing else (no markdown, no commentary) "
        f"that conforms to this JSON Schema:\n{json.dumps(schema.model_json_schema())}"
    )

    def run(prompt_value, config=None):
        if native is not None:
            try:
                return native.invoke(prompt_value, config)
            except Exception as exc:
                if _is_transport_error(exc):
                    raise
                logger.warning("Native structured output failed (%s: %s); parsing JSON text", type(exc).__name__, exc)
        messages = prompt_value.to_messages() if hasattr(prompt_value, "to_messages") else list(prompt_value)
        reply = model.invoke([*messages, HumanMessage(content=instructions)], config)
        return parse_structured_text(_message_text(reply), schema)

    return RunnableLambda(run)


class StructuredFallbackModel:
    """Thin proxy that adds the JSON fallback to `with_structured_output`.

    Everything else is delegated to the wrapped chat model.
    """

    def __init__(self, model: Any):
        self._model = model

    def __getattr__(self, name: str) -> Any:
        return getattr(self._model, name)

    def with_structured_output(self, schema, **kwargs: Any):
        if isinstance(schema, type) and hasattr(schema, "model_json_schema"):
            return structured_runnable(self._model, schema, **kwargs)
        return self._model.with_structured_output(schema, **kwargs)
