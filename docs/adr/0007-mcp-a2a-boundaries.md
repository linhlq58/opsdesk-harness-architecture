# 0007 — MCP only for the asset system, A2A only for Procurement, everything else in-process

- **Status:** Accepted
- **Date:** 2026-11-21
- **Milestone:** M08

## Context

Separate processes add latency, failure modes, auth and deployment work. They are only worth it
when a capability has its own owner, lifecycle or multiple consumers. See architecture.md §3
(W2 L1, W4 L3–L4).

## Decision

We will expose the asset management system as an MCP server (`asset-mcp`) and Procurement as an
independent A2A agent (`procurement-agent`). Specialist agents, the RAG subgraph and the report
Deep Agent run in-process inside `opsdesk`. `services/*` never import `opsdesk`.

## Alternatives considered

| Option | Why not (for now) |
|---|---|
| Everything in-process | Cannot demonstrate MCP/A2A boundaries, auth and failure handling |
| Every specialist as its own service | Network and ops overhead without an ownership boundary to justify it |
| MCP for Procurement | Long-running tasks needing human input are an agent task lifecycle, not a tool call |

## Rationale

> 🎯 Write this section in your own words. Questions to get you started:
> - What is the test for "this deserves its own process"?
> - Why is Procurement an *agent* (A2A) while the asset system is a *capability* (MCP)?

## Consequences

> 🎯 Write this section in your own words.

- **Positive:**
- **Negative:**
- **Follow-ups:**
