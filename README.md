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

![Cogit web viewer: thought DAG with a competing-hypothesis branch, active
beliefs, and blame for a confirmed root cause](docs/assets/cogit-viewer.png)

*The bundled read-only web viewer on a debugging session: a competing
hypothesis on its own colored branch lane, three writers with their own
avatars (who wrote what — Rule 10 attribution), an anchored milestone, the
same root-cause claim strengthening from 72% (inference) to 98% (verified)
with the observations it was derived from (premises), and the exact
thought that introduced it.*

## Status

Working MVP. The Python reference implementation and a full Rust port
drive **one repository interchangeably** (`tools/interop-test.sh`); the
object format is frozen by golden test vectors; agents can use it live
today through the MCP server.

- `docs/` — PRD, ADRs, specs (object format, repository layout, CLI contract),
  invariants, test strategy, roadmap, threat model, recovery playbook.
- `prototype/` — zero-dependency Python 3 reference implementation of the full
  CLI contract, with tests and frozen object-format test vectors
  (`docs/adr/0010-python-prototype-slice.md`).
- `crates/` — the Rust implementation (`cogit-core` library + `cogit-cli`
  binary, ADR-0007) with full command parity; reproduces the frozen
  vectors byte-for-byte.
- `prototype/integrations/` — MCP server (agents journal live via tools),
  Claude Code hook (passive journaling), and the read-only web viewer.
  See `prototype/integrations/README.md`.
- `user_stories/` — agent-voice backlog (US-001..US-027).
- `ideas/` — original concept notes.

## Core model

| Git | Cogit | Meaning |
| --- | --- | --- |
| blob | claim + assertion | a structured proposition + provenance-bearing evidence about it |
| tree | mindset | immutable snapshot of active assertion IDs |
| commit | thought | reasoning checkpoint with parents, mindset, author, message |
| tag | anchor | named milestone pointing to a thought |
| branch | hypothesis | movable ref to the tip of a reasoning line |
| reflog | operational provenance | append-only journal of pointer movement |
| notes | annotation | post-hoc review overlay that never rewrites its target |

"Fact" is product shorthand for an active assertion about a claim.
How to model claims well — one proposition per claim, value objects,
calibrated confidence — is `docs/claim-modeling.md`.

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

The Rust CLI is drop-in equivalent (same commands, same on-disk format):

```sh
cargo build
./target/debug/cogit --repo /tmp/demo status
```

## Use it from an agent (MCP)

The intended user is an agent. The MCP server exposes the porcelain as 26
tools (destructive maintenance excluded by design, ADR-0009):

```sh
claude mcp add cogit -e COGIT_REPO=$HOME/.cogit-journal/my-project \
    -- python3 /ABS/PATH/prototype/integrations/mcp_server.py
```

Suggested loop: start a session with `recap` (no arguments — it resumes
from your newest anchor), record decisions with `add_fact(commit=true)`
(atomic micro-commits, safe for parallel agents on one journal), `anchor`
milestones, and when something turns out wrong, `blame_fact` it back to
the thought that introduced it. When a belief changes state, use the
atomic lifecycle operations (COG-056): `supersede_fact` (new value, same
claim family), `refute_fact` (structural negation, invariant 25) and
`retire_fact` (explicit removal without asserting falsity) — each is one
all-or-nothing thought. What deserves to be a fact — and what does
not — is `docs/claim-modeling.md`.

## Watch a journal (web viewer)

```sh
python3 prototype/integrations/web_viewer.py --repo ~/.cogit-journal/my-project
# read-only UI at http://127.0.0.1:8323/  (or --snapshot journal.html)
```

The DAG draws each branch on its own colored lane; every thought carries
its writer's avatar and the project threads it touched. Click an actor in
the legend or a project chip to light up just that line of work; long
belief values expand in place; filters live in the URL, so a filtered
view is bookmarkable. `deploy/` runs the same viewer as a read-only
container (`docker compose up -d`).

Run the test suites:

```sh
cd prototype && python3 -m unittest discover -s tests   # 166 tests
cargo test                                              # core + golden vectors
sh tools/interop-test.sh                                # Python <-> Rust on one repo
```

## Design guarantees

- Immutable objects never change after publication; reads verify hash and
  the known-field schema — unknown fields from a newer version are
  tolerated, never fatal (`docs/spec/object-format-v1.md`, ADR-0015).
- Ref updates are atomic, use old-value checks, and every `HEAD`/branch
  movement appends a reflog entry (`docs/adr/0004-integrity-and-ref-atomicity.md`).
- `blame-fact` means *first introducer* in selected ancestry, not last
  modifier (`docs/adr/0005-first-introducer-blame.md`).
- Merge is conservative: when unsure, record a conflict, never invent a
  resolution.
- Secrets must not be stored; suspected secret writes are rejected, not
  redacted (`docs/adr/0009-agent-autonomy-and-destructive-operations.md`).
- Full invariant list: `docs/invariants.md`.

## Support the author

If you find **Cogit** useful, you can optionally support development on
Boosty — entirely voluntary, no perks or obligations:
**[Donate on Boosty](https://boosty.to/niksh612/donate)**

## License and contributions

Licensed under the [Apache License 2.0](LICENSE). Contributions are
welcome: open an issue referencing a `BACKLOG.md` ticket (or propose a new
one), keep changes within the invariants in `docs/invariants.md`, and
include tests — the object format may only change through an ADR plus
regenerated test vectors.
