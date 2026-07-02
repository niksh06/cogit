# Recovery Playbook

created_datetime: 2026-05-26T21:40:00+03:00
updated_datetime: 2026-05-27T09:41:00+03:00
status: Draft

## Purpose

This playbook describes expected failure modes and safe recovery paths. MVP Cogit should prefer explicit diagnostics over automatic repair.

## General Recovery Rules

- Run `cogit verify` first.
- Do not edit object files in place.
- Prefer creating new refs to preserve recovered thoughts.
- Keep corrupt files aside before deleting anything.
- Treat manual repair as an operator action, not normal agent behavior.

## Corrupt Object

Symptoms:

- `cat-object` fails.
- `verify` reports zlib error, malformed header, size mismatch, or hash-path mismatch.

Recovery:

1. Record the object ID and path from `verify`.
2. Identify referencing thoughts or mindsets.
3. If the object is a fact and the original source still exists, recreate the fact from canonical data.
4. If the recreated object has the same ID, replace the corrupt file through normal object write.
5. If the object is a thought or mindset, do not hand-edit unless no other recovery path exists.

Stop condition:

- If the replacement produces a different ID, it is not the same object.

## Missing Fact

Symptoms:

- `verify` reports a mindset referencing a missing fact.

Recovery:

1. Inspect the mindset ID.
2. Inspect thoughts pointing to that mindset.
3. Locate the fact source from external logs or documents if available.
4. Recreate the fact only if canonical content is known.
5. If not known, preserve the broken state and create a new corrective thought.

## Missing Mindset

Symptoms:

- `verify` reports a thought referencing a missing mindset.

Recovery:

1. Identify the thought.
2. Check whether the missing mindset exists in backup or alternate storage.
3. If unavailable, do not rewrite the thought.
4. Create a new thought explaining the breakage if the branch can still proceed from an earlier parent.

## Missing Parent Thought

Symptoms:

- `verify` reports a thought parent that cannot be found.

Recovery:

1. Search reflog for the parent ID.
2. Check backups.
3. If parent is unavailable, mark repository as incomplete.
4. Do not invent a replacement parent.

## Failed Ref Update After Object Write

Symptoms:

- Commit command reports concurrent update.
- New objects exist but current branch did not move.

Recovery:

1. Run `status`.
2. Inspect the current branch target.
3. Decide whether to retry commit on top of the new target or create a side branch to the unreachable thought.
4. Do not delete unreachable objects immediately.

## Detached Thought Recovery

Symptoms:

- Agent was in detached HEAD and lost the thought ID.

Recovery:

1. Run `cogit log -g HEAD`.
2. Find the previous detached target.
3. Run `cogit checkout <thought-id>`.
4. Optionally create `cogit branch recovered/<name> <thought-id>`.

## Bad Merge

Symptoms:

- Merge result contains wrong facts.
- Operator decides conflict resolution was unsafe.

Recovery:

1. Use reflog to find pre-merge branch target.
2. Create a recovery branch from pre-merge thought.
3. Do not rewrite the merge thought.
4. Commit a corrective thought or abandon the merge branch.

## Interrupted Commit

Symptoms:

- Temporary files remain.
- Objects may exist but ref did not move.
- Index may still contain staged facts.

Recovery:

1. Run `verify`.
2. Run `status`.
3. If ref did not move, retry commit or clear index explicitly.
4. Remove stale temp files only after confirming no process owns them.

## Malformed Index

Symptoms:

- `status` or `commit-thought` cannot parse `index.json`.

Recovery:

1. Copy malformed `index.json` aside.
2. Recreate an empty index.
3. Re-stage facts if they are known.
4. Do not infer staged facts from live context unless operator approves.

## Dirty Index Checkout

Symptoms:

- Checkout is requested while `index.json` contains staged facts, removals, or conflicts.

Recovery:

1. Commit the staged state, clear the index explicitly, or keep working on the current branch.
2. Do not auto-stash in MVP.
3. Retry checkout only after `status` shows an empty index.

## Concurrent Writers

Symptoms:

- Lock failure.
- Old-target mismatch.

Recovery:

1. Re-read current HEAD and branch target.
2. Recompute intended operation.
3. Retry with new expected old target if still valid.
4. Create a side branch when in doubt.

## Manual Repair Boundaries

Allowed:

- recreate missing fact from exact source;
- create new branch pointing at known thought;
- recreate empty index;
- remove stale temp files;
- add corrective thought.
- create a recovery branch from reflog.

Forbidden:

- edit immutable object bytes in place;
- change an existing thought parent;
- silently rewrite refs without reflog;
- pretend a different hash is the same object;
- auto-resolve semantic conflicts without recording the resolution.
- prune unreachable objects in MVP.
- checkout across a dirty index.

## Expired Reflog

Symptoms:

- `cogit log -g` shows fewer entries than expected.
- A recovery target mentioned in old notes is no longer in the reflog.

Prevention and recovery:

1. `cogit reflog-expire` never runs implicitly; check who ran it and with
   which `--keep` value.
2. Use `--dry-run` before any real expiry.
3. Expiry removes JOURNAL entries, not objects: a lost thought ID may
   still be recoverable from anchors, branches, annotations, or an
   operator's notes, and `cogit verify` will list dangling thoughts.
4. Keep `[maintenance] reflogRetainEntries` comfortably larger than your
   longest expected recovery window.
