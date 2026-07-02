# ADR-0001: KISS filesystem architecture for Cogit MVP

created_datetime: 2026-05-26T21:00:00+03:00
updated_datetime: 2026-05-26T21:28:00+03:00
status: Proposed

## Context

Cogit is an experiment in "Git for agents": a local version-control layer for agent state and reasoning provenance. It records what an agent believed, which thought introduced that belief, and how the active hypothesis moved over time.

Cogit is not a vector database, retrieval memory, or chat-history store. Retrieval systems answer "what context should the agent recall now?" Cogit answers "what was committed, when, by whom, and through which reasoning checkpoint?"

The initial concept in `ideas/kimi.md` maps Git primitives to Cogit primitives:

- `blob` -> `fact`
- `tree` -> `mindset`
- `commit` -> `thought`
- `tag` -> `anchor`
- `branch` -> hypothesis line
- `HEAD` -> current active thought
- `index` -> staged working memory

The local official Git repository confirms the architectural principles this project wants to preserve:

- Git presents both high-level porcelain and low-level access to internals.
- A repository is a directory of control files and object storage.
- Loose objects are stored under `objects/xx/...` using the first two hash characters as a fanout directory.
- `HEAD`, `refs/heads/*`, `refs/tags/*`, and `refs/remotes/*` are mutable pointers to immutable history.
- The index is the staged state that can be committed.
- Git is fundamentally a content-addressable filesystem.
- Packfiles, commit-graph, reftable, and other indexes are performance layers, not the starting point.
- Git selected SHA-256 as the stronger successor hash for content addressing.

The first implementation should therefore optimize for transparency, inspectability, and local durability rather than distributed scale or storage efficiency.

## Decision

Build Cogit MVP as a plain filesystem-backed repository rooted at `.cogit/`.

The MVP repository layout is:

```text
.cogit/
  HEAD
  index.json
  logs/
    HEAD
    refs/
  refs/
    heads/
    anchors/
    remotes/
  objects/
    xx/
      <sha256-rest>
```

Use these object types:

- `fact`: immutable atomic assertion with source and confidence.
- `mindset`: immutable snapshot containing ordered fact object IDs and metadata.
- `thought`: immutable reasoning checkpoint containing parent thought ID, mindset ID, message, author, and timestamp.
- `anchor`: immutable named milestone pointing at a thought.

Use this storage contract:

- Canonical JSON as object content.
- Object preimage format: `<type> <size>\0<canonical-json>`.
- SHA-256 of the preimage as the object ID.
- zlib-compressed preimage as the stored object body.
- Fanout path: `.cogit/objects/<first-2-hex>/<remaining-62-hex>`.
- Atomic writes through temporary files followed by `os.replace`.

Use text files for mutable state:

- `.cogit/HEAD` stores either `ref: refs/heads/main` or a detached thought ID.
- `.cogit/refs/**` store thought IDs.
- `.cogit/index.json` stores staged fact IDs and unresolved conflicts.
- `.cogit/logs/**` stores an append-only local journal of ref movements.

Expose a small porcelain API first:

- `init`
- `hash-object` / `cat-object`
- `add-fact`
- `commit-thought`
- `branch`
- `checkout`
- `diff-mindset`
- `merge`
- `blame-fact`
- `log`
- `status`
- `verify`
- `anchor`

Defer these features until the MVP shows real pressure:

- RocksDB, LMDB, SQLite, or any other database.
- Rust or Go reasoning engine.
- MessagePack or other binary serialization.
- Packfiles and semantic delta compression.
- Network protocol, gRPC, daemon mode, or real-time sync.
- Ed25519 signatures.
- Bloom filters, commit-graph-style accelerators, and secondary indexes.
- Notes, rerere, bisect, replace/grafts, and other advanced history tools.

## Rationale

Cogit should inherit Git's most important product quality: a developer can inspect the repository directly and understand what happened.

For an agent provenance system, debuggability matters more than early throughput. If an agent begins reasoning from a bad fact, a human should be able to decompress and pretty-print objects, inspect refs, compare mindsets, inspect ref logs, and trace the fact to the thought that introduced it.

The KISS design also keeps the implementation small enough to validate the domain model before optimizing it. Git's own architecture supports this sequence: loose objects and plain refs are easy to understand; packfiles and advanced indexes can be layered on later.

## Consequences

Positive:

- Zero runtime dependencies beyond the standard library of the implementation language.
- Easy local debugging with filesystem tools.
- Clear mapping from Git concepts to Cogit concepts.
- Portable repositories that can be copied, archived, and synchronized as directories.
- Natural path to later performance layers without changing the core object model.
- Clear separation between immutable reasoning history and mutable operational pointers.

Negative:

- Large histories will create many small files.
- Linear history walks may be slow for `blame-fact` and merge-base lookup.
- Concurrent writers require careful atomic update discipline.
- No built-in trust model for imported thoughts.
- No efficient network exchange in the MVP.
- Reflog-style operational history grows until a retention policy is introduced.

## Alternatives Considered

### Embedded KV store

RocksDB, LMDB, or SQLite would improve lookup and update patterns, but they obscure the repository and add dependency, migration, and corruption-recovery concerns before the object model is proven.

### Binary object encoding

MessagePack would reduce size and support binary payloads, but it makes manual inspection harder. JSON is preferable while the schema is still evolving.

### Service-oriented architecture

gRPC, daemonized storage, and remote synchronization would make sense for multi-agent swarms, but they are not needed to validate a local cognitive repository.

### Early packfiles

Packfiles are a proven Git scaling technique, but MVP Cogit can tolerate loose objects. Packfiles should be introduced only after object counts and storage overhead become measurable problems.

## Acceptance Criteria

- A new `.cogit/` repository can be initialized in an empty directory.
- Writing the same object twice returns the same SHA-256 object ID and does not create duplicate logical content.
- A thought commit creates a mindset object, a thought object, and advances the current ref atomically.
- Every HEAD or branch movement appends a local reflog entry.
- A branch checkout changes `HEAD` without copying object data.
- A fact can be traced to the first thought that introduced it, even if implemented by a linear walk.
- `verify` detects malformed objects, hash mismatches, missing referenced objects, and invalid refs.
- All MVP objects can be manually decompressed and rendered as JSON.

## References

- `ideas/kimi.md`
- `git/README.md`
- `git/Documentation/gitrepository-layout.adoc`
- `git/Documentation/glossary-content.adoc`
- `git/Documentation/gitformat-loose.adoc`
- `git/Documentation/gitformat-pack.adoc`
- `git/Documentation/technical/hash-function-transition.adoc`
