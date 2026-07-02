# ADR-0007: Rust workspace and first implementation slice

created_datetime: 2026-05-27T09:41:00+03:00
updated_datetime: 2026-07-02T21:00:00+03:00
status: Accepted — implemented as `crates/cogit-core` + `crates/cogit-cli`
(COG-013): full command parity with the reference prototype, frozen vectors
reproduced byte-for-byte, cross-runtime interop proven by
`tools/interop-test.sh`.

## Context

Cogit needs deterministic object storage, careful filesystem operations, and strong tests around corruption and atomic updates. The implementation language should make those invariants explicit without pulling the MVP into a service architecture.

## Decision

Implement Cogit in Rust.

Create a Cargo workspace from the start, but the first code slice contains only `cogit-core`.

Initial workspace direction:

```text
crates/
  cogit-core/
```

Future crates may include:

```text
crates/
  cogit-cli/
  cogit-testkit/
```

The first implementation slice is the object store:

- canonical JSON encoding;
- object preimage construction;
- SHA-256 object IDs;
- zlib object storage;
- object read/write;
- schema validation;
- object-level `verify` checks.

CLI, refs, index, reflog, merge, and blame come after the object store is stable.

## Dependency Policy

Dependencies are decided per component by ADR or implementation note.

Accepted direction:

- use reliable Rust crates when they reduce risk;
- do not chase zero dependencies for its own sake;
- avoid heavy storage, database, async runtime, or daemon dependencies in MVP;
- freeze canonicalization behavior with test vectors before trusting object IDs.

## Rationale

Rust is a good fit for local storage primitives, explicit error handling, and testable parsing. Starting with a workspace keeps future CLI/testkit structure clean without forcing premature crate boundaries.

Object storage is the riskiest foundation. If object IDs or canonicalization are wrong, every later feature becomes unstable.

## Consequences

Positive:

- Strong type boundaries for object schemas and errors.
- Good fit for corruption tests and filesystem invariants.
- Clean path to CLI and testkit crates.

Negative:

- Slower iteration than a Python prototype.
- Need to choose canonical JSON and compression crates carefully.
- Agent integrations may need bindings or CLI wrappers later.

## Acceptance Criteria

- Workspace can build with only `cogit-core`.
- `cogit-core` can produce deterministic object IDs from test vectors.
- Object read verifies hash and schema.
- Corruption fixtures fail predictably.

## References

- `docs/spec/object-format-v1.md`
- `docs/test-strategy.md`
- `docs/invariants.md`
