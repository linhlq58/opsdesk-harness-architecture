# 0006 — Adapter-based observability: local always on, LangSmith/Langfuse optional

- **Status:** Accepted
- **Date:** 2026-11-21
- **Milestone:** M07

## Context

Runs must be debuggable without any account or network access (including in CI), while the course
also covers LangSmith and Langfuse. Neither backend should be required to run, test or evaluate
OpsDesk.

## Decision

We will always write local events (JSONL under `var/`). LangSmith and Langfuse are optional
adapters, enabled by environment variables and attached as callbacks by the model factory.
Redaction happens before anything leaves the process.

## Alternatives considered

| Option | Why not (for now) |
|---|---|
| LangSmith only | Requires an account and network; CI and offline work break |
| Langfuse only | Same problem; its API has also changed since the course (v3 → v5) |
| Local logs only | Misses the course objectives on hosted tracing |

## Rationale

> 🎯 Write this section in your own words. Questions to get you started:
> - What must still work when no tracing backend is configured?
> - Where exactly is redaction applied, and why there?

## Consequences

> 🎯 Write this section in your own words.

- **Positive:**
- **Negative:**
- **Follow-ups:**
