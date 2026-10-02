# Verification record — 2026-10-02

## Executed results

Environment: Windows, Python 3.12. No paid model call or third-party API call was
made by automated tests. The full existing AI dependency stack was unavailable.
Normal network package installation/clone attempts were blocked by the environment;
tests used compatible cached official Python package wheels with `--no-index`.
An unsandboxed install request was automatically rejected by the approval policy.

| Executed command from repository root | Result |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q -rs` | **26 passed, 1 skipped, 1 warning in 1.51s** |
| `node tests/workflow_codes.cjs` | Initially failed with EPERM during Node's Windows path realpath lookup |
| `node --preserve-symlinks-main tests/workflow_codes.cjs` | **23 assertions passed**; tests exported Code nodes without n8n |
| `.venv\Scripts\python.exe -m compileall -q api services agent web utils tests` | Exit 0 |
| `git diff --check` | Exit 0; Git emitted ordinary LF/CRLF conversion warnings |
| `.venv\Scripts\python.exe -m uvicorn api.app:app --host 127.0.0.1 --port 8765 --workers 1` | Real HTTP server started, application startup completed in degraded mode |
| Local HTTP GET `/api/health` using urllib | HTTP **503**, degraded; graph/MCP false and provider null |
| Local HTTP POST `/api/chat` using urllib | HTTP **503**, MODEL_CONFIGURATION_ERROR, retryable false; no raw provider detail |

The server was stopped after the HTTP smoke test. No provider credential was
configured. A healthy 200 response, structured success, graph reuse and cleanup
were verified using injected runtime dependencies in the API tests, not a live LLM.

The skipped item is the `tests/test_graph_integration.py` module: `langchain`
could not be imported. It contains real LangGraph routing and real StructuredTool
smoke tests with a local fake model; those tests have **not** run in this environment.
LangGraph, MCP adapters, Chroma and Streamlit are likewise unavailable here.
The warning is a Starlette TestClient deprecation for httpx in the cached recent
FastAPI/Starlette versions; assertions passed. Existing AI dependency floors were
not upgraded to suppress it.

## Coverage and honest boundaries

The passing tests cover actual HTTP schemas, validation, health, structured errors,
service invocation, explicit graph/context user/session, redacted input/output and
memory, user isolation, provider selection, graph-error retry suppression,
durable key conflicts/replays/incomplete reservations, concurrent same-key calls,
trusted tool identity, blocked ordering/filesystem tools, injected lifespan
build/cleanup, MCP startup error normalization and credential log redaction.
The graph boundary is fake in these passing tests. The production service does
call the existing graph builder; full compatibility is not yet demonstrated.

The exported workflow has 17 nodes, three HTTP attempts, two bounded waits,
stable original payload references, no graph cycle, no credential fields and no
AI Agent nodes. JSON topology checks and actual exported JavaScript ran locally.
Official n8n documentation and source were consulted for node parameters. No n8n
MCP/instance was connected, so import and end-to-end workflow execution remain
unverified. No deployment, QLoRA training, real model generation, real MCP tool
invocation, full Streamlit smoke test, or fully offline multimodal/RAG run is claimed.

## Final review

Current configuration contains no literal nutrition key. The known exposed value
was removed before architectural edits. `.env.example` holds blank credentials;
`.env` and generated data are ignored. Source and changed-file review found no
additional literal real API credential in the inspected snapshot. Git history
still needs manual credential rotation and any appropriate separate cleanup.

The local checkout was reconstructed from GitHub connector reads because network
clone was unavailable. Its sanitized snapshot Git history is independent of the
remote history; it must not be force-pushed. Publication uses the dedicated remote
branch based on the original fork commit, with ordinary GitHub commits. No upstream
or main branch write and no automatic merge is authorized/performed.

Before accepting Phase 1 as runtime-verified: install the full requirements, run
the optional graph tests, configure an existing provider or local Ollama, verify
persistent MCP tool calls for two explicit users, launch Streamlit, and import/run
the workflow on the actual n8n instance. These are required remaining verification
steps, not implemented Phase 2 features.
