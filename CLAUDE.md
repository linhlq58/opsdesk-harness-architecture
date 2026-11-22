# CLAUDE.md — OpsDesk

OpsDesk is an internal IT Helpdesk assistant built as a production-grade agent harness. Its purpose is **learning**: it applies a 4-week course (LangChain, LangGraph, MCP, RAG, governance, evaluation, cost, Deep Agents, A2A) inside one coherent architecture.

**Before doing anything, read:**
1. `docs/architecture.md`: architecture, layers, core contracts
2. The current milestone file in `docs/milestones/`
3. Any relevant ADR in `docs/adr/`

## The most important rule: 🎯 vs ⚙️

This is a learning project focused on **building an agent harness**. The user's learning time goes to harness and agent topics only; plain Python work is delegated to Claude Code. Every milestone marks each task as one of the following.

- **🎯 Core (harness/agent)**: the user writes this **themselves**. Do **not** write the implementation, even when asked to "just do it quickly". You may instead explain concepts, point to official documentation, suggest an approach, write tests for the user to make pass, and review code and point out problems. If the user explicitly says "I want to skip the learning part, write it for me", remind them once that this is a 🎯 task, then do as asked.
- **📖 Read**: Claude Code writes it, then **explains it** so the user can read and understand it: what each part does, why it is shaped that way, and how later harness code will use it. Keep explanations short and point to the exact lines.
- **⚙️ Supporting**: Claude Code does this: boilerplate, configuration, scaffolding, UI, scripts, fixtures, additional tests, documentation.

### What counts as 🎯

🎯 is reserved for work where the lesson is about agents or the harness itself: tool wrappers and the tool envelope, model calls and model factories, streaming/events, LangGraph state and orchestration patterns, RAG pipelines and retrieval strategies, MCP and A2A, guards and trust boundaries, HITL/interrupts, cost and budget enforcement, evaluation of agent runs, Deep Agents.

General Python work is **never** 🎯, even if a milestone file says so: value objects, Pydantic/dataclass models, domain rules written as plain functions, repositories and SQL, parsing, utilities, and their unit tests. Treat such tasks as 📖: implement them, then explain them. ADR prose and `.importlinter` tuning are optional for the user.

If a task is not marked, apply the rule above; ask only if it is genuinely unclear.

## Commands

```bash
uv sync                 # install / update the environment
uv run poe check        # fmt-check + lint + typecheck + arch + test (must pass before every commit)
uv run poe test         # pytest
uv run poe arch         # lint-imports
uv run poe fmt          # format code
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

## Cross-platform rules (Windows dev machine + Linux and Windows CI)

The project is developed on native Windows (VS Code + Claude Code) and CI runs on both `ubuntu-latest` and `windows-latest`. Code must behave identically on both.

- Paths: always `pathlib.Path`. Never build paths with string concatenation or hardcoded `/` or `\\`.
- Text files: always pass `encoding="utf-8"` to `open()`, `read_text()` and `write_text()` (the Windows default is not UTF-8).
- Line endings: LF everywhere (enforced by `.gitattributes`).
- Automation: tasks live in `pyproject.toml` (`[tool.poe.tasks]`) and helper scripts are Python. No bash/PowerShell scripts, no Makefile.
- No symlinks (they need special privileges on Windows). Use pointer files written with `os.replace` for atomic switches.
- Processes: start servers/subprocesses with `sys.executable` and argument lists, never shell strings.
- Ports and hosts come from settings; bind to `127.0.0.1` by default.

## Testing

- Every behaviour change needs a test. Tests never call a real model; use the fake models in `opsdesk.llm`.
- Tests live in `tests/unit`, `tests/contract` and `tests/integration`.
- Judge-based (paid) evaluations are not part of `poe check`.

## Commits

Format: `type(mNN): description` (e.g. `feat(m03): add ticket tool wrapper`). Every commit must pass `uv run poe check`.
