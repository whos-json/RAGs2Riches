"""Security and robustness tests. None of these need network access."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app import llm as llm_mod
from app.api import create_app
from app.config import get_settings
from app.redaction import alias, redact_text
from app.schemas import LLMSelection


@pytest.fixture
def env(tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'extra.db').as_posix()}")
    # Does not exist at startup so the lifespan does not try to ingest it.
    monkeypatch.setenv("SOURCE_XLSX", str(tmp_path / "source.xlsx"))
    monkeypatch.setenv("INGEST_DIR", str(uploads))
    get_settings.cache_clear()
    llm_mod.reset_probe_cache()
    yield tmp_path
    get_settings.cache_clear()
    llm_mod.reset_probe_cache()


@pytest.fixture
def client(env):
    with TestClient(create_app()) as test_client:
        yield test_client


def _events(response) -> list[dict]:
    return [
        json.loads(chunk[len("data: "):])
        for chunk in response.text.split("\n\n")
        if chunk.startswith("data: ")
    ]


# --- /api/ingest -----------------------------------------------------------------------------


@pytest.fixture
def fake_ingest(monkeypatch):
    calls: list[str] = []

    def fake(path, _sessions):
        calls.append(path)
        return {"source": path, "source_rows": 1, "deals_loaded": 1}

    monkeypatch.setattr("app.api.ingest_xlsx", fake)
    return calls


@pytest.mark.parametrize("bad_path", ["../secret.xlsx", "sub/../../secret.xlsx", "..\\secret.xlsx"])
def test_ingest_rejects_traversal(client, env, fake_ingest, bad_path):
    (env / "secret.xlsx").write_bytes(b"x")
    response = client.post("/api/ingest", json={"path": bad_path})
    assert response.status_code == 400
    assert fake_ingest == []


def test_ingest_rejects_unc_and_nul_paths(client, fake_ingest):
    assert client.post("/api/ingest", json={"path": "\\\\host\\share\\a.xlsx"}).status_code == 400
    assert client.post("/api/ingest", json={"path": "//host/share/a.xlsx"}).status_code == 400
    assert client.post("/api/ingest", json={"path": "a\u0000.xlsx"}).status_code == 400
    assert fake_ingest == []


def test_ingest_rejects_absolute_path_outside_allowed_locations(client, env, fake_ingest):
    outside = env / "outside.xlsx"
    outside.write_bytes(b"x")
    response = client.post("/api/ingest", json={"path": str(outside)})
    assert response.status_code == 403
    assert fake_ingest == []


def test_ingest_rejects_non_xlsx(client, env, fake_ingest):
    (env / "uploads" / "notes.txt").write_text("hi")
    response = client.post("/api/ingest", json={"path": "notes.txt"})
    assert response.status_code == 400
    assert fake_ingest == []


def test_ingest_missing_file_is_404_without_echoing_path(client, fake_ingest):
    response = client.post("/api/ingest", json={"path": "nope.xlsx"})
    assert response.status_code == 404
    assert "nope" not in response.text and "uploads" not in response.text


def test_ingest_accepts_file_inside_ingest_dir(client, env, fake_ingest):
    (env / "uploads" / "ok.xlsx").write_bytes(b"x")
    response = client.post("/api/ingest", json={"path": "ok.xlsx"})
    assert response.status_code == 200
    assert response.json()["source"] == "ok.xlsx"
    assert len(fake_ingest) == 1


def test_ingest_default_uses_configured_source(client, env, fake_ingest):
    (env / "source.xlsx").write_bytes(b"x")
    response = client.post("/api/ingest", json={})
    assert response.status_code == 200
    assert response.json()["source"] == "source.xlsx"


def test_ingest_failure_returns_422_without_internal_details(client, env, monkeypatch):
    (env / "uploads" / "bad.xlsx").write_bytes(b"x")

    def boom(_path, _sessions):
        raise KeyError("Deal Name")

    monkeypatch.setattr("app.api.ingest_xlsx", boom)
    response = client.post("/api/ingest", json={"path": "bad.xlsx"})
    assert response.status_code == 422
    assert "Deal Name" not in response.text


# --- other endpoints -------------------------------------------------------------------------


@pytest.mark.parametrize("limit", [-1, 0, 1001])
def test_deals_limit_is_bounded(client, limit):
    assert client.get(f"/api/deals?limit={limit}").status_code == 422


def test_deals_default_limit_ok(client):
    assert client.get("/api/deals").status_code == 200


def test_unknown_host_header_is_rejected(client):
    assert client.get("/api/deals", headers={"host": "evil.example"}).status_code == 400


def test_no_cors_headers_are_sent(client):
    response = client.get("/api/deals", headers={"origin": "http://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_meta_probes_are_cached(client, monkeypatch):
    probed: list[str] = []

    def fake_probe(url, timeout=1.5):
        probed.append(url)
        return False

    monkeypatch.setattr(llm_mod, "_probe", fake_probe)
    llm_mod.reset_probe_cache()
    first = client.get("/api/meta")
    second = client.get("/api/meta")
    assert first.status_code == second.status_code == 200
    assert len(probed) == 2  # one per local runtime, only for the first request
    names = [p["name"] for p in first.json()["providers"]]
    assert names == list(llm_mod.PROVIDER_CATALOG)


# --- /api/evaluate model validation -----------------------------------------------------------


@pytest.mark.parametrize("model", ["bad model", "x; rm -rf /", "../etc/passwd", "a" * 201, "-flag"])
@pytest.mark.parametrize("path", ["/api/evaluate", "/api/evaluate/stream"])
def test_evaluate_rejects_bad_model_names(client, model, path):
    response = client.post(path, json={"deal": {"industry": "Tech"}, "llm": {"provider": "ollama", "model": model}})
    assert response.status_code == 422


def test_validate_model_name():
    assert llm_mod.validate_model_name(None) is None
    assert llm_mod.validate_model_name("   ") is None
    assert llm_mod.validate_model_name(" qwen2.5:7b-instruct ") == "qwen2.5:7b-instruct"
    assert llm_mod.validate_model_name("org/model-Q4_K_M.gguf") == "org/model-Q4_K_M.gguf"
    with pytest.raises(ValueError):
        llm_mod.validate_model_name("a" * 201)
    with pytest.raises(ValueError):
        llm_mod.validate_model_name("bad\nname")


# --- SSE stream -------------------------------------------------------------------------------


def test_stream_worker_error_terminates_with_run_error(client, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("kaboom " + "x" * 1000)

    monkeypatch.setattr("app.api.run_workflow", boom)
    response = client.post("/api/evaluate/stream", json={"deal": {"industry": "Tech"}})
    assert response.status_code == 200
    events = _events(response)
    assert events[-1]["type"] == "run_error"
    assert events[-1]["error"].startswith("RuntimeError: kaboom")
    assert len(events[-1]["error"]) < 400


def test_stream_invalid_deal_is_rejected_before_streaming(client):
    response = client.post("/api/evaluate/stream", json={"deal": {"size_sqft": -5}})
    assert response.status_code == 422


# --- SSRF: base URLs only from server config ---------------------------------------------------


def test_request_schema_has_no_base_url_field():
    selection = LLMSelection.model_validate(
        {"provider": "ollama", "model": "m", "base_url": "http://169.254.169.254"}
    )
    assert not hasattr(selection, "base_url")
    assert "base_url" not in selection.model_dump()


@pytest.mark.parametrize(
    "provider, env_name",
    [("ollama", "OLLAMA_BASE_URL"), ("openai_compatible", "OPENAI_COMPATIBLE_BASE_URL")],
)
def test_build_chat_model_uses_server_configured_base_url_and_timeout(env, monkeypatch, provider, env_name):
    monkeypatch.setenv(env_name, "http://configured.local:1234/v1")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "12")
    get_settings.cache_clear()
    captured: dict = {}

    def fake_init(model, **kwargs):
        captured["model"] = model
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(llm_mod, "_init_chat_model", fake_init)
    llm_mod.build_chat_model(provider, "my-model")
    assert captured["model"] == "my-model"
    assert captured["base_url"] == "http://configured.local:1234/v1"
    timeout = captured.get("timeout") or captured["client_kwargs"]["timeout"]
    assert timeout == 12.0


def test_build_chat_model_rejects_invalid_model(env):
    with pytest.raises(ValueError):
        llm_mod.build_chat_model("ollama", "bad model name")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://host/x", "localhost:11434", "http://"])
def test_config_rejects_non_http_base_urls(monkeypatch, url):
    monkeypatch.setenv("OLLAMA_BASE_URL", url)
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError):
            get_settings()
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


# --- structured output fallback ---------------------------------------------------------------


class _Out(BaseModel):
    winning_strategy: str
    items: list[str] = []


def test_parse_structured_text_handles_fences_think_and_prose():
    text = '<think>hmm {"a": 1}</think>Here you go:\n```json\n{"winning_strategy": "go", "items": ["a"]}\n```\nDone.'
    parsed = llm_mod.parse_structured_text(text, _Out)
    assert parsed.winning_strategy == "go" and parsed.items == ["a"]


def test_parse_structured_text_rejects_garbage():
    with pytest.raises(ValueError):
        llm_mod.parse_structured_text("no json here", _Out)
    with pytest.raises(ValueError):
        llm_mod.parse_structured_text('{"wrong": 1}', _Out)


class _FakeLocalModel:
    """Chat model without tool-calling support: native structured output raises."""

    def __init__(self, reply, native_error=NotImplementedError("no tools")):
        self.reply = reply
        self.native_error = native_error
        self.invocations = 0

    def with_structured_output(self, schema, **kwargs):
        error = self.native_error

        class _Native:
            def invoke(self, *_args, **_kwargs):
                raise error

        return _Native()

    def invoke(self, messages, config=None):
        from langchain_core.messages import AIMessage

        self.invocations += 1
        return AIMessage(content=self.reply)


def _chain(model):
    from langchain_core.prompts import ChatPromptTemplate

    wrapped = llm_mod.StructuredFallbackModel(model)
    return ChatPromptTemplate.from_messages([("system", "s"), ("human", "{payload}")]) | wrapped.with_structured_output(_Out)


def test_structured_fallback_parses_json_text_when_native_fails():
    model = _FakeLocalModel('```json\n{"winning_strategy": "ok"}\n```')
    result = _chain(model).invoke({"payload": "{}"})
    assert result == _Out(winning_strategy="ok", items=[])
    assert model.invocations == 1


def test_structured_fallback_does_not_retry_timeouts():
    model = _FakeLocalModel('{"winning_strategy": "ok"}', native_error=TimeoutError("slow"))
    with pytest.raises(TimeoutError):
        _chain(model).invoke({"payload": "{}"})
    assert model.invocations == 0


def test_structured_fallback_raises_when_text_is_not_json():
    model = _FakeLocalModel("I cannot do that")
    with pytest.raises(ValueError):
        _chain(model).invoke({"payload": "{}"})


# --- redaction --------------------------------------------------------------------------------


def test_redact_text_covers_urls_and_nric():
    redacted = redact_text("See https://example.com/x?id=1, NRIC S1234567D")
    assert "example.com" not in redacted and "S1234567D" not in redacted
    assert "[URL]" in redacted and "[ID]" in redacted


def test_alias_is_stable_within_process_and_hides_value():
    first = alias("PROPERTY", "Marina Bay Tower")
    assert first == alias("PROPERTY", "Marina Bay Tower")
    assert first != alias("PROPERTY", "Other Tower")
    assert "Marina" not in first
    assert alias("PROPERTY", None) is None
