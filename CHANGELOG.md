# Changelog

All notable changes to Cogit are recorded here (format inspired by
[Keep a Changelog](https://keepachangelog.com), versioning is semver
with a 0.x major). **The topmost release heading is the authoritative
current version**: `prototype/cogit/__init__.py` and both `Cargo.toml`s
must match it, and `tools/interop-test.sh` fails if any copy drifts.

The version names the SOFTWARE. The repository FORMAT is versioned
separately (`repositoryFormatVersion` in `.cogit/config`, currently 1)
and only changes through an ADR plus regenerated test vectors.

## [0.2.0] — 2026-07-12

The field-hardening release: everything learned from running the shared
journal with parallel agents since publication.

### Added
- Atomic micro-commits (`add-fact --commit`) and `micro-commit-batch` /
  MCP `record`: all-or-nothing multi-fact thoughts that bypass the
  shared index — safe for parallel agents on one journal (COG-035/044).
- Lifecycle porcelain, one atomic thought each: `supersede-fact`,
  `refute-fact`, `retire-fact` (COG-056).
- Durable removal provenance: thoughts record WHY each assertion left
  the mindset (`removals`, ADR-0014); `recap`/`dump` expose
  `removal_reason`; verify checks consistency (invariant 27).
- `search` — cogit's git-grep over beliefs: substring across subjects,
  predicates, objects, qualifier values and annotation bodies, with
  `--history` and project scoping (COG-068).
- Derivation-graph queries: `taint` (reversed-premise closure) and
  `support` (maximin/widest-path strength with bottleneck) (COG-050).
- One-call project `health` document; journal discipline codified in
  `docs/journal-discipline.md` (D1–D10) with write-time lint hints and
  a lint-ratchet line in the session digest (COG-059/067).
- `detail=` on fact writes (same-call annotation) and MCP defaults —
  a minimal fact is four fields (COG-064/065).
- Web viewer v2: branch lanes, writer avatars, project chips, health
  panel, ETag/304 polling (COG-054/060).
- Version discipline itself: this file as the version source of truth,
  `--version` on both CLIs, version surfaced in viewer footer,
  `health()` reader field, MCP serverInfo and the session digest
  (COG-070).

### Changed
- Readers tolerate unknown fields on known object types (ADR-0015);
  writes stay strict. Root cause of the live
  `CorruptionError: unknown fields: ['removals']` (old reader × newer
  writer). Pre-0.2.0 readers must be restarted to pick this up.
- Project slugs are normalized at the write choke point and matched
  case-insensitively on read; live journal migrated (COG-063).
- The Claude Code hook never touches the shared index: PostToolUse
  buffers per session, Stop publishes one atomic batch (COG-062).
- `build_state` sheds its quadratic object reads; viewer state builds
  are memoized on content addressing (COG-061).

### Fixed
- `record` staging rollback on validation error (P1 atomicity bug),
  plus the COG-055..060 review line (Sol).

## [0.1.0] — 2026-07-02

Initial public MVP (recorded retroactively): content-addressed object
store (claims/assertions/mindsets/thoughts/anchors/annotations, frozen
golden vectors), refs with atomic old-value checks and reflogs, the
full CLI contract in a zero-dependency Python reference implementation
and an interchangeable Rust port (`tools/interop-test.sh`), first-
introducer `blame-fact`, conservative claim-level merge, `verify`,
MCP server, Claude Code hook and the read-only web viewer.
