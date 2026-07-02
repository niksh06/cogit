# ADR-0003: Dual-ledger provenance

created_datetime: 2026-05-26T21:28:00+03:00
updated_datetime: 2026-05-26T21:28:00+03:00
status: Proposed

## Context

Git keeps immutable content history and mutable operational history separate:

- Objects and commits describe reachable project states.
- Refs describe current branch tips.
- Reflogs describe local movements of refs.

Cogit needs the same separation. A thought graph can show what was committed and how thoughts descend from each other, but it cannot by itself answer operational questions such as "when did this branch stop pointing at that thought?" or "what did the agent check out before it failed?"

## Decision

Cogit uses a dual-ledger model:

1. Immutable content ledger: `fact`, `mindset`, `thought`, and `anchor` objects in `.cogit/objects`.
2. Mutable pointer journal: `HEAD`, `refs/**`, and append-only local logs in `.cogit/logs/**`.

Every operation that moves `HEAD` or a branch ref appends a reflog-style entry.

The minimal log entry contains:

- previous target;
- new target;
- timestamp;
- actor or agent ID;
- operation name;
- human-readable reason.

Example:

```text
sha256:old sha256:new 2026-05-26T18:00:00Z planner checkout: switch to hypothesis-a
```

## Rationale

The immutable object graph is the source of truth for committed reasoning state. The mutable pointer journal is the source of truth for how the local agent navigated that graph.

This keeps recovery possible even when a branch is reset or a detached reasoning path is abandoned. It also avoids overloading `thought` objects with operational events that are not part of the reasoning state itself.

## Consequences

Positive:

- Recovery can use `log -g` even when objects become unreachable from refs.
- Audit can distinguish "the agent believed X" from "the agent moved active context to Y."
- Detached speculation becomes safer because abandoned thoughts remain discoverable until garbage collection.

Negative:

- Reflog storage grows over time.
- Reflogs are local operational history, not portable shared provenance.
- Retention and pruning policy must be defined before long-running production use.

## Future Work

- Notes-like annotations for post-hoc review and eval results.
- Reflog expiration policy.
- Recovery commands for dangling thoughts.

## References

- `git/Documentation/git-reflog.adoc`
- `git/Documentation/gitrepository-layout.adoc`
- `git/Documentation/revisions.adoc`
- `git/Documentation/user-manual.adoc`
