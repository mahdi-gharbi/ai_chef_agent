# Phase 1 source audit

Repository: `mahdi-gharbi/ai_chef_agent`, fork of `celestlee/ai_chef_agent`.
Inspected base: `c5c8d1f52f5b33d7a7a1cf179c118aee91be6cf6`. No upstream writes.
The recursive tree and all 41 tracked text files were reviewed before implementation,
including deployment files, prompts, provider wrappers, multimodal code and notebooks.

## Credentials and privacy

- A literal Spoonacular `nutrition_api_key` was present in
  `conf/agent_config.yaml`. It was removed; the server now reads only
  `SPOONACULAR_API_KEY`. **Rotate/revoke the exposed Spoonacular credential manually.**
  Removing the current value does not remove it from upstream/fork Git history.
- No other literal real API credential was identified in the inspected snapshot.
  This was a source review and pattern scan, not an exhaustive historical or binary scan.
- `.env.example` was absent although README referenced it. It now exists with blank
  credentials, and `.gitignore` explicitly permits that example but excludes private env files.
- `local_privacy/` files are already public in the source repository. Determine
  whether their health/recipe content is sample or real before storing personal data.
  No content from these files is copied into the audit or logs.
- Old tool logging included arguments, result previews and raw exception messages.
  The shared tool logging/middleware now records names, timing and error classes.
  The formatter masks current environment credential values and common token fields.
- Nutrition errors could include URLs with keys; the response now uses a fixed message.
  Legacy user text logs and third-party SDK logs still need broader privacy review.

## Actual behavior and changes

| Area | Source finding | Phase 1 decision |
|---|---|---|
| Routing | Streamlit preclassifies; graph skips classification if intent is provided | API supplies empty intent; graph classifies asynchronously using the selected provider |
| Agents | Four existing create_agent executors; middleware overrode specialization with generic prompt | Preserve executors and tool subsets; middleware selects specialization from execution context |
| MCP | get_tools adapters are stateless per invocation; loader uses Python/Node processes | Persistent explicit Python session in API lifespan; legacy filesystem loader retained, Windows executable lookup fixed |
| Warning state | Module-global mutable dictionary leaks across concurrent turns | ContextVar execution scope, with message-derived fallback for legacy CLI |
| Identity | Several tools default to YAML user; remove/clear/order had no explicit user argument | Add optional argument for legacy compatibility, and overwrite API tool identity in trusted wrappers |
| Session memory | JSON manager keyed only by session, unsanitized paths, non-atomic writes | Separate API SQLite memory scoped by user+session; legacy migration deferred |
| Blocking I/O | Sync routing/guardrails, SQLite and RAG | API model calls async, API persistence and optional RAG offloaded to threads; serial request execution |
| RAG | DashScope embeddings and Qwen rewrite/reflection regardless of main provider | Retain implementation; API opt-in off by default; accurately document shared/cloud dependency |
| Private files | Filesystem reads can be fed into a cloud model | Exclude filesystem MCP from multi-user API; retain legacy UI with corrected privacy claims |
| Ordering | Demo mutates fridge then posts to httpbin; repeat execution duplicates effects | Exclude API ordering; durable request-key ledger for other writes |
| Guardrails | Legacy Qwen judge fail-open; raw streamed output displayed before saved redaction | API chosen-model judge fail-closed; redact before cloud judge and before HTTP/persistence; buffer/redact UI output |
| Providers | Gemini/Qwen/Ollama wrappers exist; auxiliary calls strongly Qwen-coupled | Reuse wrappers, API override selector; no OpenAI adapter or mandatory key |
| Deployment | vercel.json points at nonexistent api/index.py | Document unsupported deployment; no infrastructure rewrite |

README overstated local/offline behavior and privacy. Local Chroma storage does not
mean cloud-free embeddings, and local file access does not prevent content from
being sent to a cloud LLM. The README now links the exact Phase 1 boundaries and
corrects those statements. Guardrails judge input, not an independent safety judge
over every output. Regex redaction is limited, not a universal privacy guarantee.

## Plan followed

1. Inspect source and call paths, scan secrets, remove embedded credential.
2. Add contracts, execution context, normalized errors and separate durable API memory.
3. Scope tool identities/warnings and preserve existing four-agent graph.
4. Initialize provider, persistent MCP and graph through lifespan; add health/chat.
5. Run injected API/service tests without model calls; add optional real-stack tests.
6. Build bounded n8n HTTP workflow from official node documentation/source.
7. Document setup, source limitations and results; review diff and rescan credentials.

Files and responsibilities are described in the integration guide and verification
record. Major remaining risks are unverified AI-stack compatibility in this
restricted environment, unauthenticated caller identity, shared optional RAG,
single-worker throughput, incomplete dependency pinning, and legacy UI/session debt.
