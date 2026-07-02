# Cogit Backlog

created_datetime: 2026-07-02T12:00:00+03:00
updated_datetime: 2026-07-02T13:30:00+03:00

Ticket IDs are stable. Specs for open tickets live in `issues/<ID>.md`.
Story references point to `user_stories/agent-user-stories.md`.

## Done

| ID | Title | Refs | Verified by |
| --- | --- | --- | --- |
| COG-001 | Phase 0 docs: PRD, ADR-0001..0009, specs, invariants, threat model | roadmap Phase 0 | design review 2026-05-27 |
| COG-002 | Doc refactor: PRD↔spec drift (fact→claim/assertion, bps, layout), parents order contradiction, anchor ref mode | ADR-0008, CQ-005/006 | cross-doc review 2026-07-02 |
| COG-003 | ADR-0010: Python stdlib reference prototype; canonicalization + ref/reflog atomicity decisions (closed OQ-001/003/005/006) | ADR-0010 | — |
| COG-004 | Object store: canonical JSON, SHA-256 preimage, zlib, fanout, atomic writes, full read verification | US-002, US-003 | `prototype/tests/test_canonical.py`, `test_objects.py`, `test_store.py` |
| COG-005 | Frozen object-format test vectors v1 | CQ-011 | `prototype/tests/test_vectors.py` |
| COG-006 | Refs, HEAD, lockfile old-target checks, reflogs | US-006, US-007 | `prototype/tests/test_refs.py` |
| COG-007 | Index, staging, remove-fact with reasons, commit-thought | US-004, US-005 | `prototype/tests/test_repo.py` |
| COG-008 | Branch/checkout/detach, log, log -g, diff, status, anchors | US-008..US-011, US-015, US-016 | `prototype/tests/test_repo.py`, `test_cli.py` |
| COG-009 | Conservative claim-level merge with conflicts, resolve, merge thoughts | US-012 | `test_repo.py` merge tests, `test_cli.py::test_merge_conflict_flow` |
| COG-010 | blame-fact (first introducer), verify (corruption/missing links/dangling), CLI with contract exit codes | US-013, US-014 | `test_repo.py`, `test_cli.py` (65 tests green 2026-07-02) |
| COG-017 | Repo housekeeping: init product VCS, exclude `git/` reference tree | `issues/COG-017.md` | initial commit `4585548`; tree clean, `git/`/`.venv` untracked, 59 files, 2026-07-02 |
| COG-011 | "Why not plain Git?" positioning ADR | ADR-0011 | doc review; README links it |
| COG-014 | Atomic symbolic-HEAD updates (old-content check on HEAD writes) | `issues/COG-014.md` | `test_refs.py` HEAD race/lock tests (exit 4), spec updated |
| COG-015 | Negation-aware merge and commit checks (invariants 24–25) | `issues/COG-015.md` | `test_repo.py` negation tests; verify warns `contradictory-mindset` |
| COG-012 | Integration experiment: Claude Code hook + CLI dogfood session | `issues/COG-012.md` | hook smoke-tested (incl. secret rejection); findings report 2026-07-02; spawned COG-027/028, re-prioritized COG-025 |

## Open — next

| ID | Title | Priority | Refs |
| --- | --- | --- | --- |
| COG-013 | Rust `cogit-core` port reproducing frozen vectors | P1 | `issues/COG-013.md`, ADR-0007 |
| COG-016 | License and open-source posture (OQ-004) — needs owner decision | P1 | `issues/COG-016.md` |
| COG-027 | Shorthand fact input for `add-fact` | P1 | `issues/COG-027.md` |
| COG-028 | `cogit facts` / `cogit show` porcelain | P1 | `issues/COG-028.md` |
| COG-025 | Abbreviated object-id resolution and `--json` on all commands | P1 (was P2; COG-012 findings) | CLI contract |

## Open — later (P1/P2 stories, unscoped)

| ID | Title | Priority | Refs |
| --- | --- | --- | --- |
| COG-018 | Notes-like annotations without rewriting objects | P1 | US-017 |
| COG-019 | `log --introduced-fact` / `--removed-fact` queries | P1 | US-018 |
| COG-020 | Conflict resolution memory (rerere-like) | P1 | US-019, OQ-008 |
| COG-021 | `bisect-thought` with oracle contract | P1 | US-020, OQ-009 |
| COG-022 | `count-objects` and maintenance thresholds | P1 | US-021, US-022, ADR-0006 |
| COG-023 | Secret detection v2 beyond pattern heuristics | P2 | OQ-013 |
| COG-024 | Reflog retention policy | P2 | OQ-010 |
| COG-026 | Trust layer: signatures, quarantine, imports | P2 | US-023, US-024, OQ-012 |
