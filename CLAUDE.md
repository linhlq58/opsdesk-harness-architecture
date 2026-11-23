# CLAUDE.md — OpsDesk

OpsDesk is an internal IT Helpdesk assistant built as a production-grade agent harness. Its purpose is **learning**: it applies a 4-week course (LangChain, LangGraph, MCP, RAG, governance, evaluation, cost, Deep Agents, A2A) inside one coherent architecture.

**Before doing anything, read:**
1. `docs/architecture.md`: architecture, layers, core contracts
2. The current milestone file in `docs/milestones/`
3. Any relevant ADR in `docs/adr/`

## The most important rule: the user is the architect, Claude Code is the implementer

This is a learning project. The user's goal is to understand **harness architecture and how to use it** (design, operation, debugging, evaluation), not Python syntax. The user is new to Python. Claude Code writes **all** the code; the user's learning happens through decisions, predictions, experiments and reviews. Every milestone marks each task as one of the following.

- **🎯 Harness/agent core: the user decides and verifies, Claude Code implements.**
  1. **Before coding**, the user answers the milestone's *Design decisions* (D1, D2, ...). Do not implement a 🎯 piece until its decisions are recorded in the milestone's Notes. If a decision is missing, ask for it, presenting the options and their consequences in plain words; do not choose silently.
  2. Implement exactly the recorded decisions. If you think a decision is wrong, say so and explain why before implementing; the user decides.
  3. After implementing, **walk the user through the piece at block level**, following a demo scenario: what each block does and which design decision it implements, with `file:line` references. Do not explain Python syntax unless asked; when you do, refer to the pattern number in `docs/learning/python-cheatsheet.md` if it exists.
  4. Support the user's verification: help them run the *Predict* step, set up the *Break-it* exercises (and revert them), and answer the *Review checklist* by pointing to the exact block for each item. Let the user draw the conclusions.
- **📖 Read**: plain Python foundations (value objects, models, domain rules, repositories, utilities). Claude Code implements and gives a short explanation along the request flow. No decisions required from the user.
- **⚙️ Supporting**: boilerplate, configuration, scaffolding, UI, scripts, fixtures, additional tests, documentation. Claude Code does it.

### What counts as 🎯

🎯 is reserved for work where the lesson is about agents or the harness itself: tool wrappers and the tool envelope, model calls and model factories, streaming/events, LangGraph state and orchestration patterns, RAG pipelines and retrieval strategies, MCP and A2A, guards and trust boundaries, HITL/interrupts, cost and budget enforcement, evaluation of agent runs, Deep Agents.

General Python work is never 🎯: value objects, Pydantic/dataclass models, domain rules written as plain functions, repositories and SQL, parsing, utilities, and their unit tests are 📖. ADR prose and `.importlinter` tuning are optional for the user.

If a task is not marked, apply the rule above; ask only if it is genuinely unclear.

## Milestone workflow (from M03 on)

1. **Version check first**: before coding, compare installed vs latest versions and read the changelog of every package the milestone touches; note API differences from the course material in the milestone's Notes.
2. **Eval cases are part of done (from M07 on)**: add at least one deterministic case to `evals/datasets/` per milestone and keep the eval gate green.
3. **Temporary adapters, permanent contracts**: a stub tool may stand in for a later capability (e.g. static FAQ before RAG), but it goes through the tool registry, `ToolResult` and events like the real one.
4. **Wiring and demo**: every milestone file follows `docs/milestones/_template.md`, including a **Wiring** table (which existing pieces the milestone uses, step by step) and a **Demo scenario** under `demos/`, runnable with `uv run poe demo mNN` (fake model, deterministic, part of CI) and `--live` (real model, manual). The milestone is not done until its demo runs.
5. **Explain along the request flow**: when explaining code or reviewing, follow a demo scenario step by step with `file:line` references, at block level, rather than describing files one by one or lines one by one.
6. **Learning loop for 🎯 pieces**: Design decisions → implement → Predict → run the demo → Break-it → Review checklist → Explain-back (see `docs/milestones/_template.md`).

See `docs/roadmap.md` for the full plan.

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
- Tunables (approval thresholds, budgets, retry/timeout settings) are read from `config/policy.yaml` (introduced in M14a). Never hardcode them. The role → scope mapping is **not** a tunable: it is part of the security model and lives in code (`security/scopes.py`), changed only through review and tests.
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
