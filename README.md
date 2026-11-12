# RAGS2Riches

RAGS2Riches is a LangChain + LangGraph implementation of the deal inference workflow from
`deal_intelligence_engine_build_guide.md`. Everything runs locally by default.

## Workflow

`validate_input` → `sql_baseline` → `analogue_retrieval` → `llm_synthesis` → `assemble_scorecard`

The UI at `http://127.0.0.1:8000` streams each node's start, end and errors live while the
deal is processed.

## Setup

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn app.api:app --reload
```

Set `SOURCE_XLSX` to the workbook you want to ingest. The default points at the UAT file
`mock leasing data.xlsx`.

## LLM providers

Choose a provider in the UI or set `LLM_PROVIDER` and `LLM_MODEL`.

| Provider | Runs | Configuration |
|---|---|---|
| `template` | Offline (default) | None |
| `ollama` | Local | `OLLAMA_BASE_URL` (default `http://localhost:11434`) |
| `openai_compatible` | Local (llama.cpp, LM Studio) | `OPENAI_COMPATIBLE_BASE_URL` (default `http://localhost:8080/v1`) |
| `anthropic` | Cloud (paid) | `ANTHROPIC_API_KEY` environment variable |
| `openai` | Cloud (paid) | `OPENAI_API_KEY` environment variable |

If the selected provider fails, the engine falls back to the template narrative and
records a warning on the scorecard.

## Data notes

- The source ledger has one row per broker per deal. Fees and sizes repeat on each row,
  so ingestion takes the per-deal maximum, not the sum.
- The UAT file has no WON/LOST field. Win probability, pursue recommendation and sales
  cycle are therefore reported as unavailable, and each gap is listed on the scorecard.
  Add an `Outcome` column (`WON` / `LOST`) to unlock these.

## Tests

```powershell
.venv\Scripts\python.exe -m pytest -q
```
