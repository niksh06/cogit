# Roadmap

created_datetime: 2026-05-26T21:40:00+03:00
updated_datetime: 2026-07-02T12:00:00+03:00
status: Draft

## Product Direction

Cogit grows from a local provenance tool into a reliable audit layer for agents. It should not grow into a retrieval memory platform.

## Status (2026-07-02)

Phases 0–3 are complete in the Python reference prototype (ADR-0010):
all MVP stories US-001..US-016 pass acceptance tests
(`prototype/tests/`, 86 tests), object-format vectors are frozen, and the
repository stays inspectable through `.cogit/`. Phase 4 is partially done
(fact-event log queries COG-019, `bisect-thought` COG-021; annotations and
rerere remain). Phase 5 is partially done (`count-objects` with thresholds
COG-022; `gc --auto` deferred until compaction exists). Work queue lives in
`BACKLOG.md`; the Rust production implementation is COG-013.

## Phase 0: Specification And Guardrails — DONE

Goal: make the implementation target unambiguous.

Includes:

- glossary;
- object format v1;
- repository layout v1;
- CLI contract;
- invariants;
- test strategy;
- recovery playbook;
- threat model.

Exit criteria:

- MVP stories are traceable to specs.
- Object format has test vectors.
- Open questions blocking implementation are resolved or explicitly deferred.

## Phase 1: Local Reasoning Journal — DONE (prototype)

Goal: commit and inspect reasoning state locally.

Includes:

- `init`;
- object write/read;
- `add-fact`;
- `commit-thought`;
- `cat-object`;
- `status`;
- `verify`;
- basic `log`.

Exit criteria:

- Healthy repository passes `verify`.
- Corruption fixtures fail `verify`.
- Thought commits are inspectable through `.cogit/`.

## Phase 2: Hypothesis Navigation — DONE (prototype)

Goal: branch, switch, diff, merge, and recover reasoning paths.

Includes:

- branch creation;
- checkout branch;
- detached checkout;
- reflog writes;
- `log -g`;
- `diff`;
- conservative merge;
- conflict index state;
- recovery docs.

Exit criteria:

- Branching does not duplicate objects.
- Reflog can recover previous `HEAD`.
- Merge conflicts block commit.

## Phase 3: Audit-Ready MVP — DONE (prototype)

Goal: complete the minimum useful local cognitive VCS.

Includes:

- `blame-fact`;
- anchors;
- first-introducer semantics;
- ref old-target checks;
- failure-mode tests;
- CLI help.

Exit criteria:

- All MVP user stories `US-001` to `US-016` pass acceptance tests.
- The repository remains human-inspectable.
- No retrieval-memory features have entered the core.

## Phase 4: Review And Regression Tooling

Goal: make Cogit useful for post-hoc review and debugging.

Includes:

- notes-like annotations;
- `log --introduced-fact`;
- repeated conflict resolution memory;
- `bisect-thought`;
- replayable bisect logs.

Entry criteria:

- MVP is stable.
- Users have real review or regression workflows.

## Phase 5: Maintenance Observability

Goal: measure repository pressure before optimizing.

Includes:

- `count-objects`;
- reflog size reporting;
- object count thresholds;
- manual `gc --auto` no-op below thresholds.

Entry criteria:

- Local repositories show measurable object, ref, or traversal pressure.

## Phase 6: Scaling Layers

Goal: add derived performance layers without changing object identity.

Includes when justified:

- packfiles;
- thought-graph index;
- fact-to-first-thought index;
- packed refs;
- alternates.

Entry criteria:

- linear walks or loose object counts exceed agreed thresholds.
- `verify` can validate before and after maintenance.

## Phase 7: Trust And Collaboration

Goal: support untrusted imports and shared histories.

Includes:

- signatures;
- quarantine;
- import verification;
- audit export;
- retention policy;
- protected anchors.

Entry criteria:

- Cogit is used across agent processes, teams, or machines.

## Stop Conditions

Pause roadmap expansion if:

- a feature requires semantic retrieval in core;
- a feature hides raw object inspectability;
- implementation cannot define recovery behavior;
- tests cannot validate the invariant it touches;
- a performance feature is proposed without measured pressure.
