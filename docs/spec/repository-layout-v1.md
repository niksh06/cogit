# Repository Layout v1

created_datetime: 2026-05-26T21:40:00+03:00
updated_datetime: 2026-07-02T12:00:00+03:00
status: Draft

## Purpose

This document defines the MVP `.cogit/` repository layout and mutable file rules.

## Layout

```text
.cogit/
  HEAD
  config
  index.json
  logs/
    HEAD
    refs/
      heads/
      anchors/
  refs/
    heads/
      main
    anchors/
    remotes/
  objects/
    xx/
      <sha256-rest>
  tmp/
```

## Required Files

### `HEAD`

Stores the active position.

Allowed forms:

```text
ref: refs/heads/main
sha256:<thought-id>
```

The first form is symbolic. The second form is detached.

### `config`

Stores repository format metadata.

MVP fields:

```ini
[core]
  repositoryFormatVersion = 1
[extensions]
  objectFormat = sha256
```

Unknown required extensions must cause the implementation to refuse opening the repository.

### `index.json`

Stores staged working memory.

Minimum shape:

```json
{
  "base_mindset": null,
  "staged_facts": [],
  "removed_facts": [],
  "conflicts": [],
  "merge": null
}
```

Field semantics:

- `base_mindset`: mindset ID of the thought the staging round started from,
  or `null` before the first commit.
- `staged_facts`: assertion IDs staged for the next thought.
- `removed_facts`: entries `{"id": "sha256:<assertion-id>", "reason": "..."}`;
  removals always carry an explicit reason.
- `conflicts`: entries
  `{"claim": "sha256:<claim-id>", "ours": [...], "theirs": [...], "base": [...]}`
  produced by merge; unresolved conflicts block commit. Merge may add
  `"fingerprint"` and, when a remembered resolution exists, `"suggestion"`
  (COG-020); suggestions are informational and never auto-applied.
- `merge`: `null`, or `{"ours": "...", "theirs": "...", "base": "..."}`
  thought IDs while a merge is in progress. A commit performed in this state
  becomes a merge thought with `parents[0]=ours`, `parents[1]=theirs`.

The index is mutable. It must not be treated as committed history.

### `rerere.json` (optional)

Local conflict-resolution memory (COG-020): a map of normalized conflict
fingerprints to remembered outcomes. Analogous to git's `rr-cache`:
mutable, per-repository preference data — not history, never part of
provenance. Written via tmp+rename; absence means no stored resolutions.

### `refs/`

Stores mutable pointers.

Rules:

- `refs/heads/<name>` points to a thought ID.
- `refs/anchors/<name>` points to an anchor object ID; the anchor object
  carries the target thought plus audit metadata (decided per CQ-005).
  Traversal commands dereference the anchor to its target thought.
- `refs/notes/<namespace>` points to the newest annotation object of an
  append-only annotation chain (ADR-0012).
- `refs/remotes/` is reserved for future sync.

### `logs/`

Stores append-only local movement logs.

Rules:

- `logs/HEAD` records HEAD movements.
- `logs/refs/heads/<name>` records branch movements.
- Reflogs are local operational provenance.
- Reflogs are not immutable object history.

### `objects/`

Stores immutable content-addressed objects using fanout directories.

Objects are published only through object-format write rules.

### `tmp/`

Stores temporary files created during object writes, ref updates, or recovery operations.

Temporary files may be cleaned on startup if they are not locked by a live process.

## Ref Names

Allowed ref segments:

- lowercase letters;
- digits;
- `-`, `_`, `.`, `/`.

Disallowed:

- empty segments;
- `..`;
- leading or trailing `/`;
- ASCII control characters;
- whitespace;
- `@{`;
- backslash;
- names ending with `.lock`.

## Locking And Atomic Updates

Mutable files use lockfile replacement:

```text
<path>.lock -> write -> fsync if available -> atomic rename to <path>
```

Rules:

- Never write mutable files in place.
- Ref updates must check expected old target.
- `HEAD` updates use the same lockfile protocol with an expected-old-content
  check under the lock; symbolic (`ref: ...`) and detached forms are
  compared verbatim, and a concurrent move fails with the concurrency exit
  code instead of overwriting.
- Failed ref updates must not partially update the ref.
- Objects written before a failed ref update may remain unreachable.
- Reflog append failure after ref update is an error that must be surfaced.

## Reflog Entry Format

MVP reflog line:

```text
<old-target> <new-target> <timestamp> <actor> <operation>: <reason>
```

Rules:

- Empty old target is encoded as `null`.
- Targets use `sha256:` IDs or symbolic ref strings.
- Timestamp is ISO-8601 UTC.
- Reason is single-line text.

## Verify Rules

`cogit verify` checks:

- required files exist;
- `HEAD` is valid;
- refs point to valid object IDs where required;
- ref names are valid;
- object fanout paths match object IDs;
- objects pass `object-format-v1` read rules;
- thought parent links exist;
- thought mindsets exist;
- mindset facts exist;
- annotation targets and chain parents exist; annotation namespaces match
  the notes ref that reaches them;
- reflog lines parse.

## Non-Goals

Repository layout v1 does not define:

- packfiles;
- packed refs;
- reftable;
- alternates;
- network remotes;
- signatures;
- quarantine;
- garbage collection.
