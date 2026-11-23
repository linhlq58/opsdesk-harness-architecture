# OpsDesk — Milestone roadmap

Each milestone takes 1–2 sessions (1–2 hours each). When a milestone is finished, the code must **run, pass all tests, and be committed**.

Legend:
- 🎯 **You decide & verify**: harness/agent work. You answer the design decisions, Claude Code implements them, then you predict, run, break and review (see `CLAUDE.md`)
- 📖 **Read**: Claude Code writes it and explains it; you read it and answer the milestone's self-check questions
- ⚙️ **Supporting**: Claude Code does it (scaffolding, config, UI, fixtures, data)

> **Focus rule:** your time goes to understanding harness architecture and how to use it, not to Python syntax. Claude Code writes all code. For 🎯 pieces you own the **decisions and the verification**; plain Python (value objects, models, domain rules, repositories, SQL, parsing, utilities) is 📖. See `CLAUDE.md` and `docs/learning/python-cheatsheet.md`.

Estimate: 25 milestones (three are split into a/b parts), roughly 30–40 sessions. Phase 0 is almost entirely 📖/⚙️; harness decisions and verification start at M03.

## Rules for every milestone from M03 on

1. **Version check first.** Before writing code, check the installed and latest versions and the changelog of every package the milestone touches (LangChain, LangGraph, langchain-mcp-adapters, Langfuse, RAGAS, deepeval, a2a-sdk, deepagents change quickly). Record any API difference from the course material in the milestone's Notes.
2. **Eval cases are part of done (from M07 on).** Every milestone adds at least one deterministic eval case (expected route, tools, status or reason code) to `evals/datasets/`, and the deterministic eval gate stays green.
3. **Temporary adapters are allowed, temporary contracts are not.** A stub tool may stand in for a capability that arrives later, but it goes through the same tool registry, `ToolResult` and events as the real one, so swapping it changes no agent code.
4. **Wiring and demo.** Each milestone file follows `docs/milestones/_template.md`: a **Wiring** table shows which existing pieces the milestone uses at each step, and a **Demo scenario** (`uv run poe demo mNN`) shows them working together. Self-check questions trace a concrete request through the system.

---

## Phase 0 — Foundations

| # | Milestone | 🎯 You decide & verify | 📖 Read | ⚙️ Claude Code | Course topics |
|---|---|---|---|---|---|
| M00 ✅ | Repository skeleton | — | `.importlinter` contracts | uv, ruff, pyright, pytest, pre-commit, CI (Linux + Windows), poe tasks, VS Code settings, Settings | Layered architecture |
| M01 ✅ | Domain & seed data | — | `Money`, domain models, policies, ports, unit tests | Seed YAML, in-memory + SQLite repositories, contract tests | W1 L2, W4 L3 |
| M02 | Core contracts | — | `Principal`, `RequestContext`, `ToolResult` + error taxonomy, `Event` v1, recorder, event bus, sinks, redaction | Contract snapshot tests | W1 L2, L4 |

## Phase 1 — Basic harness (Week 1)

| # | Milestone | 🎯 You decide & verify | 📖 Read | ⚙️ Claude Code | Course topics |
|---|---|---|---|---|---|
| M03 | First agent across all 5 layers | Tool wrapper (scope → policy → `ToolResult` → events), ticket tools, `RequestContext` through runtime context, role-based model factory, first `create_agent` answering with the **real model** | Fake model with scripted tool calls for tests | CLI runner, smoke-test command | W1 L2, L3 |
| M04 | API + SSE + UI v1 | `stream_adapter`: `astream_events(v3)` → Event v1 → SSE (allowlist, redaction, cancellation); multi-turn sessions with `InMemorySaver` (one `thread_id` per tab, Reset = new thread) | Demo-login token helper | FastAPI app, persona picker, chat + timeline UI | W1 L3, W2 L3 |
| M05 | Router pattern | Route schema + fallback, parallel execution, synthesis; specialists (ticket, knowledge, hardware, security) | **Temporary in-process tools** behind the tool registry: small static FAQ (replaced by RAG in M10), fake device list (replaced by MCP in M08) | Live flow diagram in the UI | W1 L3 |
| M06 | Subagent · Handoff · Skill | The three patterns in the helpdesk domain; handoff to a Security Agent whose ownership (`active_agent`) persists across turns via the checkpointer | — | UI tabs, starter prompts | W1 L3 |
| M07 | Tracing, cost v1 & eval skeleton | Usage capture from model callbacks → cost per turn; failure injection → trace → regression case; **`AgentResult` built from the event log** and a deterministic eval gate (route, tools, status, reason codes) | Pricing table + cost arithmetic, dataset format | LangSmith adapter, metadata/tags, first golden cases for M03–M06 | W1 L4, L5, W3 L2 |

## Phase 2 — Capabilities & data (Week 2)

| # | Milestone | 🎯 You decide & verify | 📖 Read | ⚙️ Claude Code | Course topics |
|---|---|---|---|---|---|
| M08 | MCP: asset management system | MCP tools/resources, tool registry (namespacing + collision check) via `langchain-mcp-adapters`, infrastructure failure → `unavailable`; **swap the M05 fake device tool for MCP** without touching the agents | Server-side PII filter helpers | FastMCP server scaffold, asset data | W2 L1 |
| M09 | RAG Pipeline A — ingestion | ACL validation (quarantine), atomic publish + manifest, index contract; **multimodal sources**: one document with a table and one image (network diagram), each chunk keeping `modality` and `locator` | Locator-preserving chunker, document parsing | `opsdesk-ingest` CLI, sample KB documents | W2 L2 |
| M10 | RAG Pipeline B — serving baseline | Fail-closed loader, ACL pre-filter, retrieval → citations / no-evidence answer; **swap the M05 static FAQ for retrieval** | BM25 wrapper | Retrieval eval set + recall@k | W2 L2 |
| M11 | Advanced RAG | Adaptive plan (strategy / top-k / retry budget), hybrid retrieval, comparison on the eval set | RRF fusion function | Qdrant local mode + embeddings | W2 L2 |
| M12a | Main helpdesk graph — structure | State contract + reducers, conditional edges, specialists as nodes, RAG as a subgraph | — | Subgraph namespaces in the UI | W2 L3 |
| M12b | Main helpdesk graph — dynamic control | `Send` fan-out + deterministic gather, `Command` retry with a limit | — | Parallel branches in the flow diagram | W2 L3, W4 L1 |

## Phase 3 — Governance (Week 3)

| # | Milestone | 🎯 You decide & verify | 📖 Read | ⚙️ Claude Code | Course topics |
|---|---|---|---|---|---|
| M13 | Guards | Trust channels, input guard placement (before any model call), neutralizer at data boundaries, output guard → gate | Pattern/heuristic detectors | Red-team fixtures | W3 L1 |
| M14a | Access workflow — gates & durable interrupt | Access-request workflow as a graph, approval gates driven by `policy.yaml`, `interrupt` / `Command(resume=...)`, durable checkpointer (`InMemorySaver` → `AsyncSqliteSaver`) | `policy.yaml` loader | Checkpointer wiring | W3 L1, W2 L3 |
| M14b | Access workflow — approval API & idempotency | Approval endpoint that authorizes the reviewer (`access:approve`), idempotent side effects on resume; compare with the built-in `HumanInTheLoopMiddleware` and record when each fits | — | Approval queue in the UI | W3 L1 |
| M15 | Audit & resilience | Wiring timeout / retry / circuit breaker around LLM and MCP calls (middleware) | Hash-chained audit + verification, retry and breaker primitives | — | W3 L1 |
| M16 | Cost governance | Budget reserve/settle before every model call, chat vs eval budgets, alerts that combine cost + retries + quality | Ledger storage with de-duplication | Langfuse adapter, cost panel in the UI | W3 L3 |
| M17 | Evaluation expansion | Judge-based metrics (choice of DeepEval metrics, when they do not apply), red-team suite, separate grouping of blocked runs | — | DeepEval runner, golden/red-team datasets, report | W3 L2 |

## Phase 4 — Multi-agent systems (Week 4)

| # | Milestone | 🎯 You decide & verify | 📖 Read | ⚙️ Claude Code | Course topics |
|---|---|---|---|---|---|
| M18a | Orchestrator-worker | Dynamic decomposition of multi-intent requests, worker result envelope (`ok` / `empty` / `error` / `unavailable`), labelled partial results | — | Partial-result rendering in the UI | W4 L1 |
| M18b | Evaluator-optimizer & verifier | Refinement loop with a hard attempt budget, independent verifier (citations must point to retrieved evidence) | — | — | W4 L1 |
| M19 | A2A: Procurement Agent | Fail-closed auth, task lifecycle, `input-required` ↔ harness HITL, A2A client tool | Task store | Agent Card, server scaffold | W4 L4 |
| M20 | Weekly report Deep Agent | `create_deep_agent` setup, read-only tools over ledger/audit/tickets/evals, budget, artifact checked against evidence, fallback for infrastructure failures only | — | Workspace backend, artifact viewer in the UI | W4 L2 |
| M21 | Framework selection, optimization & ROI | Cheaper-router experiment with a quality gate; **ROI estimate** from real ledger data: monthly workload mix, baseline (IT staff answering manually), time-bounded ROI | ADR per workload | Final demo script | W4 L3, W3 L3, W1 L5 |

---

## Changes from the previous version (2026-11-22)

| Change | Why |
|---|---|
| M05 uses temporary in-process tools, swapped in M08 (MCP) and M10 (RAG) | Router specialists need knowledge and device tools before MCP/RAG exist |
| `InMemorySaver` from M04; M14a upgrades to `AsyncSqliteSaver` | Pattern tabs and handoff need multi-turn state long before HITL |
| Eval skeleton moved to M07; every milestone adds eval cases; M17 becomes "expansion" | Regressions must be caught from the first agent changes, not after 13 milestones |
| M12, M14, M18 split into a/b | Each held too many new concepts for one 1–2 hour session |
| Multimodal sources in M09 | Covered in W2 L2, previously missing |
| ROI estimate in M21 | Covered in W1 L5, previously missing |
| Version check as the first step of every milestone | Agent libraries change APIs faster than the course material |
| 🎯 redefined: you decide & verify, Claude Code implements; each milestone has Design decisions, Predict, Break-it, Review checklist, Explain-back; Python cheat sheet | Reading and writing Python line by line cost most of the time while the goal is harness architecture; decisions and experiments teach the architecture directly |
| Wiring table + runnable demo in every milestone (from M03) | Pieces built in M00–M02 were hard to connect because nothing used them yet; every milestone now shows how its pieces fit together |
