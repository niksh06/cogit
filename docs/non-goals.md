# Non-Goals

created_datetime: 2026-05-26T21:40:00+03:00
updated_datetime: 2026-05-26T21:40:00+03:00
status: Draft

## Purpose

This document prevents scope drift. Cogit can grow, but the MVP must stay a local provenance system for agent reasoning.

## Product Non-Goals

### Cogit Is Not Retrieval Memory

Cogit does not decide what context should be retrieved for the next model call.

Out of scope:

- embeddings;
- vector search;
- reranking;
- semantic memory extraction;
- context assembly;
- chat-history compression.

### Cogit Is Not A Vector Database

Cogit stores content-addressed provenance objects, not nearest-neighbor indexes.

### Cogit Is Not A Chat Log

Cogit records committed reasoning state. It does not automatically store every prompt, token, or tool event.

### Cogit Is Not A General Event Store

Cogit is not intended to replace observability systems, traces, metrics, or application logs.

### Cogit Is Not A Database Product

MVP should not introduce RocksDB, LMDB, SQLite, Postgres, or a daemon unless a later ADR proves measured need.

### Cogit Is Not A Distributed Sync Protocol

MVP is local-first. Remotes, fetch, push, quarantine, signatures, and partial sync are future layers.

### Cogit Is Not Enterprise Compliance In MVP

MVP does not provide:

- RBAC;
- encryption;
- key management;
- secure deletion;
- legal hold;
- SOC 2 controls;
- HIPAA controls;
- audit export guarantees.

### Cogit Does Not Rewrite History By Default

Rebase-like operations, replace refs, grafts, and overlays are out of scope unless explicitly designed with raw view and audit safeguards.

### Cogit Does Not Resolve Truth

Cogit can show where a fact came from and when it entered the graph. It does not prove the fact is true.

## Technical Non-Goals For MVP

- Packfiles.
- Commit-graph or thought-graph indexes.
- Packed refs or reftable.
- Semantic delta compression.
- Background maintenance scheduler.
- Signed objects.
- Quarantine.
- Notes.
- Rerere.
- Bisect.
- Browser or web UI.

## How To Challenge A Non-Goal

A non-goal can move into scope only with:

- concrete user story;
- measured pain or clear product requirement;
- ADR describing trade-offs;
- migration plan;
- tests and recovery behavior.
