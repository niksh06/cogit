# ADR-0010: Python stdlib reference prototype before the Rust implementation

created_datetime: 2026-07-02T12:00:00+03:00
updated_datetime: 2026-07-02T12:00:00+03:00
status: Accepted

## Context

ADR-0007 selected Rust for the Cogit implementation and a Cargo workspace
starting with `cogit-core`. That decision stands for the production codebase.

However, Phase 0 exit criteria were not met: the object format had no test
vectors, and three blocking open questions (canonicalization, test vectors,
ref+reflog atomicity) were unresolved. The fastest way to resolve them is a
complete executable reference implementation of the specs, because object
identity must be frozen by real bytes, not by prose.

The development environment for the first prototype has no Rust toolchain but
ships Python 3 with everything the object format needs in the standard
library: `hashlib` (SHA-256), `zlib`, `json`, and atomic filesystem
operations via `os`.

## Decision

Build a zero-dependency Python 3 stdlib prototype in `prototype/` that
implements the full MVP CLI contract (`docs/spec/cli-contract.md`) and the
object format (`docs/spec/object-format-v1.md`).

The prototype's roles:

1. Validate the specs by executing them end to end.
2. Generate and freeze the object-format test vectors
   (`prototype/vectors/object-vectors-v1.json`). Any future implementation,
   including the Rust one, must reproduce these object IDs byte-for-byte.
3. Serve as the reference implementation for ambiguity questions until the
   Rust implementation replaces it.

The Rust workspace direction from ADR-0007 is unchanged. The prototype is a
spec-validation artifact, not the production codebase. If prototype behavior
and spec text disagree, the spec is fixed first and the vectors are only
changed with an explicit ADR.

## Canonicalization decision (closes OQ-001 for the prototype)

Cogit canonical JSON is a JCS-inspired profile, made simpler and fully
cross-runtime by schema restrictions:

- UTF-8, no BOM, no insignificant whitespace.
- Object keys sorted by Unicode code point (equivalently: by UTF-8 bytes).
  This differs from RFC 8785's UTF-16 ordering only for keys containing
  non-BMP characters; schema keys are ASCII, so the difference cannot occur
  in required fields.
- Strings: mandatory escapes only (`\"`, `\\`, and control characters as
  `\b \t \n \f \r` or lowercase `\u00xx`); non-ASCII characters are emitted
  as raw UTF-8.
- Numbers: integers only, magnitude at most 2^53 - 1. Floats are forbidden
  by the object format, which removes the hardest part of RFC 8785.

## Ref+reflog atomicity decision (closes OQ-006 for the MVP)

Ref movement uses a lockfile protocol:

1. Create `<ref>.lock` with `O_CREAT|O_EXCL` (existing lock -> exit code 4).
2. Re-read the ref under the lock and compare with the expected old target;
   mismatch -> concurrent update error, lock removed, ref untouched.
3. Write the new target to the lockfile, fsync, atomically rename onto the ref.
4. Append the reflog line after the rename, while still holding the logical
   operation. A reflog append failure after a successful ref update is
   surfaced as an error (the ref stays moved; the operator is told the
   journal is incomplete).

This gives: no partial ref writes, no lost updates between concurrent
writers, and a journal that can lag but never lies about a movement that did
not happen.

## Consequences

Positive:

- Specs are now executable and tested; Phase 0 exit criteria can be met.
- Object identity is frozen by vectors before the Rust implementation starts.
- The prototype doubles as a usable local tool for early adopters.

Negative:

- Two implementations will briefly coexist; the prototype must not grow
  features ahead of the specs.
- Python performance is irrelevant to the MVP but must not be used to judge
  maintenance-layer thresholds (ADR-0006 thresholds are model-level, not
  runtime-level).

## References

- `docs/adr/0007-rust-workspace-and-first-slice.md`
- `docs/spec/object-format-v1.md`
- `docs/spec/cli-contract.md`
- `prototype/vectors/object-vectors-v1.json`
