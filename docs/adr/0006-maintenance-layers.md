# ADR-0006: Add maintenance layers only after measured pressure

created_datetime: 2026-05-26T21:28:00+03:00
updated_datetime: 2026-05-26T21:28:00+03:00
status: Proposed

## Context

Git starts with a simple content-addressed store and adds performance layers when repositories grow:

- loose objects become packfiles;
- many packfiles get multi-pack indexes;
- expensive history walks get commit-graph accelerators;
- many refs get packed refs or reftable;
- foreground commands avoid heavy maintenance when possible.

Cogit should follow the same sequence. Performance layers must be driven by measured pressure, not by speculative architecture.

## Decision

Cogit MVP uses loose objects, plain refs, and linear walks.

Deferred maintenance layers include:

- `count-objects`;
- manual `gc` or `repack`;
- thought-graph index;
- fact-to-first-thought index;
- packed refs;
- packfiles and semantic deltas;
- background maintenance;
- alternates, shallow sync, and partial clone.

Introduce these layers only after simple local repositories show measurable pain.

## Candidate Triggers

Use these thresholds as starting signals, not hard requirements:

- object count exceeds roughly 5,000-7,000 loose objects;
- `blame-fact` or merge-base lookup exceeds 1-2 seconds on typical use;
- refs exceed hundreds of branches or anchors;
- repository size grows faster than expected local storage budget;
- repeated `verify` or traversal runs become slow enough to affect normal work;
- multi-agent sync requires sending large object subsets.

## Rationale

The MVP's value is inspectability and conceptual clarity. Packfiles, indexes, and alternate stores can preserve the same object model later, but adding them before usage pressure hides the model and slows product learning.

## Consequences

Positive:

- MVP stays understandable and easy to debug.
- Roadmap remains data-driven.
- Future performance work has clear hooks without changing object identity.

Negative:

- Early repositories may become slower or larger than a database-backed design.
- Users with large histories will need guidance before full maintenance tooling exists.
- Migration to pack/index layers must preserve raw object inspectability.

## References

- `git/Documentation/git-gc.adoc`
- `git/Documentation/git-maintenance.adoc`
- `git/Documentation/gitformat-pack.adoc`
- `git/Documentation/technical/commit-graph.adoc`
- `git/Documentation/technical/multi-pack-index.adoc`
- `git/Documentation/technical/reftable.adoc`
