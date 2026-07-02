# PRD: Cogit MVP

created_datetime: 2026-05-26T21:00:00+03:00
updated_datetime: 2026-07-02T12:00:00+03:00
status: Draft

## Summary

Cogit is a Git-inspired local repository for agent cognition and reasoning provenance. It records immutable facts, snapshots of active context, reasoning checkpoints, pointer movement logs, and named anchors so an agent can explain, branch, merge, recover, and debug its own state over time.

The MVP should prove the core model with a transparent `.cogit/` directory and no external runtime dependencies. Cogit is not retrieval memory; it is version control for agent state and reasoning provenance.

## Problem

Agents often lose both content provenance and operational provenance. They may remember the current context, but not:

- which source introduced a belief;
- which reasoning step changed the active state;
- how to return to a previous cognitive checkpoint;
- how to compare two hypothesis branches;
- where an incorrect answer first entered the reasoning history.
- who or what moved the active hypothesis pointer.

Git solved a similar problem for code by storing immutable content-addressed objects and moving refs over a commit graph while keeping local logs of ref movements. Cogit applies that model to agent state and reasoning audit.

## Goals

- Persist agent cognitive state as immutable content-addressed objects.
- Support local branching of hypotheses without copying all state.
- Allow a human or agent to inspect objects, refs, and history directly.
- Provide enough operations to initialize, commit, branch, checkout, diff, merge, and blame.
- Keep the MVP small, local-first, and dependency-free.

## Non-Goals

- Replace a vector database or long-term semantic memory system.
- Provide automatic retrieval, embeddings, context assembly, or semantic search.
- Provide real-time multi-agent synchronization.
- Implement packfiles, custom binary storage, or compression dictionaries.
- Provide cryptographic trust, signatures, or permissioning.
- Optimize for very large histories before the core model is validated.
- Build a full UI.
- Transparently replace or rewrite historical thoughts by default.

## Users

- Agent developers who need explainable memory and reasoning traces.
- AI workflow builders who need reproducible context checkpoints.
- Researchers exploring agent self-debugging, branching, and rollback.
- Human operators diagnosing why an agent reached a conclusion.

## Product Principles

- Preserve Git's conceptual model where it helps: objects, refs, HEAD, index, branches, merge, blame, and reachable history.
- Prefer inspectable files over opaque infrastructure.
- Treat optimizations as later layers.
- Keep every MVP operation understandable from the repository layout.
- Make bad reasoning traceable to a source fact or thought.
- Separate immutable reasoning history from mutable pointer movement logs.
- Define history-query semantics explicitly: first introducer, not last modifier, for `blame-fact`.
- Keep raw object view authoritative; overlays and annotations must be explicit.

## MVP Scope

### Repository Initialization

Cogit can initialize this layout:

```text
.cogit/
  HEAD
  config
  index.json
  logs/
    HEAD
    refs/heads/main
  refs/
    heads/main
    anchors/
    remotes/
  objects/
  tmp/
```

Initial state:

- `HEAD` points to `refs/heads/main`.
- `refs/heads/main` may be empty until the first thought commit.
- `config` records repository format version and object format.
- `index.json` contains an empty staged fact list and an empty conflict list.
- `logs/HEAD` and branch logs are created when refs first move.

### Object Store

Cogit supports five object types (see `docs/adr/0008-claim-assertion-model.md`):

- `claim`: an immutable structured proposition (subject, predicate, object).
- `assertion`: provenance-bearing evidence about a claim: status, source,
  confidence, actor, method, time.
- `mindset`: a snapshot of active assertion object IDs.
- `thought`: a reasoning checkpoint pointing to a parent thought and mindset.
- `anchor`: a named milestone pointing to a thought.

"Fact" remains product shorthand for an active assertion about a claim; CLI
commands keep the fact language (`add-fact`, `blame-fact`).

Objects are stored as zlib-compressed canonical JSON preimages under `.cogit/objects/xx/...`, addressed by SHA-256.

Object reads verify the decompressed preimage against the object ID. Object writes reject malformed data and treat a same-path, different-content collision as corruption.

### Index

The index represents staged working memory before a thought commit.

It stores:

- staged fact IDs;
- removed fact IDs;
- conflict entries;
- base mindset ID when available.

### Thought Commit

A commit operation:

1. Reads staged facts from `index.json`.
2. Creates a `mindset` object.
3. Reads the current parent from `HEAD`.
4. Creates a `thought` object.
5. Atomically advances the current ref.
6. Appends a reflog entry for the ref movement.
7. Clears the index.

### Branching And Checkout

Cogit can:

- create a branch ref pointing at a thought;
- switch `HEAD` to a branch;
- detach `HEAD` at a specific thought;
- list branches and current position.

Branching must be O(1): only refs move, objects are not copied.

Every branch creation, checkout, and detached HEAD movement records an operational log entry.

### Diff

Cogit can compare two mindsets or two thoughts and return:

- added facts;
- removed facts;
- unchanged facts;
- changed confidence or metadata if represented as a new fact version.

The MVP diff is set-based, not semantic natural-language diff.

### Merge

Cogit supports a simple three-way merge over fact sets:

- find a common ancestor thought;
- compare base, ours, and theirs mindsets;
- auto-merge non-conflicting additions/removals;
- write conflicts into `index.json`;
- commit a merge thought after conflicts are resolved.

The MVP can use conservative conflict detection. If unsure, mark conflict rather than inventing a resolution.

### Blame

Cogit can answer: "which thought first introduced this fact?"

The MVP implementation may linearly walk history. Secondary indexes are out of scope until this becomes too slow.

`blame-fact` returns the first introducing thought in the selected ancestry. It does not mean "last modifier" and does not perform semantic similarity over fact text.

### Log, Status, And Verify

Cogit can inspect both content history and operational history:

- `log` walks thought ancestry from a ref or thought ID.
- `log -g` walks reflog entries for `HEAD` or a branch.
- `status` shows the current ref, staged facts, conflicts, and detached state.
- `verify` checks object hashes, object schemas, refs, and graph connectivity.

The MVP `verify` does not repair corruption. It reports enough context for manual recovery.

### Anchors

Cogit can create named anchors for important thoughts, such as:

- task-understood;
- plan-approved;
- root-cause-found;
- release-ready.

Anchors are immutable object records plus movable or fixed refs under `refs/anchors/`, depending on final implementation.

## Functional Requirements

- `cogit init` creates a valid repository layout.
- `cogit hash-object --write` writes a typed object and returns its SHA-256 ID.
- `cogit cat-object <id>` prints the decoded object.
- `cogit add-fact` writes claim and assertion objects and stages the assertion.
- `cogit remove-fact <assertion-id> --reason <reason>` stages a removal with an explicit reason.
- `cogit commit-thought --message --author` creates a thought and advances the current ref.
- `cogit branch <name>` creates a branch at the current thought.
- `cogit checkout <name-or-id>` updates `HEAD`.
- `cogit diff <a> <b>` compares two thoughts or mindsets.
- `cogit merge <branch-or-id>` performs a conservative merge.
- `cogit blame-fact <fact-id>` returns the first introducing thought.
- `cogit log [<ref-or-id>]` walks thought history.
- `cogit log -g [<ref>]` walks local ref movement history.
- `cogit status` prints current HEAD, branch, staged facts, and conflicts.
- `cogit verify` validates object integrity, schemas, refs, and connectivity.
- `cogit anchor <name> <thought-id>` records a named milestone.

## Non-Functional Requirements

- No external runtime dependencies for the core MVP.
- Repository data remains readable with standard filesystem tooling plus zlib/JSON decoding.
- Object writes are atomic.
- Object reads verify the object hash against its storage path.
- Duplicate object content deduplicates by hash.
- Existing objects are immutable after write.
- Ref updates must not leave partially written target files.
- Ref updates use old-object checks to avoid lost updates from concurrent writers.
- The object format includes enough type and size information to validate reads.

## Data Model

Authoritative schemas live in `docs/spec/object-format-v1.md`. Confidence is
an integer basis-point value (`confidence_bps`, 0..10000); floats are
forbidden in canonical objects.

Example `claim` with its `assertion` (together: a "fact"):

```json
{
  "type": "claim",
  "kind": "user_preference",
  "subject": "user",
  "predicate": "prefers_response_style",
  "object": "brief",
  "qualifiers": {}
}
```

```json
{
  "type": "assertion",
  "claim": "sha256:...",
  "status": "asserted",
  "source": {"type": "prompt", "uri": "conversation:current"},
  "confidence_bps": 9200,
  "asserted_at": "2026-05-26T18:00:00Z",
  "actor": "agent",
  "method": {"type": "user_statement"}
}
```

Example `mindset`:

```json
{
  "type": "mindset",
  "assertions": ["sha256:..."],
  "created_at": "2026-05-26T18:01:00Z"
}
```

Example `thought`:

```json
{
  "type": "thought",
  "parents": ["sha256:..."],
  "mindset": "sha256:...",
  "operation": "commit",
  "message": "Captured user's output preference.",
  "author": "agent",
  "timestamp": "2026-05-26T18:02:00Z"
}
```

## Milestones

### M1: Repository And Objects

- Initialize `.cogit/`.
- Write and read typed objects.
- Validate hash identity and object immutability.

### M2: Index And Commits

- Stage facts.
- Create mindset and thought objects.
- Advance `HEAD` and branch refs.

### M3: Branching And Inspection

- Create branches.
- Checkout branch or detached thought.
- Append reflog entries for HEAD and branch movement.
- Print thought logs, reflog logs, and current status.

### M4: Diff, Merge, Blame, Verify

- Compare fact sets.
- Merge two branches conservatively.
- Trace a fact to its first thought.
- Validate objects, refs, and graph connectivity.

### M5: Developer Polish

- Add concise CLI help.
- Add examples.
- Add tests for corruption, atomic writes, and duplicate object writes.
- Add recovery docs for reflog, dangling thoughts, and failed verify output.

## Acceptance Criteria

- A developer can create a Cogit repo, add two facts, commit a thought, branch, add a different fact, and checkout back to the original branch.
- Rewriting identical fact content returns the same object ID.
- `cat-object` can decode every object created by the MVP.
- `diff` reports fact additions and removals between two thoughts.
- `merge` never silently drops conflicting facts.
- `blame-fact` identifies the thought that introduced a selected fact.
- Every HEAD or branch movement creates a reflog entry.
- `verify` detects a corrupted object body, hash-path mismatch, malformed JSON, missing referenced object, and invalid ref.
- The repository remains understandable by inspecting `.cogit/HEAD`, `.cogit/logs`, `.cogit/refs`, `.cogit/index.json`, and `.cogit/objects`.

## Risks

- The `fact` schema may be too weak for semantic conflicts.
- Linear history walks may become slow earlier than expected.
- JSON canonicalization must be stable across runtimes.
- Atomic writes are simple for objects but trickier for coordinated ref/index updates.
- The Git analogy can overreach; Cogit should copy mechanisms only when they serve agent reasoning.
- Without a stable fact identity model, `blame-fact` can split semantically identical claims into different histories.
- Without reflog retention, local operational history can grow without bound.

## Open Questions

Resolved questions moved to `docs/open-questions.md` (Closed Questions):
anchor representation (object + ref, CQ-005), fact structure (structured
claims + assertions, CQ-003), confidence representation (`confidence_bps`,
CQ-004), first implementation shape (Python reference prototype, Rust
production target — ADR-0007/ADR-0010).

Still open:

- What is the minimum useful conflict schema for an LLM to resolve safely?
- What retention policy should apply to reflogs for long-running agents?
- Should post-hoc review annotations use notes-like refs in v0.2?
- What oracle interface is needed for future `bisect-thought`?
- When should `count-objects`, repack, or a thought-graph index become necessary?
