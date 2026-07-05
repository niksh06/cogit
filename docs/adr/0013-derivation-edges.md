# ADR-0013: Derivation Edges (Premises) Between Beliefs

created_datetime: 2026-07-05T14:00:00+03:00
status: Accepted (implementation staged; COG-046)

## Context

An assertion records WHERE a belief came from externally (`source`:
tool, prompt, file, agent) but not WHAT it was inferred from inside the
journal. Nothing connects "suite is green" and "pool saturation at 98%"
to the conclusion "root cause is pool exhaustion". Without those edges
the journal cannot answer the questions graph algorithms exist for:

- **Taint**: source X turned out to be poisoned (prompt injection,
  broken tool) — which downstream conclusions inherit the poison?
- **Support strength**: how strong is the weakest link in the evidence
  chain behind a conclusion?
- **Criticality**: which beliefs carry the most derived weight and
  deserve verification first?

The COG-039/041 benchmarks fixed the product thesis as "trust of
recall"; derivation edges extend that trust from single beliefs to
chains of reasoning. This ADR was requested as the owner's "what math
can we bring in" line (COG-046).

## Decision

1. **Format**: assertions gain an OPTIONAL `premises` field — a sorted,
   deduplicated array of assertion IDs the author relied on:

   ```json
   {"type": "assertion", "claim": "sha256:…", "status": "asserted",
    "premises": ["sha256:aa…", "sha256:bb…"], "…": "…"}
   ```

   - Absent field ≡ no recorded premises (all existing objects stay
     valid; object-format v1 is extended, not broken).
   - Write-time validation: every premise must exist and be an
     assertion object. Self-reference is impossible and cycles cannot
     be constructed at all: premise IDs are part of the content-addressed
     preimage, so an assertion can only reference assertions that
     already exist — the derivation graph is a DAG **by construction**.
   - Identity: premises are part of the assertion preimage. The same
     claim at the same confidence derived from different evidence is a
     DIFFERENT assertion. That is intended: "same conclusion, different
     grounds" is exactly what an auditor wants to distinguish.
2. **Vectors**: one additive golden vector (assertion with premises)
   per the CQ-011 process; the existing frozen vectors stay intact —
   same procedure ADR-0012 used for annotations.
3. **Write surface**: `add-fact --premise <id>` (repeatable) and the
   `premises` argument in the MCP `add_fact`/`record` tools. Premises
   are never inferred automatically — recording them is an explicit
   authoring act (the coverage question inherits COG-044's
   pilot-and-measure discipline; expect sparsity first).
4. **Read surface, staged behind usage**:
   - Phase A (with the format change): expose `premises` in fact rows,
     `show`, `dump`; viewer draws them in the fact panel.
   - Phase B: `taint <assertion-id | source-uri>` — reachability
     closure over the reversed premise graph (all conclusions resting
     on the tainted node/source), the recall-cascade primitive for the
     trust line (COG-026).
   - Phase C: `support <assertion-id>` — maximin path: the strength of
     a conclusion is the maximum over derivation paths of the minimum
     confidence along the path (bottleneck shortest path, the
     Dijkstra-family algorithm that IS meaningful here).
   - Later, evidence permitting: criticality (out-degree-weighted
     centrality over the premise graph).

## Consequences

- Positive: reasoning chains become auditable objects; taint analysis
  turns "the source was poisoned" from a rediscovery project into one
  query; support strength gives negation/merge arbitration a
  quantitative input it never had.
- Negative/costs: one more optional field in the write path and the
  identity function; premise recording is manual and will be sparse
  until affordances prove themselves (measured, not assumed); both
  runtimes must implement validation in lockstep plus one new vector.
- Explicit non-goals: automatic confidence FUSION over premises
  (Dempster-Shafer, Bayesian networks) — fusing erases authorship and
  dilutes the anti-confabulation property the benchmarks certified;
  automatic premise inference from context — premises are testimony,
  not telemetry.

## Implementation tickets

- COG-049 — premises v1: format + validation + vectors + write surface
  + row/dump exposure (both runtimes, interop step).
- COG-050 — graph queries over premises: `taint`, then `support`
  (entry criterion: real journals contain premises; measure like
  COG-044).
