# Open Questions

created_datetime: 2026-05-26T21:40:00+03:00
updated_datetime: 2026-07-02T12:00:00+03:00
status: Draft

## Purpose

This document collects unresolved decisions so implementation does not hide assumptions in code.

## Blocking Before MVP Implementation

### OQ-002: Method object schema

Question: What exact fields should assertion `method` contain?

Why it matters: method can easily become a trace/event schema rather than provenance metadata.

Decision so far: `method` is an object with a required `type` string; other fields stay minimal in MVP. The prototype enforces only `type`.

Status: Open (narrowed)

### OQ-004: License and open-source posture

Moved to Closed Questions as CQ-014 (Apache-2.0, decided 2026-07-02).

## Post-MVP Questions

### OQ-007: Notes namespaces

Moved to Closed Questions as CQ-016 (typed namespaces, ADR-0012, 2026-07-02).

### OQ-008: Rerere conflict fingerprint

Moved to Closed Questions as CQ-017 (COG-020, 2026-07-02).

### OQ-009: Bisect oracle contract

Moved to Closed Questions as CQ-015 (implemented by COG-021, 2026-07-02).

### OQ-010: Reflog retention policy

Moved to Closed Questions as CQ-018 (COG-024, 2026-07-02).

### OQ-011: Maintenance thresholds

Question: What object count, ref count, or latency thresholds should trigger pack/index work?

Status: Deferred until measured pressure.

### OQ-012: Trust model

Question: What signature format, key identity, and verification policy should be used for imported thoughts?

Status: Deferred

### OQ-013: Secret detection implementation

Question: How should MVP detect suspected secrets well enough to reject writes?

Decision so far (narrowed by COG-023): three local layers — known-shape
patterns, credential-in-URL/assignment shapes, and an entropy heuristic for
opaque tokens with explicit false-positive guards (object IDs, hex, code
identifiers must pass). Still open: pluggable scanner-grade detection
(gitleaks-class rulesets) for enterprise use.

Status: Deferred (narrowed)

## Closed Questions

### CQ-018: Reflog retention policy (was OQ-010)

Answer: Retention is entry-count based and ALWAYS explicit in MVP:
`cogit reflog-expire --keep <n> (--ref <name> | --all) [--dry-run]` trims
each reflog to its newest N entries under the standard lockfile protocol.
`--keep` may default from `[maintenance] reflogRetainEntries`, but no
expiry ever runs implicitly — trimming the journal shrinks the recovery
window (see recovery playbook), so it stays an operator action per
ADR-0009. Time-based retention is future work if entry counts prove the
wrong unit.

Closed by:

- `docs/spec/cli-contract.md`
- `docs/recovery-playbook.md`

### CQ-017: Rerere conflict fingerprint (was OQ-008)

Answer: SHA-256 over the canonical JSON of the normalized conflict shape
`{claim, sides, base}`, where `claim` is the negation-group root, both
side lists are sorted internally and against each other (merge orientation
does not matter), and `base` is included so the same rivalry over a
different base is a different conflict. Resolutions are recorded on every
`resolve` into local `rerere.json`; merge surfaces suggestions but never
applies them without an explicit `resolve --suggested`.

Closed by:

- `issues/COG-020.md`
- `docs/spec/cli-contract.md`

### CQ-016: Notes namespaces (was OQ-007)

Answer: Typed namespaces. Each namespace is one append-only annotation
chain under `refs/notes/<namespace>` (default `notes`); the namespace is
recorded inside every annotation object so chain entries cannot be
silently re-homed. One-ref-for-everything was rejected because audit and
eval overlays have different consumers and retention expectations.

Closed by:

- `docs/adr/0012-annotations.md`

### CQ-015: Bisect oracle contract (was OQ-009)

Answer: `cogit bisect-thought --good <id> --bad <id> --run <command>`.
Probes are non-mutating: the oracle receives `COGIT_THOUGHT`,
`COGIT_MINDSET`, and `COGIT_REPO` env vars and inspects state through
read-only commands. Exit codes are git-bisect compatible: 0 good, 125
skip/unknown, any other code below 128 bad, 128+ aborts. Skipped
candidates near the answer are reported as suspects; an all-skipped range
is inconclusive. A replayable probe log is printed and optionally written
with `--log`.

Closed by:

- `issues/COG-021.md`
- `docs/spec/cli-contract.md`

### CQ-014: License (was OQ-004)

Answer: Apache-2.0 — permissive with a patent grant, the standard choice
for infrastructure tooling; safe for a future hosted/enterprise layer.
Contribution model: ticket-first (BACKLOG.md), invariants are the review
bar, object-format changes require an ADR plus regenerated vectors.

Closed by:

- `LICENSE`
- `README.md` (License and contributions)
- owner decision, 2026-07-02

### CQ-010: Canonicalization profile (was OQ-001)

Answer: Cogit uses a JCS-inspired canonical JSON profile: UTF-8, keys sorted
by Unicode code point, minimal escaping, integers only (|n| <= 2^53 - 1),
floats forbidden. The Rust crate choice remains per-component, but the
profile is frozen by test vectors, so any implementation must match bytes,
not a library default.

Closed by:

- `docs/adr/0010-python-prototype-slice.md`
- `docs/spec/object-format-v1.md`

### CQ-011: Test vectors (was OQ-003)

Answer: Frozen vectors for claim, assertion, mindset, thought, and anchor
live in `prototype/vectors/object-vectors-v1.json`, generated and verified by
the reference prototype. Vectors change only through an explicit ADR.

Closed by:

- `docs/adr/0010-python-prototype-slice.md`
- `prototype/vectors/object-vectors-v1.json`

### CQ-012: Naming compatibility (was OQ-005)

Answer: Yes. The CLI keeps fact language (`add-fact`, `remove-fact`,
`blame-fact`) while the storage model uses claim/assertion. Fact is defined
as an active assertion about a claim; command output shows both claim and
assertion IDs so the mapping stays visible.

Closed by:

- `docs/glossary.md`
- `docs/spec/cli-contract.md`

### CQ-013: Ref and reflog atomicity strategy (was OQ-006)

Answer: Lockfile protocol: create `<ref>.lock` exclusively, re-check the
expected old target under the lock, write + fsync + atomic rename, then
append the reflog line. Reflog append failure after a successful ref move is
surfaced as an error rather than rolled back.

Closed by:

- `docs/adr/0010-python-prototype-slice.md`

### CQ-001: Is Cogit retrieval memory?

Answer: No. Cogit is reasoning provenance and cognitive VCS. Retrieval systems are external layers.

Closed by:

- `docs/adr/0002-provenance-not-retrieval-memory.md`
- `docs/non-goals.md`

### CQ-002: First implementation language and shape

Answer: Rust. Use a Cargo workspace from the start, but the first implementation slice is `cogit-core` object store.

Closed by:

- `docs/adr/0007-rust-workspace-and-first-slice.md`

### CQ-003: Claim and assertion model

Answer: Use structured typed claims and assertions. A claim is the stable proposition; assertions carry source, confidence, time, actor, and method. Product "fact" is shorthand for an active assertion about a claim.

Closed by:

- `docs/adr/0008-claim-assertion-model.md`
- `docs/spec/claim-assertion-examples.md`

### CQ-004: Confidence representation

Answer: Required integer `confidence_bps` from `0` to `10000`.

Closed by:

- `docs/adr/0008-claim-assertion-model.md`

### CQ-005: Anchor representation

Answer: Anchor object plus ref. The ref makes lookup convenient; the object preserves audit metadata.

Closed by:

- `docs/adr/0001-cogit-kiss-filesystem-architecture.md`

### CQ-006: Thought parent ordering

Answer: Use Git-like semantic parent order. For merge thoughts, `parents[0]` is current/ours and `parents[1]` is merged/theirs. Merge metadata records base/ours/theirs explicitly.

Closed by:

- `docs/adr/0008-claim-assertion-model.md`

### CQ-007: Negated claims and removal

Answer: A negated claim explicitly links to the original via `negates`. Activating a negated claim requires removing the original active assertion with reason `refuted`.

Closed by:

- `docs/adr/0008-claim-assertion-model.md`

### CQ-008: Secrets policy

Answer: Secrets and sensitive data are forbidden in Cogit. Suspected secret writes are rejected, not redacted and written.

Closed by:

- `docs/adr/0009-agent-autonomy-and-destructive-operations.md`

### CQ-009: Agent autonomy and destructive operations

Answer: The agent may autonomously run append-oriented and inspection operations such as init/add/commit/branch/checkout/verify. Destructive operations are constrained: dirty-index checkout blocks in MVP; safe repair is limited to empty index recreation and tmp cleanup; prune is not in MVP.

Closed by:

- `docs/adr/0009-agent-autonomy-and-destructive-operations.md`
