# 0001 — Layered/hexagonal architecture enforced by import-linter

- **Status:** Accepted
- **Date:** 2026-11-21
- **Milestone:** M00

## Context

OpsDesk combines many frameworks (LangChain, LangGraph, FastAPI, MCP, A2A, Langfuse, ...) and will
grow over 22 milestones. Business rules (ownership, approval thresholds, eligibility) must stay
testable without any of those frameworks, and dependencies between parts of the code must not erode
as features are added. See architecture.md §2 and §4.

## Decision

We will organise `src/opsdesk` into layers (core → domain → infrastructure → tools/retrieval →
agents → orchestration/workloads → api/evaluation) where upper layers may import lower ones, never
the reverse. Domain and policy code is plain Python; frameworks are adapters at the edges (ports &
adapters). The rules are enforced by import-linter contracts in `.importlinter`, run by
`uv run poe arch`, pre-commit and CI. Changing a rule requires a new ADR.

## Alternatives considered

| Option | Why not (for now) |
|---|---|
| Flat package, rules written in docs only | Nothing stops a violation; it is found (if ever) in code review |
| One package per framework | Organises by technology instead of responsibility; business rules leak everywhere |
| Separate installable package per layer | Enforces boundaries, but heavy tooling overhead for a learning project |

## Rationale

> 🎯 Write this section in your own words. Questions to get you started:
> - What goes wrong, concretely, if `domain` imports `langchain`?
> - Why is a tool-enforced rule better than a rule written in architecture.md?
> - Why does the infrastructure layer use `:` while the other layers use `|`?

## Consequences

> 🎯 Write this section in your own words.

- **Positive:**
- **Negative:**
- **Follow-ups:**
