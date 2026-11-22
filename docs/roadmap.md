# OpsDesk — Milestone roadmap

Each milestone takes 1–2 sessions (1–2 hours each). When a milestone is finished, the code must **run, pass all tests, and be committed**.

Legend: 🎯 core harness/agent work you write yourself (Claude Code may only explain, hint or review) · 📖 Claude Code writes it and explains it, you read and understand it · ⚙️ supporting work delegated to Claude Code.

> **Focus rule:** your own coding time goes to the harness and agents. Plain Python (value objects, models, domain rules, repositories, utilities) is 📖 everywhere, even where a row below still lists it under 🎯. See `CLAUDE.md` → "What counts as 🎯".

Estimate: 22 milestones, roughly 30–40 sessions.

---

## Phase 0 — Foundations

| # | Milestone | 🎯 You write | ⚙️ Claude Code | Course topics |
|---|---|---|---|---|
| M00 | Repository skeleton | Read and adapt `.importlinter` (layer rules) | uv, ruff, pyright, pytest, pre-commit, GitHub Actions CI (Linux + Windows), poe tasks, VS Code settings, Settings | Layered architecture |
| M01 | Domain & seed data | — (📖 read: `Money`, domain models, policies, ports) | Everything: models, policies, ports, YAML seed data, SQLite repositories, tests | W1 L2 (verification), W4 L3 (plain Python) |
| M02 | Core contracts | `Principal`, `RequestContext`, `ToolResult` + error taxonomy, `Event` v1 + bus + JSONL sink | Contract tests for the schemas | W1 L2, L4 |

## Phase 1 — Basic harness (Week 1)

| # | Milestone | 🎯 | ⚙️ | Course topics |
|---|---|---|---|---|
| M03 | First agent across all 5 layers | Tool wrapper (authz → call → envelope → event), ticket tools, role-based model factory + fake model | CLI runner | W1 L2, L3 |
| M04 | API + SSE + UI v1 | `stream_adapter`: `astream_events(v3)` → Event v1 → SSE (allowlist, redaction, cancellation) | FastAPI app, demo login (pick a persona → token), chat + timeline UI | W1 L3, W2 L3 |
| M05 | Router pattern | Route schema + fallback, parallel execution, synthesis | Live flow diagram in the UI | W1 L3 |
| M06 | Subagent · Handoff · Skill | The three patterns in the helpdesk domain (handoff to a Security Agent) | UI tabs, starter prompts | W1 L3 |
| M07 | Tracing & cost v1 | Usage capture → cost from pricing; failure injection → regression case | LangSmith adapter, metadata/tags | W1 L4, L5 |

## Phase 2 — Capabilities & data (Week 2)

| # | Milestone | 🎯 | ⚙️ | Course topics |
|---|---|---|---|---|
| M08 | MCP: asset management system | Server-side PII filtering, tool registry (namespacing + collision check), infrastructure failure → `unavailable` | FastMCP server scaffold, asset data | W2 L1 |
| M09 | RAG Pipeline A — ingestion | Locator-preserving chunker, ACL validation (quarantine), atomic publish + manifest | `opsdesk-ingest` CLI, sample KB documents | W2 L2 |
| M10 | RAG Pipeline B — serving baseline | Fail-closed loader, ACL pre-filter, BM25, citations, no-evidence response | Retrieval eval set + recall@k | W2 L2 |
| M11 | Advanced RAG | Hybrid RRF, adaptive plan (strategy / top-k / retry budget), comparison on the eval set | Qdrant local mode + embeddings | W2 L2 |
| M12 | Main helpdesk graph | State contract + reducers, conditional edges, RAG subgraph, Send fan-out + gather, Command retry | Subgraph namespaces in the UI | W2 L3 |

## Phase 3 — Governance (Week 3)

| # | Milestone | 🎯 | ⚙️ | Course topics |
|---|---|---|---|---|
| M13 | Guards | Trust channels, input guard, neutralizer at data boundaries, output guard | Red-team fixtures | W3 L1 |
| M14 | Access-request workflow + HITL | Policy config, approval gates, interrupt/resume, authorized approval endpoint, idempotency | AsyncSqliteSaver, approval queue in the UI | W3 L1, W2 L3 |
| M15 | Audit & resilience | Hash-chained audit + verification; async timeout / retry / circuit breaker | Wiring into the LLM and MCP clients | W3 L1 |
| M16 | Cost governance | Durable ledger (no double counting), budget reserve/settle before model calls, chat vs eval budgets | Langfuse adapter, cost panel in the UI, alerts | W3 L3 |
| M17 | Evaluation suite | `AgentResult` built from the event log, deterministic gate, separate grouping of blocked runs | DeepEval runner, golden/red-team datasets, report | W3 L2 |

## Phase 4 — Multi-agent systems (Week 4)

| # | Milestone | 🎯 | ⚙️ | Course topics |
|---|---|---|---|---|
| M18 | Advanced orchestration | Orchestrator-worker for multi-intent requests, evaluator-optimizer with an attempt budget, independent verifier (citations must point to retrieved evidence), labelled partial results | — | W4 L1 |
| M19 | A2A: Procurement Agent | Fail-closed auth, task store, `input-required` ↔ harness HITL, A2A client tool | Agent Card, server scaffold | W4 L4 |
| M20 | Weekly report Deep Agent | Read-only tools over ledger/audit/tickets/evals, budget, numbers checked against evidence, fallback for infrastructure failures only | Workspace backend, artifact viewer in the UI | W4 L2 |
| M21 | Framework selection & optimization | ADR per workload; cheaper-router experiment with a quality gate | Final demo script | W4 L3, W3 L3, W1 L5 |
