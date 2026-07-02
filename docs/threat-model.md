# Threat Model

created_datetime: 2026-05-26T21:40:00+03:00
updated_datetime: 2026-05-27T09:41:00+03:00
status: Draft

## Purpose

This document identifies risks Cogit should account for while staying focused on local provenance. MVP mitigates corruption and accidental misuse; it does not provide full enterprise security.

## Assets

- Immutable object history.
- Ref and HEAD state.
- Reflog operational history.
- Index staged facts and conflicts.
- Fact source metadata.
- Operator trust in audit output.

## Actors

- Local agent process.
- Human operator.
- Another local agent process.
- Malicious imported repository.
- Future remote peer.
- Local filesystem or hardware failure.

## Trust Boundaries

### Local Filesystem

MVP trusts local filesystem permissions but verifies object integrity.

### Imported Objects

Imported objects are untrusted until future quarantine and signature policy exists.

### Source Metadata

`source` is a claim recorded by the agent. It is not cryptographic proof.

### Reflog

Reflog is local operational evidence. It is mutable filesystem data, not immutable object history.

## Threats And Mitigations

### Corrupt Object Body

Risk: bit rot or interrupted write makes object unreadable.

Mitigation:

- zlib decode errors;
- size checks;
- SHA-256 hash-path verification;
- `verify`.

### Hash-Path Mismatch

Risk: object stored at one path contains different bytes.

Mitigation:

- verify hash on read;
- reject same-path different-content writes.

### Malicious Imported History

Risk: imported objects contain fake authors, poisoned sources, or broken graph links.

MVP mitigation:

- treat imports as out of scope;
- `verify` before use.

Future mitigation:

- quarantine;
- signature policy;
- import hooks.

### Lost Ref Update

Risk: two agents commit concurrently and one silently overwrites the other branch tip.

Mitigation:

- old-object checks;
- lockfiles;
- explicit concurrent update errors.

### Reflog Tampering

Risk: local actor edits reflog to hide operational history.

MVP mitigation:

- none beyond filesystem permissions.

Future mitigation:

- signed reflog entries;
- append-only storage;
- external audit export.

### Prompt Or Tool Source Poisoning

Risk: agent records a false fact with plausible source metadata.

Mitigation:

- source metadata preserved for audit;
- confidence represented explicitly;
- later notes/evals can flag facts;
- Cogit does not equate provenance with truth.

### Private Data Leakage

Risk: facts, messages, sources, or reflogs contain secrets or personal data.

MVP mitigation:

- secrets and sensitive data are forbidden;
- suspected secret writes are rejected;
- local-only storage;
- no automatic sync.

Future mitigation:

- encrypted repositories;
- export policy;
- retention controls.

### Semantic Retrieval Confusion

Risk: users trust retrieval results as if they were provenance.

Mitigation:

- non-goal docs;
- exact-ID blame semantics;
- raw object view authoritative.

### Unsafe Automatic Repair

Risk: repair tool rewrites history or invents missing objects.

Mitigation:

- MVP `verify` reports only;
- recovery playbook forbids in-place object edits.

## MVP Security Boundaries

MVP provides:

- content integrity checks;
- schema validation;
- ref update safety;
- local recovery evidence.
- rejection of suspected secret writes.

MVP does not provide:

- actor authentication;
- encryption;
- secure deletion;
- remote trust;
- tamper-proof logs;
- compliance retention.
- reliable automated secret classification.

## Enterprise Questions

- Should thoughts and anchors be signed?
- Should reflogs be signed or exported to an external append-only log?
- How should secrets in facts be redacted?
- What retention policy applies to facts and reflogs?
- How should imported repositories be quarantined?
