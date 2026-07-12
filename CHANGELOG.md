# Changelog

All notable changes to Cogit are recorded here (format inspired by
[Keep a Changelog](https://keepachangelog.com), versioning is semver
with a 0.x major). **The topmost release heading is the authoritative
current version**: `prototype/cogit/__init__.py` and both `Cargo.toml`s
must match it, and `tools/interop-test.sh` fails if any copy drifts.

The version names the SOFTWARE. The repository FORMAT is versioned
separately (`repositoryFormatVersion` in `.cogit/config`, currently 1)
and only changes through an ADR plus regenerated test vectors.

## [0.5.0] — 2026-07-12

Agent-write ergonomics (COG-073) — first-hand dogfooding feedback from an
agent user: cogit asked the writer to be a librarian at the exact moment
it is an engineer. This release makes the right thing the cheap thing;
the model itself does not budge.

### Added
- Lifecycle by family: `supersede-fact` / `refute-fact` / `retire-fact`
  accept `subject` + `predicate` (+ optional `project`) instead of an
  assertion id — the single active family member resolves server-side;
  zero matches is a clean "add-fact instead" error, several rivals
  refuse and list the candidates. Both runtimes, CLI and MCP.
- Opt-in `normalize` on MCP `add_fact`/`record`: a prose object splits
  deterministically — first clause stays the value (lint R2 threshold),
  the FULL original lands verbatim as the `detail` annotation, and the
  response reports the rewrite. Never applied silently.
- `skills/cogit-journaling/SKILL.md`: the write-time distillation of
  claim-modeling + journal discipline, shaped for agents (prose→triple
  decomposition, lifecycle by family, when NOT to write).

### Changed
- Subjects normalize at the write choke point in both runtimes
  (lowercase, whitespace→dash — punctuation untouched), exactly like
  project slugs (COG-063): `"OSV Distro Full-Scope Land"` lands as
  `osv-distro-full-scope-land`. Read filters and family computations
  match case-insensitively, so pre-0.5.0 mixed-case history stays one
  family. R3-subject-whitespace debt can no longer be produced through
  porcelain.

## [0.4.1] — 2026-07-12

### Fixed
- Hook: git-commit captures keep the belief object a value (lint R2).
  JSON-encoded tool responses hide stat lines behind a literal `\n`
  that `splitlines()` cannot split, so `head_commit` objects leaked
  `… 11 files changed, …` tails; the subject is now cut at the escaped
  newline and capped at 10 words / 100 chars — the full message lives
  in git itself.

## [0.4.0] — 2026-07-12

### Added
- Viewer: the journal now reads like git (COG-072, owner-picked design).
  Project swimlanes — every project is its own colored lane, thoughts
  connect into continuous per-project threads, multi-project thoughts
  span their lanes; the branch-DAG layout stays one toggle away
  (`view=` URL param, auto-picked: multi-project journal → projects,
  else branches). Anchor chapters — anchors partition the timeline into
  collapsible sections with the newest expanded, so a 250-thought
  journal opens as a table of contents of milestones (and the DOM
  shrinks accordingly). Jumps from recap/blame expand the right chapter.

## [0.3.0] — 2026-07-12

### Added
- Writer provenance (ADR-0016, COG-071): every new thought records which
  build wrote it — an optional `writer` field, `<impl>/<semver>` (e.g.
  `cogit-py/0.3.0`). Thoughts only: claims/assertions are
  identity-deduplicated and never carry the version. Golden vector #9
  freezes the field; the entire pre-0.3.0 history (no `writer`) stays
  valid. `log --json`/`dump` expose it; `health()` reports
  `newest_writer` and warns (`version_skew`) when the journal holds
  thoughts written by a newer cogit than the reader.

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
