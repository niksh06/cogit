# Cogit Backlog

created_datetime: 2026-07-02T12:00:00+03:00
updated_datetime: 2026-07-05T00:40:00+03:00

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
| COG-017 | Repo housekeeping: init product VCS, exclude `git/` reference tree | `issues/COG-017.md` | initial commit `90e8133`; tree clean, `git/`/`.venv` untracked, 59 files, 2026-07-02 |
| COG-011 | "Why not plain Git?" positioning ADR | ADR-0011 | doc review; README links it |
| COG-014 | Atomic symbolic-HEAD updates (old-content check on HEAD writes) | `issues/COG-014.md` | `test_refs.py` HEAD race/lock tests (exit 4), spec updated |
| COG-015 | Negation-aware merge and commit checks (invariants 24–25) | `issues/COG-015.md` | `test_repo.py` negation tests; verify warns `contradictory-mindset` |
| COG-012 | Integration experiment: Claude Code hook + CLI dogfood session | `issues/COG-012.md` | hook smoke-tested (incl. secret rejection); findings report 2026-07-02; spawned COG-027/028, re-prioritized COG-025 |
| COG-016 | License: Apache-2.0 adopted, OQ-004 closed as CQ-014 | `issues/COG-016.md` | commit `859e541`; owner decision 2026-07-02 |
| COG-027 | Shorthand fact input for `add-fact` (incl. `--negates`) | `issues/COG-027.md` | commit `77543d7`; parity test: shorthand == JSON object IDs |
| COG-028 | `cogit facts` / `cogit show` porcelain | `issues/COG-028.md` | commit `c8846fb`; `test_cli.py::test_facts_and_show` |
| COG-025 | Abbreviated object-id prefixes + `--json` on all porcelain commands | CLI contract | commit `188b9f5`; 77 tests green 2026-07-02 |
| COG-019 | `log --introduced-fact` / `--removed-fact` event queries | `issues/COG-019.md` | commit `cf7f83a`; re-introduction test in `test_cli.py` |
| COG-021 | `bisect-thought` with oracle contract (closed OQ-009 as CQ-015) | `issues/COG-021.md` | commit `9524e7c`; `test_bisect.py` incl. skip range + real-oracle CLI run |
| COG-022 | `count-objects` pressure metrics with `[maintenance]` thresholds | `issues/COG-022.md` | `test_maintenance.py`; 86 tests green 2026-07-02; `gc --auto` deferred until compaction exists |
| COG-018 | Annotations: `annotation` object type, typed namespaces, annotate/annotations, `log --annotations` (ADR-0012; closed OQ-007 as CQ-016) | `issues/COG-018.md` | annotation tests in `test_repo.py`/`test_cli.py`; vectors +1 additive (5 frozen intact); 91 tests green 2026-07-02 |
| COG-020 | Rerere: orientation-invariant conflict fingerprints, remembered resolutions, `resolve --suggested`, `cogit rerere` (closed OQ-008 as CQ-017) | `issues/COG-020.md` | `test_rerere.py` (record/suggest/apply/forget, drop memory); 97 tests green 2026-07-02; roadmap Phase 4 DONE |
| COG-023 | Secret detection v2: entropy heuristic + URL/AWS shapes, false-positive guards (OQ-013 narrowed) | commit `f72d0c3` | `test_secrets.py`: object ids/identifiers pass, tokens/URL-creds rejected |
| COG-024 | Reflog retention: explicit `reflog-expire` with dry-run and config default (closed OQ-010 as CQ-018) | commit `7bede04` | `test_refs.py::test_reflog_expire`; recovery playbook updated |
| COG-030 | `add-fact --commit` micro-commit + stdin input (model-review finding) | `issues/COG-030.md` | `test_cli.py`: micro-flow, dirty-index refusal, stdin id parity |
| COG-031 | `cogit recap` belief-state digest for context recovery (model-review finding) | `issues/COG-031.md` | `test_cli.py::test_recap`; 108 tests green 2026-07-02 |
| COG-013 | Rust port: `cogit-core` + `cogit-cli`, full command parity, golden vectors byte-for-byte | `issues/COG-013.md`, ADR-0007 | `cargo test` (12 tests, clippy clean); `tools/interop-test.sh`: Python↔Rust drive one repository interchangeably (ids, conflicts, rerere fingerprints, annotations, metrics all agree) |
| COG-029 | MCP server: stdio JSON-RPC, 18 tools, destructive ops excluded per ADR-0009 | `issues/COG-029.md` | `test_mcp_server.py`: real subprocess handshake, tool listing, full workflow (micro-commit→anchor→blame→recap→verify), soft errors incl. secret rejection |
| COG-032 | Claim-modeling cookbook: 7 rules, confidence bands, worked example | `issues/COG-032.md` | `docs/claim-modeling.md`; linked from README and integrations README |
| COG-035 | Atomic micro-commit + index.json.lock — parallel agents safe by construction (supersedes COG-033) | `issues/COG-035.md` | thread-parallel tests both runtimes (2 writers x 5, nothing lost); interop steps |
| COG-036 | facts subject/predicate/project filters; no-arg recap from newest anchor with from_anchor/same_point | `issues/COG-036.md` | `test_concurrency.py::BeliefQueryTests`; rust `micro_commit_noop_and_filters`; interop no-arg recap step |
| COG-037 | Project qualifier convention for shared journals (--project, MCP arg, cookbook Rule 8) | `issues/COG-037.md` | claim-identity test; interop project-filter step |
| COG-033 | Multi-process index safety — implemented by COG-035 (lockfile + atomic micro-commit) | `issues/COG-033.md` | superseded; see COG-035 verification |
| COG-038 | Read-only web viewer: thought DAG, beliefs+filters, blame, recap; live serve + HTML snapshot | `issues/COG-038.md` | `test_web_viewer.py` (11 tests); live browser check on shared journal 2026-07-04 (render, detail panels, snapshot mode, 0 console errors) |
| COG-039 | Belief-recovery benchmark: journal vs markdown vs transcript, 12 context-free readers | `issues/COG-039.md` | `test_belief_bench.py` (6 tests); run seed 20260704: markdown/transcript 1.00, journal 0.975 at ~2.3x reader tokens — solo-scale parity CONFIRMED against the journal; findings report 2026-07-04; spawned COG-040/041 |
| COG-040 | Explicit negation rendering: NOT prefix in facts/show/recap text, negation flag in JSON rows, viewer + MCP + cookbook wording | `issues/COG-040.md` | `test_cli.py::NegationRenderingTests`; rust refute-flow row asserts; interop step 13 green both runtimes |
| COG-041 | Scale benchmark: synthetic 10x (all media 1.00; journal read-cost +6% vs +59-74%) + REAL history (transcript 10/10 at 48 calls/10min; markdown confabulated; journal 0 fabrications) — H0 fired, trust-differentiator found | `issues/COG-041.md` | findings report 2026-07-04 (`~/Reports/projects/cogit/research/2026-07-04-cog-041-scale-benchmark.md`); harness `--segments` + deep-probe fix, `test_belief_bench.py` scale smoke; spawned COG-042 |
| COG-042 | `cogit dump` one-call reader surface (CLI+MCP+Rust parity); fact rows gain source_uri (dump readers fabricated URIs without it) | `issues/COG-042.md` | dump-medium readers score 1.00 on all probe classes from ONE artifact (6-9 tool calls vs 10-18); `test_cli.py::DumpTests`, rust `dump_one_call_surface`, MCP workflow step, interop step 14 |

## Open — next

| ID | Title | Priority | Refs |
| --- | --- | --- | --- |
| COG-034 | Live MCP session findings (needs owner: register server, run a real session) | P0 (usage phase) | `issues/COG-034.md` |

## Open — later (P1/P2 stories, unscoped)

| ID | Title | Priority | Refs |
| --- | --- | --- | --- |
| COG-026 | Trust layer: signatures, quarantine, imports — DEFERRED by roadmap entry criteria: no cross-process/team/machine sharing exists yet (Phase 7); building crypto before that is speculative architecture the project's own stop-conditions forbid | P2 | US-023, US-024, OQ-012 |
