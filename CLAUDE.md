# CLAUDE.md — OpsDesk

OpsDesk is an internal IT Helpdesk assistant built as a production-grade agent harness. Its purpose is **learning**: it applies a 4-week course (LangChain, LangGraph, MCP, RAG, governance, evaluation, cost, Deep Agents, A2A) inside one coherent architecture.

**Before doing anything, read:**
1. `docs/architecture.md`: architecture, layers, core contracts
2. The current milestone file in `docs/milestones/`
3. Any relevant ADR in `docs/adr/`

## The most important rule: 🎯 vs ⚙️

This is a learning project. Every milestone marks each task as one of the following.

- **🎯 Core**: the user writes this **themselves**. Do **not** write the implementation, even when asked to "just do it quickly". You may instead explain concepts, point to official documentation, suggest an approach, write tests for the user to make pass, and review code and point out problems. If the user explicitly says "I want to skip the learning part, write it for me", remind them once that this is a 🎯 task, then do as asked.
- **⚙️ Supporting**: you do this: boilerplate, configuration, scaffolding, UI, scripts, fixtures, additional tests, documentation.

If a task is not marked, ask before writing code.

## Commands

```bash
make install     # uv sync
make check       # fmt-check + lint + typecheck + arch + test (must pass before every commit)
make test        # pytest
make arch        # lint-imports
```

## Architecture rules (enforced by import-linter, do NOT relax)

- Upper layers may import lower layers, never the reverse (see `.importlinter` and architecture.md §4).
- `opsdesk.domain` is pure Python: no I/O, no frameworks.
- Serving code never imports `opsdesk.ingestion`. The two RAG pipelines share only `opsdesk.retrieval.contract`.
- `services/*` never import `opsdesk`.
- To change an architecture rule, propose a new ADR. Never silently edit `.importlinter`.

## Code conventions

- Python 3.13, full type hints, pyright strict for `src/`.
- Pydantic v2 for every model at a boundary; frozen dataclasses for internal value objects.
- Async for I/O (FastAPI, LangGraph, MCP, A2A).
- Money: `Decimal`, currency VND. Never use floats for money.
- Time: timezone-aware UTC `datetime`, obtained through `core.clock`. Never use `datetime.utcnow()`.
- Identity comes only from the server-built `RequestContext`/`Principal`. Never from user text, model output or retrieved data.
- Tools return a `ToolResult` whose status belongs to the shared error taxonomy. No ad-hoc dicts, and no raw exceptions leaking to the model.
- Thresholds, budgets, scopes and retry settings are read from `config/policy.yaml`. Never hardcode them.
- No `print`; use `logging`. Never log secrets, full prompts or PII.
- Do not add a dependency before a milestone needs it. When you add one, state why in the commit message.

## Testing

- Every behaviour change needs a test. Tests never call a real model; use the fake models in `opsdesk.llm`.
- Tests live in `tests/unit`, `tests/contract` and `tests/integration`.
- Judge-based (paid) evaluations are not part of `make check`.

## Commits

Format: `type(mNN): description` (e.g. `feat(m03): add ticket tool wrapper`). Every commit must pass `make check`.
