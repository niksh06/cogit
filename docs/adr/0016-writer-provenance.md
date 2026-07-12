# ADR-0016: Writer Provenance on Thoughts

created_datetime: 2026-07-12T12:00:00+03:00
status: Accepted (owner decision 2026-07-12)

## Context

Cogit is in live field use while under active development. Journals
accumulate history written by many builds of the tool, and nothing on
the artifacts says which era wrote what: pre-slug-normalization rows,
thoughts without removal provenance, and future format additions all
look like anomalies instead of dated behavior. Version skew between a
running reader and a newer writer bit twice in one week (the stale MCP
server's `CorruptionError`, the stale viewer container's 124-second
polls) and was invisible both times until root-caused by hand.

A tool whose purpose is provenance of beliefs should carry provenance
of its own records. Git ships the analogous machinery implicitly: the
repository format version gates readers, and commits carry enough
headers to date behavior changes.

COG-070 already made the version real (CHANGELOG.md as source of
truth, `--version`, surfacing in viewer/health/digest). This ADR puts
it on the artifacts.

## Decision

1. **Thoughts carry an optional `writer` field**: a single token
   `<impl>/<semver>` — `cogit-py/0.3.0`, `cogit-rs/0.3.0`. The grammar
   reserves an optional `+<build>` suffix; nothing emits it today
   (build-hash introspection in two zero-dependency runtimes is not
   worth it yet). Every thought-creating path stamps it: staged
   commits, merges, atomic micro-commits and batches — hence all
   lifecycle operations, `record`, and the hook.
2. **Thoughts only.** Claims and assertions are identity-deduplicated
   across writers; a version field there would split identical facts
   into different IDs and break families, supersede targeting and the
   interop guarantee. Anchors and annotations are small overlays; every
   belief change is already bounded by a thought, so the thought stamp
   dates it.
3. **Validation** (write-strict, read-tolerant like any known field per
   ADR-0015): if present — non-empty string, at most 64 chars, no
   whitespace or control characters, exactly one `/`, both halves
   non-empty. Absent field stays valid forever: the entire pre-0.3.0
   history has no `writer`.
4. **Identity-bearing**: the field is part of the preimage, frozen by
   golden vector #9. Two thoughts differing only in writer are
   different thoughts — that is correct: they are records by different
   tools.
5. **Skew detection**: `health()` reports `newest_writer` (max semver
   among the newest 50 thoughts) and emits a `version_skew` warning
   when the journal holds thoughts written by a NEWER version than the
   reader — the actionable direction (restart/upgrade stale readers).
   Older writers in history are normal, never warned about.

## Consequences

- `log --json` / `dump` expose `writer` on thought rows for free (both
  runtimes pass thought objects through).
- Mixed-version journals are normal and expected (parallel sessions,
  CLI vs MCP vs hook); no ordering or monotonicity is enforced.
- Byte-parity across runtimes for independently-written thoughts no
  longer holds even with identical inputs (the impl half differs) —
  nothing relied on it; cross-runtime interop reads, verifies and
  extends the other's thoughts, which the interop suite proves.
- Readers older than ADR-0015 would reject stamped thoughts as unknown
  fields; ADR-0015 shipped before this, and its grandfathering note
  applies: restart pre-0.2.0 processes.
