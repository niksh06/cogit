# ADR-0012: Append-only annotations over immutable objects

created_datetime: 2026-07-02T16:00:00+03:00
updated_datetime: 2026-07-02T16:00:00+03:00
status: Accepted

## Context

Post-hoc review needs to attach information to committed history — human
review verdicts, eval results, policy flags — without changing object IDs
(US-017, invariant 19: overlays must be explicit; raw object view stays
authoritative). Git solves this with notes; Cogit needs an equivalent that
reuses its own machinery instead of inventing a parallel store.

OQ-007 asked whether annotations live under one ref or typed namespaces.

## Decision

Add a sixth object type, `annotation`, to object format v1:

```json
{
  "type": "annotation",
  "target": "sha256:<annotated-object-id>",
  "namespace": "audit",
  "body": "Root cause confirmed by regression test.",
  "author": "reviewer",
  "created_at": "2026-07-02T16:00:00Z",
  "parents": []
}
```

- `target` may reference a thought, assertion, or claim; it must exist at
  write time and is never modified.
- Annotations in a namespace form an append-only chain: `parents` holds the
  previous chain tip (empty for the first), and `refs/notes/<namespace>`
  points to the newest annotation. Appending uses the standard lockfile +
  old-target check + reflog machinery.
- Namespaces are typed (closes OQ-007): `refs/notes/<namespace>`, one chain
  per namespace, default namespace `notes`. The namespace is also recorded
  in the object so a chain entry cannot be silently re-homed.
- Annotations are immutable; corrections are new annotations. Deletion is
  out of scope for MVP.
- Reading is a linear chain walk filtered by target — consistent with the
  MVP linear-walk philosophy (ADR-0006); indexes are a later layer.

CLI: `cogit annotate <target> --message <text> [--namespace <ns>]`,
`cogit annotations <target>`, and `cogit log --annotations`.

## Vectors

The five existing test vectors are frozen and unchanged. This ADR
authorizes appending ONE new vector for `annotation` to
`prototype/vectors/object-vectors-v1.json`.

## Rationale

Reusing content-addressed objects + refs + reflogs gives annotation history
versioning, atomicity, and operational provenance for free, and keeps the
whole repository inspectable by the same rules. A separate side-store would
create a second source of truth and violate the KISS architecture.

Chain-per-namespace (rather than a map object per git notes trees) is the
smallest model that satisfies "versioned or append-only" — O(n) target
lookup is acceptable at MVP scale and has a clear index hook later.

## Consequences

Positive:

- Review, eval, and policy flags attach to history without rewrites.
- `verify` extends naturally: chain parents, targets, and namespace
  consistency are ordinary link checks.

Negative:

- Target lookup is O(chain length) until a notes index exists.
- Cross-namespace queries walk every notes ref.

## References

- `issues/COG-018.md`
- `docs/spec/object-format-v1.md`
- `user_stories/agent-user-stories.md` (US-017)
