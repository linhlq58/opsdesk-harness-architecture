# 0002 — LangGraph as the orchestration backbone, create_agent for specialists

- **Status:** Accepted
- **Date:** 2026-11-21
- **Milestone:** M03

## Context

The main helpdesk flow needs explicit state, branching, parallel fan-out, subgraphs, retries,
interrupts for human approval and resumable checkpoints. Individual specialists (tickets, KB,
hardware, security) only need a standard model ↔ tool loop. See architecture.md §7 (W4 L3).

## Decision

We will build the main helpdesk graph and the access-request workflow with LangGraph, and build
specialists with LangChain `create_agent` plus middleware. Fixed rules stay in plain Python
(`domain/policies`).

## Alternatives considered

| Option | Why not (for now) |
|---|---|
| `create_agent` for everything | No explicit state machine, fan-out or HITL resume for the main flow |
| Hand-written asyncio state machine | Re-implements checkpointing, interrupts and streaming |
| Other agent frameworks | Outside the course scope |

## Rationale

> 🎯 Write this section in your own words. Questions to get you started:
> - Which parts of the flow genuinely need a graph, and which are just a loop?
> - What do you gain by keeping policy decisions out of the model entirely?

## Consequences

> 🎯 Write this section in your own words.

- **Positive:**
- **Negative:**
- **Follow-ups:**
