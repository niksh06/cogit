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
- Every porcelain command accepts `--json` for machine-readable output
  (COG-025); `init` and `cat-object` (already JSON) are exempt.
- Object IDs may be abbreviated to a unique prefix of at least 6 hex
  characters (with or without the `sha256:` prefix); ambiguous or unknown
  prefixes are user errors. Ref names take precedence over prefixes.
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
  [--actor agent] [--method cli] [--asserted-at <iso-utc>] \
  [--premise <assertion-id> ...]
```

`--premise` (repeatable, ADR-0013) records the assertions this belief
derives from; IDs accept unique prefixes and are expanded, sorted and
deduplicated. Every premise must reference an existing assertion. Fact
rows (`facts`, `show`, `dump`) expose the resulting `premises` list.

Rules:

- Shorthand and equivalent JSON must produce identical object IDs;
  `--asserted-at` defaults to now (UTC).
- `-` as the positional argument reads the JSON document from stdin
  (COG-030).
- The `assertion.claim` reference is filled from the written claim
  automatically; if present, it must match.
- Without `--commit`, does not create a thought; `--commit` is an ATOMIC
  micro-commit (COG-030/COG-035): the mindset is composed from the parent
  thought directly — the shared index is never touched — and published via
  the ref old-target check with retry, so parallel agents on one journal
  are safe by construction. Message defaults from the claim; a fact
  already active at HEAD returns `already_active` instead of an empty
  commit; a dirty index still refuses (it must not be invalidated).
- `--project <name>` (COG-037) sets the `project` qualifier — the
  shared-journal convention for separating projects.
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

### `cogit log --introduced-fact <fact-id> [<ref-or-id>]` / `--removed-fact`

Lists thoughts that introduced or removed a fact in the selected ancestry
(COG-019).

Rules:

- Exact fact ID only (abbreviations allowed); no semantic matching.
- *introduced*: fact present in the thought's mindset and in no parent.
- *removed*: fact absent from the thought's mindset and present in at
  least one parent.
- A re-introduced fact yields multiple events.
- Scope is the selected ancestry (default `HEAD`), not all refs.
- Mutually exclusive with each other and with `-g`.

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

### `cogit resolve <claim-id> (--keep <assertion-id> | --drop | --suggested)`

Resolves a recorded merge conflict for one claim.

Rules:

- `--keep` stages the chosen assertion; `--drop` stages none of them;
  `--suggested` applies the remembered resolution attached by merge
  (COG-020) and fails if none is stored.
- Every successful resolution is recorded into `rerere.json` for future
  suggestions.
- Removes the conflict entry from the index.
- Editing `index.json` by hand remains a legal fallback; the file is the
  authority.

### `cogit rerere [--forget <claim-or-fingerprint>]`

Lists remembered conflict resolutions, or forgets them (COG-020).

Rules:

- Fingerprints are orientation-invariant: the same rivalry conflicts to
  one fingerprint regardless of merge direction; a different base is a
  different conflict.
- Merge only SURFACES suggestions (in its output, `status`, and the index
  entry); applying one always requires an explicit `resolve --suggested`.
- `--forget` accepts a full fingerprint or a claim ID (abbreviations
  allowed for claims) and removes matching entries.

### `cogit blame-fact <fact-id> [<ref-or-id>]`

Returns the first introducing thought in selected ancestry.

Rules:

- Exact fact ID only.
- No semantic text matching.
- Linear traversal is acceptable in MVP.

### `cogit annotate <target-id> --message <text> [--namespace <ns>]`

Appends an annotation to a thought, assertion, or claim without rewriting
it (COG-018, ADR-0012).

Rules:

- Target must exist; its bytes are untouched.
- Default namespace is `notes`; a namespace is one valid ref segment.
- The annotation chains onto `refs/notes/<ns>` with an old-target check
  and a reflog entry.
- Suspected secrets in the body are rejected.

### `cogit annotations <target-id> [--namespace <ns>]`

Lists annotations for a target, newest first, across all namespaces by
default.

### `cogit log --annotations [<ref-or-id>]`

Walks thought ancestry like `log` and prints each thought's annotations
inline. Raw object view remains authoritative; annotations are display
overlay only.

### `cogit reflog-expire --keep <n> (--ref <name> | --all) [--dry-run]`

Trims reflogs to their newest N entries (COG-024, closes OQ-010).

Rules:

- Never runs implicitly; expiry is an explicit operator action (ADR-0009).
- `--keep` defaults from `[maintenance] reflogRetainEntries` when set;
  with neither, the command fails.
- `--dry-run` reports what would be dropped without changing anything.
- Trimming shrinks the recovery window — see the recovery playbook.

### `cogit count-objects`

Reports repository pressure metrics (COG-022, ADR-0006): loose objects by
type, corrupt-object count, disk bytes, head/anchor counts, reflog entries
and bytes, stale tmp files.

Rules:

- Never mutates the repository.
- Reads object headers only; unreadable objects are counted as corrupt,
  never fatal (this is a metrics scan, `verify` is the health authority).
- Warns when thresholds are exceeded; defaults follow ADR-0006 and can be
  overridden in a `[maintenance]` config section (`looseObjectsWarn`,
  `refsWarn`, `reflogEntriesWarn`).

### `cogit bisect-thought --good <id> --bad <id> --run <command>`

Binary-searches the first bad thought between a known-good ancestor and a
known-bad descendant (COG-021).

Rules:

- Probes never mutate the repository; the oracle gets `COGIT_THOUGHT`,
  `COGIT_MINDSET`, `COGIT_REPO` env vars.
- Oracle exit codes: `0` good, `125` skip/unknown, other `< 128` bad,
  `>= 128` aborts the bisect.
- Assumes a monotonic predicate along the topological candidate order
  (primary use: linear histories).
- Prints a replayable probe log; `--log <file>` also writes it to disk.
- When skip verdicts leave more than one possible first-bad thought, the
  remaining candidate range is reported and the command exits `1`
  (inconclusive), mirroring git-bisect's "could be any of" behavior.

### `cogit recap [<from>] [<to>]`

Belief-state digest for context recovery (COG-031): the thoughts between
two points plus the net fact changes with decoded claim content, and the
current position.

Rules:

- `<from>` accepts anchors, refs, and thought IDs; `<to>` defaults to
  `HEAD`.
- With no `<from>` (COG-036), recap starts from the NEWEST anchor, or the
  root thought when no anchors exist; the result reports `from_anchor`
  and `same_point` so a resuming agent never guesses.
- `<from>` must be an ancestor of `<to>`; otherwise the command fails and
  points to `diff`.
- Output is compact by design — the primary consumer is an agent resuming
  work.

### `cogit facts [<ref-or-thought>] [--subject S] [--predicate P] [--project N]`

Lists the active facts of a thought (default `HEAD`) with decoded claim
content (COG-028). Filters (COG-036/037) are exact URI matching — subject
accepts a trailing `*` prefix wildcard, `--project` matches the claim's
`project` qualifier. Not semantic search (ADR-0002).

Output per fact includes:

- short assertion ID (full with `--json`);
- claim kind, subject, predicate, object;
- confidence and source type;
- negations rendered unmistakably (COG-040): text shows `NOT <object>
  (negates <id>)`; JSON rows carry `negates` plus derived
  `negation: true`. A negation asserts the claim is FALSE — no
  replacement value is implied.

Rules:

- Output is sufficient to pick IDs for `blame-fact`, `remove-fact`, and
  `resolve` without `cat-object` chains.
- Works for branches, anchors (dereferenced), and detached thoughts.

### `cogit show [<ref-or-thought>]`

Prints the thought header (ID, parents, author, date, operation, message)
followed by its active facts, like `git show`.

### `cogit dump [<ref>] [--project N] [--since <anchor>] [--limit-log K]`

One-call reader surface (COG-042), JSON only: the active fact rows
(negation-explicit), the first introducer per active assertion
(blame-fact semantics), anchors, branches, the newest `K` log entries
(default 50), and a recap block against `--since` (default: the newest
anchor). Exists because a context-free reader otherwise needs 8-18
porcelain calls to assemble the same picture; `recap` remains the
delta-only read.

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
