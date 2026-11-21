# 0005 — Qdrant local mode for vectors, BM25 for lexical search

- **Status:** Accepted
- **Date:** 2026-11-21
- **Milestone:** M10

## Context

Permission-aware RAG needs a lexical baseline, dense retrieval and filtering by tenant/ACL *before*
ranking, so that unauthorised chunks can never enter the context. It must run locally and in CI
without a server. See architecture.md §6.4 (W2 L2).

## Decision

We will use `rank-bm25` as the lexical baseline (M10) and `qdrant-client` in local (embedded) mode
for vectors (M11), with payload filtering on `tenant_id` and `allowed_groups`, combined by
reciprocal rank fusion.

## Alternatives considered

| Option | Why not (for now) |
|---|---|
| Qdrant server | Extra process to run on Windows and CI |
| FAISS / Chroma | Weaker or post-hoc metadata filtering for ACLs |
| Vectors only | No strong baseline for exact terms (error codes, product names) |

## Rationale

> 🎯 Write this section in your own words. Questions to get you started:
> - Why must the ACL filter run *before* ranking rather than after?
> - What does BM25 catch that embeddings miss, and vice versa?

## Consequences

> 🎯 Write this section in your own words.

- **Positive:**
- **Negative:**
- **Follow-ups:**
