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

Question: Which license and contribution model should Cogit use?

Why it matters: open-source adoption depends on license clarity before publication.

Status: Open

## Post-MVP Questions

### OQ-007: Notes namespaces

Question: Should annotations live under one notes ref or typed namespaces such as `refs/notes/audit` and `refs/notes/eval`?

Status: Deferred

### OQ-008: Rerere conflict fingerprint

Question: What normalized shape identifies repeated semantic conflicts?

Status: Deferred

### OQ-009: Bisect oracle contract

Question: What exit codes and inputs should `bisect-thought` use for agent quality checks?

Status: Deferred

### OQ-010: Reflog retention policy

Question: How long should local operational history be retained?

Status: Deferred

### OQ-011: Maintenance thresholds

Question: What object count, ref count, or latency thresholds should trigger pack/index work?

Status: Deferred until measured pressure.

### OQ-012: Trust model

Question: What signature format, key identity, and verification policy should be used for imported thoughts?

Status: Deferred

### OQ-013: Secret detection implementation

Question: How should MVP detect suspected secrets well enough to reject writes?

Decision so far: secrets are forbidden; suspected secret writes are rejected. Detection details remain open.

Status: Deferred

## Closed Questions

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
