# Cogit Glossary

created_datetime: 2026-05-26T21:40:00+03:00
updated_datetime: 2026-05-27T09:41:00+03:00
status: Draft

## Purpose

This glossary fixes the core vocabulary for Cogit before implementation. When a term appears in ADRs, PRD, specs, user stories, or code, it should use the meaning below.

## Terms

### Agent

The AI process using Cogit to record reasoning state. The agent is the primary user in `user_stories/agent-user-stories.md`.

### Anchor

An important named milestone pointing to a thought. Examples: `task-understood`, `plan-approved`, `root-cause-found`, `release-ready`.

An anchor is not a mutable memory entry. It is a provenance marker.

### Annotation

An append-only post-hoc overlay on a thought, assertion, or claim: review
verdicts, eval results, policy flags. Annotations chain per typed namespace
under `refs/notes/<namespace>` and never rewrite their targets (ADR-0012).

### Assertion

An immutable provenance-bearing statement about a claim. It records the claim ID, status, source, confidence, assertion time, actor, and method.

In product language, an active assertion about a claim may be called a fact.

### Blame-Fact

A query that returns the first thought in selected ancestry that introduced a fact. It does not mean "last modifier" and does not use semantic similarity.

### Branch

A movable ref under `refs/heads/` pointing to the tip thought of a hypothesis line.

### Cognitive Repository

A `.cogit/` directory containing immutable objects, mutable refs, reflogs, index state, and repository metadata.

### Claim

An immutable structured proposition. A claim describes what is being asserted, while assertions describe who or what asserted it, with which confidence and source.

### Fact

Product shorthand for an active assertion about a claim.

The storage model uses `claim` and `assertion` objects. The term fact remains useful in CLI/user stories when the distinction is not important.

### HEAD

The current active position. `HEAD` may be symbolic (`ref: refs/heads/main`) or detached at a thought ID.

### Hypothesis

A branch of reasoning that may differ from another branch. A hypothesis is represented by a branch ref and its reachable thought history.

### Index

The staged working memory before a thought commit. The index is mutable and may contain staged fact IDs, removed fact IDs, conflicts, and merge metadata.

The index is not long-term memory.

### Mindset

An immutable snapshot of active assertion object IDs plus metadata. A mindset is similar to a Git tree in role, but it does not imply POSIX paths.

### Object

An immutable content-addressed record stored under `.cogit/objects/xx/...`. MVP object types are `claim`, `assertion`, `mindset`, `thought`, `anchor`, and `annotation` (ADR-0012).

### Operational Provenance

The local history of pointer movement: checkouts, commits, branch updates, detached HEAD moves, and recovery-relevant ref changes. Operational provenance lives in reflogs.

### Provenance

Evidence of what was committed, where it came from, which thought introduced it, and how the active hypothesis moved. Provenance is Cogit's core purpose.

### Ref

A mutable pointer to a thought ID or another ref. Branches and anchors are refs.

### Reflog

An append-only local journal of ref movement. Reflog answers "where did this pointer point before?" It is local operational history, not shared immutable content history.

### Retrieval Memory

A system for finding context relevant to a future model call. Cogit is not retrieval memory in the MVP.

### Source

The origin claimed by an assertion: prompt, tool result, file path, URL, system instruction, manual input, agent output, or another explicit signal. Source is semantic provenance, not cryptographic trust.

### Thought

An immutable reasoning checkpoint. A thought points to a mindset, zero or more parent thoughts, operation metadata, author, timestamp, and message.

### Verify

A repository health check that validates object hashes, schemas, refs, and graph connectivity. `verify` reports problems; it does not repair them in MVP.

### Working Context

The agent's live context that has not necessarily been staged or committed. Cogit only records it after facts are staged and committed into thoughts.
