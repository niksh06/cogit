# Test Strategy

created_datetime: 2026-05-26T21:40:00+03:00
updated_datetime: 2026-05-26T21:40:00+03:00
status: Draft

## Purpose

This document defines how Cogit should be tested so implementation does not drift from the provenance model.

## Test Layers

### Unit Tests

Use for pure functions and small file operations:

- canonical JSON serialization;
- object preimage creation;
- SHA-256 object ID calculation;
- schema validation;
- ref name validation;
- reflog line parsing;
- mindset set diff;
- first-introducer traversal on small graphs.

### Property Tests

Use for invariants:

- same canonical object always hashes to same ID;
- object read after write returns the same object;
- key ordering does not change canonical bytes;
- invalid confidence values are rejected;
- duplicate facts in a mindset are rejected or normalized consistently;
- ref update with wrong old target never succeeds.

### Integration Tests

Use for repository workflows:

- init repository;
- add fact;
- commit thought;
- branch and checkout;
- detached checkout;
- diff two thoughts;
- merge non-conflicting branches;
- merge conflicting branches;
- blame fact;
- log thought history;
- log reflog history;
- verify healthy repository.

### Failure Tests

Use for known dangerous cases:

- corrupt zlib body;
- malformed object header;
- hash-path mismatch;
- missing parent thought;
- missing mindset;
- missing fact;
- invalid ref;
- interrupted object write;
- interrupted ref update;
- concurrent ref update;
- malformed index;
- unresolved merge conflict.

### Golden Tests

Use stable fixtures for:

- object-format test vectors;
- CLI text output;
- JSON output when `--json` exists;
- verify error messages.

## MVP Test Matrix

| Area | Required Tests |
| --- | --- |
| Object format | canonicalization, hash, read/write, corruption |
| Repository layout | init, required files, invalid layout |
| Refs | symbolic HEAD, detached HEAD, old-target checks |
| Reflog | append, parse, `log -g` |
| Index | stage, clear, conflict blocks commit |
| Thought commit | mindset creation, parent links, ref update |
| Diff | added, removed, unchanged facts |
| Merge | clean merge, conflict merge |
| Blame | first introducer, not last modifier |
| Verify | healthy, corrupted, missing links |

## Test Data Principles

- Prefer small repositories created in temporary directories.
- Do not depend on wall-clock ordering; inject timestamps.
- Do not depend on host-specific paths.
- Keep object fixtures human-readable.
- Keep corruption fixtures explicit and isolated.

## Definition Of Done For Implementation

A feature is not done until:

- unit tests cover its core logic;
- an integration test covers its repository behavior;
- failure behavior is tested when the feature mutates state;
- `verify` passes after successful mutation;
- docs mention user-visible behavior.

## What Not To Test In MVP

- Network sync.
- Signatures.
- Packfiles.
- Semantic retrieval.
- UI rendering.
- Enterprise retention policy.
