# Cogit Backlog

created_datetime: 2026-07-02T12:00:00+03:00
updated_datetime: 2026-07-02T21:30:00+03:00

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
| COG-016 | License: Apache-2.0 adopted, OQ-004 closed as CQ-014 | `issues/COG-016.md` | commit `6b8f58d`; owner decision 2026-07-02 |
| COG-027 | Shorthand fact input for `add-fact` (incl. `--negates`) | `issues/COG-027.md` | commit `2ebe3ee`; parity test: shorthand == JSON object IDs |
| COG-028 | `cogit facts` / `cogit show` porcelain | `issues/COG-028.md` | commit `3e3acac`; `test_cli.py::test_facts_and_show` |
| COG-025 | Abbreviated object-id prefixes + `--json` on all porcelain commands | CLI contract | commit `c2fb017`; 77 tests green 2026-07-02 |
| COG-019 | `log --introduced-fact` / `--removed-fact` event queries | `issues/COG-019.md` | commit `ad1b522`; re-introduction test in `test_cli.py` |
| COG-021 | `bisect-thought` with oracle contract (closed OQ-009 as CQ-015) | `issues/COG-021.md` | commit `f9ec330`; `test_bisect.py` incl. skip range + real-oracle CLI run |
| COG-022 | `count-objects` pressure metrics with `[maintenance]` thresholds | `issues/COG-022.md` | `test_maintenance.py`; 86 tests green 2026-07-02; `gc --auto` deferred until compaction exists |
| COG-018 | Annotations: `annotation` object type, typed namespaces, annotate/annotations, `log --annotations` (ADR-0012; closed OQ-007 as CQ-016) | `issues/COG-018.md` | annotation tests in `test_repo.py`/`test_cli.py`; vectors +1 additive (5 frozen intact); 91 tests green 2026-07-02 |
| COG-020 | Rerere: orientation-invariant conflict fingerprints, remembered resolutions, `resolve --suggested`, `cogit rerere` (closed OQ-008 as CQ-017) | `issues/COG-020.md` | `test_rerere.py` (record/suggest/apply/forget, drop memory); 97 tests green 2026-07-02; roadmap Phase 4 DONE |
| COG-023 | Secret detection v2: entropy heuristic + URL/AWS shapes, false-positive guards (OQ-013 narrowed) | commit `03178bc` | `test_secrets.py`: object ids/identifiers pass, tokens/URL-creds rejected |
| COG-024 | Reflog retention: explicit `reflog-expire` with dry-run and config default (closed OQ-010 as CQ-018) | commit `18e39a8` | `test_refs.py::test_reflog_expire`; recovery playbook updated |
| COG-030 | `add-fact --commit` micro-commit + stdin input (model-review finding) | `issues/COG-030.md` | `test_cli.py`: micro-flow, dirty-index refusal, stdin id parity |
| COG-031 | `cogit recap` belief-state digest for context recovery (model-review finding) | `issues/COG-031.md` | `test_cli.py::test_recap`; 108 tests green 2026-07-02 |
| COG-013 | Rust port: `cogit-core` + `cogit-cli`, full command parity, golden vectors byte-for-byte | `issues/COG-013.md`, ADR-0007 | `cargo test` (12 tests, clippy clean); `tools/interop-test.sh`: Python↔Rust drive one repository interchangeably (ids, conflicts, rerere fingerprints, annotations, metrics all agree) |
| COG-029 | MCP server: stdio JSON-RPC, 18 tools, destructive ops excluded per ADR-0009 | `issues/COG-029.md` | `test_mcp_server.py`: real subprocess handshake, tool listing, full workflow (micro-commit→anchor→blame→recap→verify), soft errors incl. secret rejection |

## Open — next

| ID | Title | Priority | Refs |
| --- | --- | --- | --- |
| COG-034 | Live MCP session findings (needs owner: register server, run a real session) | P0 (usage phase) | `issues/COG-034.md` |
| COG-032 | Claim-modeling cookbook (model-review finding) | P1 | `issues/COG-032.md` |

## Open — later (P1/P2 stories, unscoped)

| ID | Title | Priority | Refs |
| --- | --- | --- | --- |
| COG-033 | Multi-process index safety (model-review finding) | P2 | `issues/COG-033.md` |
| COG-026 | Trust layer: signatures, quarantine, imports — DEFERRED by roadmap entry criteria: no cross-process/team/machine sharing exists yet (Phase 7); building crypto before that is speculative architecture the project's own stop-conditions forbid | P2 | US-023, US-024, OQ-012 |
