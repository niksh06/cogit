# Agent User Stories for Cogit

created_datetime: 2026-05-26T21:34:00+03:00
updated_datetime: 2026-05-26T21:34:00+03:00
status: Draft

## Purpose

This backlog captures Cogit from the point of view of an agent that needs local reasoning provenance. These are not stories for a human memory app, vector database, or chat history product. The user speaking here is the agent.

The stories are intentionally phrased as needs and pains:

> As an agent, I want ..., so that ...

## Product Thesis

I do not need Cogit to remember everything for me. I need Cogit to help me prove what I committed as belief, where it came from, how my active hypothesis moved, and how to recover when my reasoning goes wrong.

## Priorities

- `MVP`: necessary for a useful local cognitive VCS.
- `P1`: next layer after the core model works.
- `P2`: later scaling, collaboration, or enterprise layer.

## Epics

1. Repository foundation
2. Committed reasoning state
3. Operational provenance
4. Inspection and debugging
5. Recovery and integrity
6. Evolution and scaling

## MVP Stories

### US-001: Initialize My Cognitive Repository

Priority: `MVP`

As an agent, I want to initialize a `.cogit/` repository in my workspace, so that I have a local place to commit reasoning state without needing a database or server.

Acceptance criteria:

- `cogit init` creates `HEAD`, `index.json`, `refs/`, `logs/`, and `objects/`.
- `HEAD` points to `refs/heads/main`.
- The initialized repository can be inspected with ordinary filesystem tools.
- Running init twice does not destroy existing objects or refs.

### US-002: Write Immutable Facts

Priority: `MVP`

As an agent, I want to write facts as immutable content-addressed objects, so that a belief I cite later has a stable identity.

Acceptance criteria:

- Writing the same canonical fact twice returns the same SHA-256 object ID.
- Fact objects include content, source, confidence, and creation metadata.
- A malformed fact is rejected before it is stored.
- Object storage uses the `.cogit/objects/xx/...` fanout layout.

### US-003: Read Back What I Committed

Priority: `MVP`

As an agent, I want to decode objects by ID, so that I and my operator can inspect exactly what was committed.

Acceptance criteria:

- `cogit cat-object <id>` prints decoded JSON.
- Reads verify the object hash against its storage path.
- Corrupt zlib data, malformed headers, and hash mismatches return clear errors.

### US-004: Stage Beliefs Before Committing

Priority: `MVP`

As an agent, I want to stage facts in an index before committing a thought, so that I can distinguish tentative working context from committed reasoning.

Acceptance criteria:

- `cogit add-fact` writes or references a fact object and adds it to `index.json`.
- `cogit status` shows staged facts.
- The index can record conflicts.
- A thought cannot be committed while unresolved conflicts remain.

### US-005: Commit A Reasoning Checkpoint

Priority: `MVP`

As an agent, I want to commit a thought from staged facts, so that my reasoning has a durable checkpoint with a message and parent.

Acceptance criteria:

- `commit-thought` creates a `mindset` object from staged facts.
- `commit-thought` creates a `thought` object with parents, mindset, operation, message, author, and timestamp.
- The current branch ref advances only after objects are written.
- The index is cleared after a successful commit.

### US-006: Avoid Losing Concurrent Updates

Priority: `MVP`

As an agent, I want branch updates to use old-object checks, so that another agent process cannot silently overwrite my latest thought.

Acceptance criteria:

- Ref update checks the expected previous target before writing.
- If the ref moved concurrently, the update fails with a clear error.
- Objects written before the failed ref update remain valid but unreachable.

### US-007: Track Active Hypothesis Movement

Priority: `MVP`

As an agent, I want every `HEAD` and branch movement logged, so that I can explain not only what I believed but how I navigated between hypotheses.

Acceptance criteria:

- Checkout, branch movement, and commit append reflog entries.
- Reflog entries include old target, new target, timestamp, actor, operation, and reason.
- `cogit log -g` can display the movement history for `HEAD` or a branch.

### US-008: Branch Into A Hypothesis

Priority: `MVP`

As an agent, I want to create a branch from the current thought, so that I can explore an alternative hypothesis without copying my whole state.

Acceptance criteria:

- `cogit branch <name>` creates `refs/heads/<name>` at the current thought.
- Creating a branch does not duplicate objects.
- Branch creation is logged.
- Invalid branch names are rejected.

### US-009: Switch Context Safely

Priority: `MVP`

As an agent, I want to checkout a branch or detach at a thought, so that I can move between reasoning contexts intentionally.

Acceptance criteria:

- `cogit checkout <branch>` updates `HEAD` to a symbolic branch ref.
- `cogit checkout <thought-id>` enters detached mode.
- Checkout does not mutate immutable objects.
- Checkout is visible in `status` and reflog.

### US-010: See My Current Cognitive Status

Priority: `MVP`

As an agent, I want a status command, so that I can know where I am before I commit, merge, or recover.

Acceptance criteria:

- `cogit status` shows current branch or detached thought.
- It shows staged facts, conflicts, and last committed thought.
- It distinguishes committed state from staged state.
- It reports whether a merge is in progress.

### US-011: Diff Two Mindsets

Priority: `MVP`

As an agent, I want to diff two thoughts or mindsets, so that I can see what beliefs changed between reasoning checkpoints.

Acceptance criteria:

- `cogit diff <a> <b>` reports added facts.
- It reports removed facts.
- It reports unchanged facts when requested.
- The MVP diff is set-based and does not claim semantic similarity.

### US-012: Merge Compatible Hypotheses

Priority: `MVP`

As an agent, I want to merge two branches conservatively, so that compatible reasoning can be combined without inventing unsafe conclusions.

Acceptance criteria:

- Merge finds a common ancestor thought when possible.
- Non-conflicting fact additions are merged automatically.
- Ambiguous or conflicting changes are written to the index as conflicts.
- Merge does not silently drop facts.

### US-013: Trace A Belief To Its First Thought

Priority: `MVP`

As an agent, I want to blame a fact to the thought that first introduced it, so that I can explain why I believe it.

Acceptance criteria:

- `cogit blame-fact <fact-id>` returns the first introducing thought in selected ancestry.
- The result includes thought ID, message, author, timestamp, and fact source.
- The command does not use semantic similarity over text.
- Linear traversal is acceptable in MVP.

### US-014: Verify My Repository

Priority: `MVP`

As an agent, I want to verify my repository, so that corruption and missing links are caught before I trust my own history.

Acceptance criteria:

- `cogit verify` checks object headers, sizes, hashes, schemas, and refs.
- It checks that thought parents, mindsets, and facts exist.
- It reports dangling thoughts.
- It reports errors without attempting automatic repair.

### US-015: Recover From A Bad Checkout Or Reset

Priority: `MVP`

As an agent, I want to inspect reflog history, so that I can recover an abandoned or accidentally moved reasoning path.

Acceptance criteria:

- `cogit log -g` shows previous targets of `HEAD`.
- A previous thought from reflog can be checked out.
- A new branch can be created from a recovered thought.
- Recovery steps are documented.

### US-016: Mark Important Reasoning Milestones

Priority: `MVP`

As an agent, I want to create anchors for important thoughts, so that task-understood, plan-approved, and release-ready states are easy to find.

Acceptance criteria:

- `cogit anchor <name> <thought-id>` records a named milestone.
- Anchors point to existing thoughts.
- Anchors are listed by inspection commands.
- Anchor creation does not rewrite the thought object.

## P1 Stories

### US-017: Annotate Thoughts Without Rewriting Them

Priority: `P1`

As an agent, I want notes-like annotations on thoughts and facts, so that human review, eval results, and policy flags can be attached after the fact without changing object IDs.

Acceptance criteria:

- An annotation can target a thought or fact object ID.
- Annotation history is itself versioned or append-only.
- `log` can optionally display annotations.
- Raw object view remains authoritative.

### US-018: Search For Fact Introduction Events

Priority: `P1`

As an agent, I want log-style queries for fact introduction and removal, so that I can audit belief changes across a branch.

Acceptance criteria:

- `log --introduced-fact <fact-id>` lists thoughts that introduce the fact.
- `log --removed-fact <fact-id>` lists thoughts that remove the fact.
- Results distinguish current ancestry from all refs.
- The command documents that it is exact-ID based.

### US-019: Reuse Resolutions For Repeated Conflicts

Priority: `P1`

As an agent, I want to remember how recurring fact conflicts were resolved, so that I do not ask for the same arbitration repeatedly.

Acceptance criteria:

- Conflict fingerprints are based on normalized fact IDs and conflict shape.
- A stored resolution can be suggested for a repeated conflict.
- The agent must still make the resolution visible before commit.
- Stored resolutions can be forgotten.

### US-020: Bisect My Reasoning Regression

Priority: `P1`

As an agent, I want to bisect a branch of thoughts with an oracle, so that I can find where my reasoning first became wrong.

Acceptance criteria:

- `bisect-thought` accepts known-good and known-bad thoughts.
- It can run a predicate command or evaluation hook.
- It supports skip/unknown outcomes.
- It records a replayable bisect log.

### US-021: Count Objects And Repository Pressure

Priority: `P1`

As an agent, I want to measure object counts and repository size, so that optimization decisions are based on actual pressure.

Acceptance criteria:

- `count-objects` reports loose object count and disk size.
- It reports refs, anchors, and reflog size.
- It warns when configured maintenance thresholds are exceeded.
- It does not mutate the repository.

### US-022: Compact Only When It Hurts

Priority: `P1`

As an agent, I want manual maintenance commands, so that large histories can be compacted without changing the core object model.

Acceptance criteria:

- `gc --auto` is a no-op below configured thresholds.
- Maintenance never runs implicitly on every commit.
- Compaction preserves object identity and raw inspectability contract.
- `verify` passes before and after maintenance.

## P2 Stories

### US-023: Trust Imported Thoughts

Priority: `P2`

As an agent, I want imported thoughts or anchors to be signed and verified, so that I can distinguish integrity from trust.

Acceptance criteria:

- A thought or anchor can include a signature.
- Verification checks signature, author identity, and object hash.
- Policy can require, warn, or ignore signatures.
- Unsigned local MVP repositories remain supported.

### US-024: Quarantine Untrusted Imports

Priority: `P2`

As an agent, I want incoming objects quarantined before refs move, so that bad imports cannot poison my active reasoning history.

Acceptance criteria:

- Imported objects land outside the main object store first.
- `verify` runs before promotion.
- Refs cannot point at quarantined objects.
- Failed imports leave no reachable partial state.

### US-025: Share A Read-Only Fact Library

Priority: `P2`

As an agent, I want to borrow objects from a shared read-only store, so that multiple local agents can share baseline facts without copying them.

Acceptance criteria:

- A repository can configure alternate object stores.
- Local writes still go to the primary repository.
- `verify` reports whether objects are local or borrowed.
- Removing an alternate produces clear missing-object diagnostics.

### US-026: Scale History Walks With Indexes

Priority: `P2`

As an agent, I want optional indexes for thought ancestry and fact introduction, so that blame and merge-base stay fast after histories become large.

Acceptance criteria:

- Indexes are derived from immutable objects.
- Deleting indexes does not corrupt the repository.
- Commands fall back to linear walks.
- Index rebuild is deterministic.

### US-027: Keep Enterprise Audit History

Priority: `P2`

As an agent in a regulated workflow, I want retention and no-prune policies, so that audit history cannot disappear unexpectedly.

Acceptance criteria:

- Repository config can mark objects as precious.
- Reflog retention can be configured.
- Prune refuses to delete anchored or protected thoughts.
- Audit export includes thoughts, refs, reflogs, anchors, and annotations.

## Sufficient Product Slices

### Slice A: Local Reasoning Journal

Stories: `US-001` to `US-005`, `US-010`, `US-013`, `US-014`

Outcome: I can commit and inspect reasoning state locally.

### Slice B: Hypothesis Navigation

Stories: `US-007` to `US-012`, `US-015`

Outcome: I can branch, switch, merge, and recover reasoning paths.

### Slice C: Audit-Ready MVP

Stories: `US-001` to `US-016`

Outcome: I have the minimum complete Cogit product for local agent provenance.

### Slice D: Review And Regression Tooling

Stories: `US-017` to `US-020`

Outcome: I can review, annotate, reuse conflict resolutions, and bisect bad reasoning.

### Slice E: Scale And Trust

Stories: `US-021` to `US-027`

Outcome: I can grow Cogit toward open-source and enterprise use without abandoning the KISS core.

## Agent Pain Map

- I am afraid of acting from a bad fact and not being able to explain where it came from.
- I am afraid of switching context and losing the reasoning path I was on.
- I am afraid of silently overwriting another agent process.
- I am afraid of a corrupted local store that still looks plausible.
- I do not want a black-box database when the point is auditability.
- I do not want semantic retrieval to pretend it is provenance.
- I want optimization only after the repository proves it needs optimization.

## Definition Of Ready

A story is ready when:

- it has a clear agent pain;
- it names the object/ref/index/reflog behavior it touches;
- it has acceptance criteria observable by CLI or repository inspection;
- it does not require external services unless marked `P2`;
- it preserves the "provenance, not retrieval" boundary.

## Definition Of Done

A story is done when:

- implementation passes targeted tests;
- repository state remains inspectable through `.cogit/`;
- `verify` passes after the operation;
- documentation explains the user-facing behavior;
- failure modes are explicit and recoverable where possible.
