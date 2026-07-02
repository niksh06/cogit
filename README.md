# Cogit

**Version control for agent cognition.** Cogit is a Git-inspired, local-first,
content-addressed store for agent reasoning provenance: what an agent committed
as belief, which source introduced it, which reasoning checkpoint changed the
active state, and how the active hypothesis pointer moved over time.

Cogit is **not** retrieval memory. It does not do embeddings, semantic search,
or context assembly. It answers audit questions:

- What did the agent believe at this thought?
- Which thought first introduced this fact, and from which source?
- How did `HEAD` or a hypothesis branch move, and how do I recover an
  abandoned reasoning path?

See `docs/adr/0002-provenance-not-retrieval-memory.md` for the boundary, and
`docs/adr/0011-why-not-plain-git.md` for why this is a standalone engine
rather than a convention over Git (short version: Git cannot merge or blame
*propositions*, only lines in files).

## Status

Concept with a working reference prototype.

- `docs/` — PRD, ADRs, specs (object format, repository layout, CLI contract),
  invariants, test strategy, roadmap, threat model, recovery playbook.
- `prototype/` — zero-dependency Python 3 reference implementation of the full
  MVP CLI contract, with tests and frozen object-format test vectors.
  The production implementation direction remains Rust
  (`docs/adr/0007-rust-workspace-and-first-slice.md`); the prototype exists to
  validate the specs and freeze cross-runtime object identity
  (`docs/adr/0010-python-prototype-slice.md`).
- `user_stories/` — agent-voice backlog (US-001..US-027).
- `ideas/` — original concept notes.
- `git/` — a reference copy of the upstream Git source tree used during
  design. It is not part of the product and should be excluded from any
  packaging or version control of this repository.

## Core model

| Git | Cogit | Meaning |
| --- | --- | --- |
| blob | claim + assertion | a structured proposition + provenance-bearing evidence about it |
| tree | mindset | immutable snapshot of active assertion IDs |
| commit | thought | reasoning checkpoint with parents, mindset, author, message |
| tag | anchor | named milestone pointing to a thought |
| branch | hypothesis | movable ref to the tip of a reasoning line |
| reflog | operational provenance | append-only journal of pointer movement |

"Fact" is product shorthand for an active assertion about a claim.

Objects are zlib-compressed `<type> <size>\0<canonical-json>` preimages
addressed by SHA-256 under `.cogit/objects/xx/...`. Everything is inspectable
with standard filesystem tools plus zlib/JSON decoding.

## Quickstart (prototype)

```sh
cd prototype
python3 -m cogit init /tmp/demo
cd /tmp/demo

# stage a fact (claim + assertion), commit a thought
python3 -m cogit add-fact '{
  "claim": {"type": "claim", "kind": "user_preference", "subject": "user",
             "predicate": "prefers_response_style", "object": "brief",
             "qualifiers": {}},
  "assertion": {"type": "assertion", "status": "asserted",
                 "source": {"type": "prompt", "uri": "conversation:current"},
                 "confidence_bps": 9200, "asserted_at": "2026-07-02T12:00:00Z",
                 "actor": "agent", "method": {"type": "user_statement"}}
}'
python3 -m cogit commit-thought --message "Captured user preference" --author agent

python3 -m cogit branch hypothesis-a     # O(1): only a ref is created
python3 -m cogit checkout hypothesis-a
python3 -m cogit status
python3 -m cogit log
python3 -m cogit log -g                  # reflog: operational provenance
python3 -m cogit verify
```

Run the test suite:

```sh
cd prototype
python3 -m unittest discover -s tests -v
```

## Design guarantees

- Immutable objects never change after publication; reads verify hash and
  schema (`docs/spec/object-format-v1.md`).
- Ref updates are atomic, use old-value checks, and every `HEAD`/branch
  movement appends a reflog entry (`docs/adr/0004-integrity-and-ref-atomicity.md`).
- `blame-fact` means *first introducer* in selected ancestry, not last
  modifier (`docs/adr/0005-first-introducer-blame.md`).
- Merge is conservative: when unsure, record a conflict, never invent a
  resolution.
- Secrets must not be stored; suspected secret writes are rejected, not
  redacted (`docs/adr/0009-agent-autonomy-and-destructive-operations.md`).
- Full invariant list: `docs/invariants.md`.
