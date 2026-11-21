# 0008 — Role-based models through an OpenAI-compatible gateway; fake models for tests

- **Status:** Accepted
- **Date:** 2026-11-21
- **Milestone:** M03

## Context

Different steps need different quality/cost trade-offs (routing is cheap; synthesis and judging
need more capability). The course provides an OpenAI-compatible gateway. Tests must never call a
paid model.

## Decision

We will select models by role (`router`, `specialist`, `synthesizer`, `judge`, `embedding`) through
a model factory in `opsdesk.llm`, configured from settings and pointed at the gateway via
`base_url`. Tests use fake chat models from `langchain-core` with scripted outputs.

## Alternatives considered

| Option | Why not (for now) |
|---|---|
| Hardcode a model name per call site | Switching a model means editing code everywhere; no cost experiments |
| One model for everything | Overpays for routing, or underperforms on synthesis |
| Record/replay real model calls in tests | Brittle cassettes; still needs a key to record |

## Rationale

> 🎯 Write this section in your own words. Questions to get you started:
> - Why select by *role* rather than by model name?
> - How does this make the M21 cheaper-router experiment a one-line change?

## Consequences

> 🎯 Write this section in your own words.

- **Positive:**
- **Negative:**
- **Follow-ups:**
