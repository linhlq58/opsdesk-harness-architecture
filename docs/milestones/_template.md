# MNN — <Title>

**Goal:** <one or two sentences: what works at the end that did not work before>

**Estimated effort:** <1–2 sessions>

**Learning objectives:**
- <harness/agent concept 1>
- <concept 2>

**Course topics:** <W? L?, ...>

**How you learn in this milestone:** Claude Code writes all code. You (1) answer the Design decisions, (2) predict the demo output, (3) run it, (4) do the Break-it exercises, (5) go through the Review checklist, (6) explain one scenario back in your own words.

---

## 0. Scope
### In scope
- ...
### Explicitly out of scope
| Not here | Where it goes | Why |
|---|---|---|

## 1. Version check (Claude Code, first step)
| Package | Installed | Latest | API differences from the course material |
|---|---|---|---|

## 2. Wiring: how this milestone uses what already exists
One table for the main flow. Each row is a step a request goes through; new pieces are in bold.

| Step | Piece used | Built in |
|---|---|---|
| ... | ... | M0x / **this milestone** |

## 3. Design decisions (🎯 you, before any code)
Each decision: the question, 2–3 options with their consequences, and a recommendation. Record your choice and one sentence of reasoning in the Notes. Claude Code implements only after the decisions are recorded.

| # | Question | Options and consequences | Recommended |
|---|---|---|---|
| D1 | ... | A: ... → ... · B: ... → ... | A, because ... |

## 4. Files
| File | Content | Owner (🎯 decide & verify / 📖 / ⚙️) |
|---|---|---|

## 5–N. Design sections
<One section per 🎯 piece: what it must do, contract/signature, rules, test cases. Written so Claude Code can implement it and you can verify it.>

## Demo scenario
`uv run poe demo mNN` (deterministic, fake model, runs in CI) and `uv run poe demo mNN --live` (real model, manual).

```
▶ Scenario 1: <who> asks <what>
  [step]  <piece> → <result>
  [events] seq0 ... · seq1 ... · ...
▶ Scenario 2: ...
```

## Predict (🎯 you, before running the demo)
For each scenario, write down in the Notes: the tool calls, the `ToolResult` status / reason code, the event kinds in order, what the model will say. Then run the demo and compare. Every wrong prediction is something to ask about.

## Break-it exercises (🎯 you, with Claude Code's help; revert afterwards)
| # | Change | Question to answer |
|---|---|---|
| B1 | <remove / alter one harness piece> | Which test, demo line or eval case catches it? What would happen in production? |

## Review checklist (🎯 you)
Ask Claude Code to point to the exact block (`file:line`) for each item, then judge it yourself.

- [ ] Identity comes only from `RequestContext`, never from messages or tool arguments
- [ ] No `except Exception` that turns bugs into polite answers
- [ ] Every tool call emits `tool_started` and `tool_finished`
- [ ] <milestone-specific item>

## Eval cases (from M07 on)
| Case id | Input | Expected (route / tools / status / reason code) |
|---|---|---|

## Explain-back (🎯 you)
In the Notes, explain scenario <n> from user message to final answer in your own words (5–10 lines). Ask Claude Chat to check it.

## Self-check questions (trace style)
Questions follow a concrete request through the system: "Where is the decision made? What does the model see? What does the JSONL file contain?"

## Definition of done
- [ ] Version check recorded
- [ ] Design decisions recorded before implementation
- [ ] Demo scenario runs (`poe demo mNN`), including in CI; predictions compared
- [ ] Break-it exercises done and reverted
- [ ] Review checklist completed
- [ ] Eval cases added and eval gate green (from M07)
- [ ] `uv run poe check` green locally; CI green on Linux and Windows
- [ ] Explain-back written and self-check questions answered
- [ ] Commit: `feat(mNN): ...`

## Suggested prompts for Claude Code
> ...

## Notes (fill in)
### Decisions
- D1:
### Predictions vs actual
-
### Break-it findings
-
### Explain-back
-
