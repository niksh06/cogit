---
name: cogit-journaling
description: Write clean cogit facts in-flow — prose→triple decomposition, lifecycle by family, when NOT to write. Load when journaling beliefs to a cogit repository via MCP or CLI.
---

# Cogit journaling — write like a commit, land like a claim

You are an engineer mid-task, not a librarian. This skill makes the clean
shape the cheap shape. The full model is `docs/claim-modeling.md`
(Rules 1–10) and `docs/journal-discipline.md` (D1–D10); this is the
at-write distillation.

## The 10-second decomposition

A finding forms as a sentence. Split it BEFORE calling `add_fact`:

> "connection pool exhausted by retry storm — saw 98% saturation in
> grafana, three FAILED suites before the fix"

| part | field | rule |
|---|---|---|
| what it's about | `subject: bug:orders-500` | URI, not phrase (auto-slugged since 0.5.0, but write it clean) |
| the repeatable relation | `predicate: root_cause` | reusable snake_case token — NOT a headline |
| the value | `object: "connection pool exhausted by retry storm"` | ≤12 words; a VALUE |
| everything else | `detail: "saw 98% saturation in grafana, three FAILED..."` | same call, lands as an annotation |

Under load? Pass `normalize: true` — a prose object splits
deterministically (first clause → value, FULL original → detail,
response reports what happened). Opt-in, never silent.

## State changes are lifecycle ops, not new facts

The value changed → do NOT `add_fact` a rival. Since 0.5.0 you don't
need the old id:

- `supersede_fact(subject=…, predicate=…, object=<new>)` — new value,
  same family.
- `refute_fact(subject=…, predicate=…)` — it was WRONG (structural
  negation; never write "REFUTE" in prose).
- `retire_fact(subject=…, predicate=…, reason=…)` — no longer relevant,
  no falsity implied.

Several active rivals → the call refuses and lists them; pick by id
(that family needs the cleanup anyway — `lint` shows it).

## Defaults do the ceremony (MCP)

Minimal fact = `kind + subject + predicate + object` (+ `project` on a
shared journal — always). Source defaults to `agent:<instance>`,
confidence to 9000 (`tool_observation` 9900). Confidence bands: 9800+
only for direct observation; agent inference/decisions sit at 9000–9700.

## When NOT to write

Derivable from git/BACKLOG/code — don't. Narrating your reasoning steps
— don't (that's the transcript's job). Ticket statuses of shipped work —
don't (BACKLOG holds them). Write what a DIFFERENT session needs in a
week: decisions, verdicts, constants, root causes, user preferences.

## Session rhythm

Start: `dump` / `health` (one-call re-anchor). Milestone: `anchor`.
Batch of related facts: `record` (one atomic thought). Response `hints`
are the linter talking to you at write time — fix the NEXT write.
