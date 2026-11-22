# MNN — <Title>

**Goal:** <one or two sentences: what works at the end that did not work before>

**Estimated effort:** <1–2 sessions>

**Learning objectives:**
- <harness/agent concept 1>
- <concept 2>

**Course topics:** <W? L?, ...>

---

## 0. Scope
### In scope
- ...
### Explicitly out of scope
| Not here | Where it goes | Why |
|---|---|---|

## 1. Version check (first step)
| Package | Installed | Latest | API differences from the course material |
|---|---|---|---|

## 2. Wiring: how this milestone uses what already exists
One table for the main flow of the milestone. Each row is a step a request goes through; new pieces are in bold.

| Step | Piece used | Built in |
|---|---|---|
| ... | ... | M0x / **this milestone** |

## 3. Files
| File | Content | Owner (🎯 / 📖 / ⚙️) |
|---|---|---|

## 4–N. Design sections
<One section per 🎯 piece: contract/signature, rules, cases. Signatures are given; 🎯 bodies are written by the user.>

## Demo scenario
`uv run poe demo mNN` (deterministic, fake model, runs in CI) and `uv run poe demo mNN --live` (real model, manual).

```
▶ Scenario 1: <who> asks <what>
  [step]  <piece> → <result>
  [events] seq0 ... · seq1 ... · ...
▶ Scenario 2: ...
```

The demo must run before the milestone counts as done. It extends `demos/` so that, by M21, every milestone has a runnable scenario.

## Eval cases (from M07 on)
| Case id | Input | Expected (route / tools / status / reason code) |
|---|---|---|

## Self-check questions (trace style)
Questions follow a concrete request through the system: "Where is the decision made? What does the model see? What does the JSONL file contain?"

## Definition of done
- [ ] Version check recorded
- [ ] Demo scenario runs (`poe demo mNN`), including in CI
- [ ] Eval cases added and eval gate green (from M07)
- [ ] `uv run poe check` green locally; CI green on Linux and Windows
- [ ] Self-check questions answered
- [ ] Commit: `feat(mNN): ...`

## Suggested prompt for Claude Code
> ...

## Notes (fill in)
-
