# ADR-0004: Object integrity and ref atomicity

created_datetime: 2026-05-26T21:28:00+03:00
updated_datetime: 2026-05-26T21:28:00+03:00
status: Proposed

## Context

Cogit's MVP stores immutable objects as zlib-compressed canonical JSON preimages addressed by SHA-256. That gives a strong foundation, but content addressing is only useful if reads verify object integrity and mutable refs are updated safely.

Git treats objects and refs differently:

- Objects are immutable and validated by content hash.
- Refs are mutable and protected by lockfiles, old-object checks, and transactions.

Cogit should copy this boundary from the start.

## Decision

Cogit object reads verify integrity:

- decompress object body;
- parse `<type> <size>\0<canonical-json>`;
- verify declared size;
- recompute SHA-256 over the full preimage;
- compare the computed hash to the storage path.

Cogit object writes enforce immutability:

- validate object schema before writing;
- write to a temporary file;
- publish with atomic rename;
- if the target object path already exists, compare content and reject same-path/different-content collisions.

Cogit ref updates use old-object checks:

- update a ref only if its current value matches the expected old value;
- write refs through lockfiles or equivalent atomic replacement;
- treat objects written before a failed ref update as harmless unreachable objects.

Cogit includes `verify` in the MVP.

## Rationale

Hashing is an integrity mechanism, not a trust mechanism. It detects corruption, malformed objects, and path/content mismatch, but it does not prove that an imported thought came from a trusted actor.

Ref atomicity is a separate problem. Without old-object checks, two local agents can both commit from the same parent and silently lose one branch tip update.

## MVP Verify Checks

`cogit verify` should report:

- corrupt zlib body;
- malformed object header;
- declared size mismatch;
- hash-path mismatch;
- invalid JSON;
- unknown object type;
- missing required fields;
- invalid refs;
- missing parent, mindset, or fact objects;
- dangling thoughts reachable only from reflog or not reachable at all.

The MVP reports problems but does not repair them.

## Consequences

Positive:

- Corruption is caught early and locally.
- Concurrent ref updates fail explicitly instead of silently losing history.
- The repository becomes safe enough for local agent experiments and future sync.

Negative:

- Every object read pays a small verification cost.
- Ref update code is more complex than plain file writes.
- Recovery remains manual until dedicated repair commands exist.

## References

- `git/Documentation/gitformat-loose.adoc`
- `git/object-file.c`
- `git/lockfile.h`
- `git/Documentation/git-update-ref.adoc`
- `git/fsck.h`
- `git/Documentation/git-fsck.adoc`
