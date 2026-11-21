# opsdesk-harness-architecture

OpsDesk is an internal IT Helpdesk assistant, built as a production-grade agent harness
(incorporating LangChain, LangGraph, MCP, RAG, governance, evaluation, cost management,
Deep Agents, and A2A capabilities).

It is a **learning project**: a 4-week agent-engineering course applied inside one coherent
architecture, delivered in 22 milestones.

- Architecture: [docs/architecture.md](docs/architecture.md)
- Roadmap: [docs/roadmap.md](docs/roadmap.md)
- Current milestone: [docs/milestones/](docs/milestones/)
- Decisions: [docs/adr/](docs/adr/)

## Setup (Windows)

Prerequisites: [Git for Windows](https://git-scm.com/download/win) and
[uv](https://docs.astral.sh/uv/).

```powershell
git config --global core.autocrlf false    # .gitattributes controls line endings (LF)
git config --global core.longpaths true

powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

uv sync                          # creates .venv with Python 3.13 and all dev tools
uv run pre-commit install        # optional: run ruff + import-linter on every commit
```

In VS Code, install the recommended extensions and select `.venv\Scripts\python.exe` as the
interpreter. Linux and macOS use the same `uv` commands.

## Everyday commands

```powershell
uv run poe check      # fmt-check + lint + typecheck + arch + test (must pass before every commit)
uv run poe test       # pytest
uv run poe arch       # import-linter architecture contracts
uv run poe fmt        # format code
uv run poe            # list all tasks
```

CI runs `uv sync --locked` and `uv run poe check` on both `ubuntu-latest` and `windows-latest`.
