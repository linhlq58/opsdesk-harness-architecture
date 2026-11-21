# 0003 — One event schema shared by SSE, local logs and evaluation

- **Status:** Accepted
- **Date:** 2026-11-21
- **Milestone:** M02

## Context

The UI timeline, local debugging logs and the evaluation suite all need to know what happened in a
run (routes, tool calls, guard verdicts, approvals, usage). Traces (LangSmith/Langfuse) and audit
records have different purposes and guarantees. See architecture.md §6.3.

## Decision

We will define one versioned event schema (`opsdesk.event.v1`) published on an in-process bus to
several sinks: SSE (allowlisted), local JSONL (always on) and evaluation (builds `AgentResult`).
Traces go through separate callbacks; audit is written through its own API. All three share
`request_id`.

## Alternatives considered

| Option | Why not (for now) |
|---|---|
| Each consumer parses LangGraph events directly | Couples UI and evals to framework internals that change between versions |
| Use traces as the event source | Optional, external, and not designed for UI streaming or deterministic evals |
| Put audit on the event bus | Audit needs tamper evidence and must not depend on sink filtering |

## Rationale

> 🎯 Write this section in your own words. Questions to get you started:
> - Why must *event*, *trace* and *audit* stay three separate concepts?
> - Why is `seq` used for ordering instead of the timestamp?

## Consequences

> 🎯 Write this section in your own words.

- **Positive:**
- **Negative:**
- **Follow-ups:**
