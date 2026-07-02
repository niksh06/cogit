# ADR-0011: Why Cogit is not plain Git over JSON files

created_datetime: 2026-07-02T13:00:00+03:00
updated_datetime: 2026-07-02T13:00:00+03:00
status: Accepted

## Context

The most likely objection to Cogit: "put one JSON file per fact in a
directory and use Git itself — immutable history, branching, reflog, blame,
tooling, and hosting for free." If that objection holds, Cogit is a naming
convention, not a product. This ADR answers it explicitly (COG-011).

## Decision

Cogit remains a standalone implementation that borrows Git's architecture
(content-addressed objects, refs, reflog, index) but not Git's engine.

## Rationale: what breaks when the engine is Git

The comparison assumes the obvious encoding: one fact per file, a commit per
thought, branches per hypothesis.

1. **Merge semantics.** Git merges text lines inside files and detects
   conflicts per path. Cogit's unit of conflict is a *proposition family* —
   a claim, rival assertions about it, and its `negates` chain (ADR-0008,
   COG-015). Two branches adding different files never conflict in Git, yet
   "ours strengthened X, theirs refuted X" MUST conflict in Cogit. A custom
   merge driver cannot see across files; git merge drivers fire per path.
   This is the single strongest reason: Cogit's most valuable operation is
   exactly the one Git cannot express.
2. **Schema enforcement at write time.** Git stores any bytes. Cogit
   rejects malformed objects, floats, unknown fields, secrets, and
   contradiction-introducing commits at the storage boundary. With Git this
   becomes hooks, which are advisory, per-clone, and skippable.
3. **Blame semantics.** `git blame` answers "which commit last touched this
   line." Cogit's contract is *first introducer* of a fact in ancestry
   (ADR-0005) — implementable over Git only by walking history externally,
   at which point the engine provides no leverage.
4. **Fact identity.** Content-addressing whole JSON values (claim identity
   separate from assertion provenance) is Cogit's data model. In Git the
   addressable unit is a blob of the whole file; renaming a path silently
   changes identity semantics.
5. **Agent guardrails as storage invariants.** Dirty-index checkout block,
   no-prune default, reject-don't-redact secrets, mandatory removal
   reasons, refutation flow — these are contracts of the store, not
   conventions a caller may forget.
6. **Operational footprint.** Git brings gc, packfiles, and auto-maintenance
   that can rewrite storage layout under an agent mid-task. Cogit's MVP
   promises raw inspectability and no background mutation (ADR-0006).

## What we consciously give up

- Git's maturity, fuzzed C core, and two decades of edge cases.
- Free hosting, diff viewers, code review UIs.
- The ecosystem answer "it's just Git" during adoption conversations.

These losses are real. They are the price of owning merge and blame
semantics, which are the product.

## Revisit triggers

Re-open this decision if any of these happen:

- Distributed sync (Phase 7) starts reimplementing pack/transport — then
  evaluate Git as the *transport* layer while keeping Cogit semantics local.
- The Rust port (COG-013) stalls and maintenance cost dominates.
- A Git-backed prototype demonstrates family-level merge with acceptable
  ergonomics, contradicting point 1.

## References

- `issues/COG-011.md`
- `docs/adr/0005-first-introducer-blame.md`
- `docs/adr/0008-claim-assertion-model.md`
- `docs/spec/claim-assertion-examples.md` (enforcement section)
