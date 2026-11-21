# 0004 — SQLite for the learning phase, with an upgrade path to Postgres

- **Status:** Accepted
- **Date:** 2026-11-21
- **Milestone:** M01

## Context

OpsDesk needs durable storage for domain data, the cost ledger, the audit chain and LangGraph
checkpoints. It runs on a native Windows dev machine and on Linux and Windows CI runners, with no
external services available by default.

## Decision

We will use SQLite (standard-library driver, `AsyncSqliteSaver` for checkpoints) behind repository
interfaces in `opsdesk.persistence`. Database files live under `var/`. Nothing outside
`persistence` depends on SQLite specifics, so Postgres can replace it later.

## Alternatives considered

| Option | Why not (for now) |
|---|---|
| Postgres from day one | Needs a server on every dev machine and CI job (Docker on Windows CI is awkward) |
| In-memory only | Cannot demonstrate resume, idempotency or a durable ledger |
| JSON files | No transactions; double counting and races in the ledger |

## Rationale

> 🎯 Write this section in your own words. Questions to get you started:
> - Which guarantees (transactions, unique keys) do the ledger and audit chain actually rely on?
> - What would have to change to move to Postgres, and what would not?

## Consequences

> 🎯 Write this section in your own words.

- **Positive:**
- **Negative:**
- **Follow-ups:**
