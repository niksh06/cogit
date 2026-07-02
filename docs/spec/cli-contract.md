# CLI Contract

created_datetime: 2026-05-26T21:40:00+03:00
updated_datetime: 2026-07-02T12:00:00+03:00
status: Draft

## Purpose

This document defines the MVP command-line behavior for Cogit. The CLI is a porcelain layer over stable repository operations.

## General Rules

- Commands operate on the nearest `.cogit/` repository unless `--repo <path>` is provided.
- Commands must not require a daemon.
- Human output is concise by default.
- Machine-readable output may be added with `--json`.
- Commands that mutate refs append reflog entries.
- Commands that fail must leave refs and index in a consistent state.

## Exit Codes

- `0`: success.
- `1`: user error, invalid input, unresolved conflict, or verification failure.
- `2`: repository not found or invalid repository layout.
- `3`: corruption detected.
- `4`: concurrent update or lock failure.
- `5`: unsupported repository format or extension.

## Commands

### `cogit init [path]`

Creates a `.cogit/` repository.

Must create:

- `HEAD`;
- `config`;
- `index.json`;
- `refs/heads/`;
- `refs/anchors/`;
- `logs/`;
- `objects/`;
- `tmp/`.

### `cogit hash-object --type <type> [--write] <file>`

Computes an object ID for canonical object JSON.

Rules:

- Without `--write`, does not mutate the repository.
- With `--write`, stores the object if absent.
- Rejects malformed objects.

### `cogit cat-object <object-id>`

Prints decoded object JSON.

Rules:

- Verifies object hash before printing.
- Fails on missing, corrupt, or schema-invalid objects.

### `cogit add-fact [<json-or-file>] [shorthand flags]`

Writes claim and assertion objects and stages the assertion in `index.json`.

Input is a fact document:

```json
{
  "claim": { "type": "claim", "...": "..." },
  "assertion": { "type": "assertion", "...": "..." }
}
```

or the equivalent shorthand (COG-027):

```sh
cogit add-fact --kind agent_decision --subject cogit:mvp \
  --predicate first_slice --object object_store \
  --source manual:design-session --confidence 9500 \
  [--qualifier k=v ...] [--negates <claim-id>] [--object-json <json>] \
  [--actor agent] [--method cli] [--asserted-at <iso-utc>]
```

Rules:

- Shorthand and equivalent JSON must produce identical object IDs;
  `--asserted-at` defaults to now (UTC).
- The `assertion.claim` reference is filled from the written claim
  automatically; if present, it must match.
- Does not create a thought.
- Is idempotent for the same assertion ID.
- Shows claim and staged assertion IDs on success.

### `cogit remove-fact <assertion-id> --reason <reason>`

Stages removal of an active assertion from the base mindset.

Rules:

- The assertion must be active in the base mindset or staged.
- A reason is required (`refuted`, `superseded`, or free text).
- Removing a staged-but-uncommitted assertion unstages it.

### `cogit commit-thought --message <text> --author <id>`

Creates a mindset and thought from the index, then advances the current ref.

Rules:

- Fails if the index has unresolved conflicts.
- Fails if the current ref moved since parent was read.
- Fails when nothing is staged or removed, unless a merge is in progress.
- In merge state, creates a merge thought with two parents.
- Appends reflog entry.
- Clears index only after successful ref update.

### `cogit branch [<name>] [<thought-id>]`

Creates a branch at a thought, or lists branches when called without
arguments (current branch is marked).

Rules:

- Defaults to current thought.
- Rejects invalid names.
- Does not copy objects.
- Appends branch reflog entry.

### `cogit checkout <branch-or-thought-id>`

Switches `HEAD`.

Rules:

- Branch checkout writes symbolic `HEAD`.
- Thought checkout writes detached `HEAD`.
- Appends `logs/HEAD`.
- Does not mutate objects or index unless a future option explicitly says so.

### `cogit status`

Shows repository state.

Must include:

- branch or detached HEAD;
- current thought ID;
- staged facts count;
- removed facts count;
- conflict count;
- merge state when present.

### `cogit log [<ref-or-id>]`

Walks thought ancestry.

MVP output includes:

- thought ID;
- parents;
- author;
- timestamp;
- operation;
- message.

### `cogit log -g [<ref>]`

Walks reflog entries.

MVP output includes:

- old target;
- new target;
- timestamp;
- actor;
- operation;
- reason.

### `cogit diff <a> <b>`

Compares two thoughts or mindsets.

MVP output includes:

- added fact IDs;
- removed fact IDs;
- optionally unchanged fact IDs.

No semantic diff is implied.

### `cogit merge <branch-or-id>`

Performs conservative fact-set merge.

Rules:

- Finds common ancestor when possible.
- Auto-merges compatible changes into the index and records merge state.
- Reports "already up to date" when the target is in current ancestry.
- Writes conflicts to index. Two assertions about the same claim arriving
  from different sides is a conflict.
- Does not commit automatically unless a future option explicitly says so;
  the merge thought is created by `commit-thought`.

### `cogit resolve <claim-id> (--keep <assertion-id> | --drop)`

Resolves a recorded merge conflict for one claim.

Rules:

- `--keep` stages the chosen assertion; `--drop` stages none of them.
- Removes the conflict entry from the index.
- Editing `index.json` by hand remains a legal fallback; the file is the
  authority.

### `cogit blame-fact <fact-id> [<ref-or-id>]`

Returns the first introducing thought in selected ancestry.

Rules:

- Exact fact ID only.
- No semantic text matching.
- Linear traversal is acceptable in MVP.

### `cogit verify`

Checks repository health.

Rules:

- Reports all detected errors when practical.
- Does not repair.
- Returns `0` only if repository is healthy.
- Returns `3` when corruption is detected.

### `cogit anchor [<name> <thought-id>]`

Records a named milestone, or lists anchors when called without arguments.

Rules:

- Target thought must exist.
- Writes an anchor object and points `refs/anchors/<name>` at it.
- Anchor creation does not rewrite the target thought.
- Anchor movement, if allowed, appends a reflog entry.

## Error Message Requirements

Error messages should include:

- command name;
- path or object ID involved;
- short reason;
- recovery hint when obvious.

Example:

```text
cogit cat-object: sha256:abc... hash mismatch; run `cogit verify`
```

## Non-Goals

MVP CLI does not include:

- network sync;
- signatures;
- pack maintenance;
- semantic search;
- UI server;
- automatic repair.
