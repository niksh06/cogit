# ADR-0014: Durable Removal Provenance

created_datetime: 2026-07-10T01:30:00+03:00
status: Accepted (COG-057)

## Context

Cogit REQUIRES a reason at removal time (`remove-fact --reason`,
invariant 25 even inspects it), then throws it away: reasons live only
in the mutable `index.json`, which is cleared the moment the thought is
committed. After that, the exact reason the writer supplied is
unrecoverable — COG-045 analytics has to re-infer superseded/refuted/
retired structurally, free-form retirement reasons are simply lost, and
merge-time arbitration ("refuted" vs "merge-conflict-resolution",
already distinguished by `resolve`) evaporates.

## Options considered

1. **Optional `removals` field on the thought object** — the thought
   that publishes the removal carries `[{assertion, reason}]`.
2. **Dedicated transition object** referenced by the thought — a new
   object type holding removal metadata.
3. **Typed annotation overlay** keyed to thought + assertion — reasons
   as after-the-fact annotations.

Option 2 adds an object type, a reference hop on every read, and a
consistency obligation (thought without its transition object is
half-readable) — cost without benefit at this data size. Option 3 is
not atomic (annotation lands in a separate operation, so a crash
between commit and annotate loses provenance again) and pollutes a
human-note namespace with machine metadata. Option 1 keeps the reason
in the SAME atomic publication as the mindset change, is trivially
human-inspectable (`cat-object` on the thought), and is a pure additive
extension.

## Decision

1. **Format**: thought objects gain an OPTIONAL `removals` field:

   ```json
   {"type": "thought", "parents": ["sha256:…"], "mindset": "sha256:…",
    "operation": "commit", "message": "…", "author": "…",
    "timestamp": "…",
    "removals": [{"assertion": "sha256:…", "reason": "superseded"}]}
   ```

   - Absent field ≡ no recorded removal reasons (every existing object
     stays valid; object-format v1 is extended additively, exactly like
     `premises` in ADR-0013).
   - When present: non-empty, sorted by `assertion`, unique assertions,
     each `reason` a non-empty string. The field is part of the
     content-addressed preimage (identity-bearing).
   - Frozen vectors 1–7 are untouched; an 8th additive vector freezes a
     thought with removals. Python/Rust must reproduce it byte-for-byte.

2. **Write paths** populate it uniformly from data that already exists:
   - staged flow (`commit-thought`): from `index.removed_facts`
     (`{id, reason}` — including merge conflict resolutions, where
     `resolve` already writes `refuted` / `merge-conflict-resolution`);
   - batch flow (`record` / lifecycle porcelain, COG-055/056): from the
     batch removal list.
   Hand-written thought objects MAY omit the field (legacy parity).

3. **Merge semantics**: for a two-parent thought the recorded removals
   are the conflict-resolution drops; membership is checked against the
   UNION of parent mindsets. No claim of completeness is made for
   merges (the parent-union delta legitimately contains assertions that
   simply lost the merge without an explicit arbitration entry).

4. **Verification** (`verify`):
   - ERROR `removal-not-removed`: a recorded removal still present in
     the thought's own mindset.
   - ERROR `removal-not-in-parents`: a recorded removal absent from all
     parent mindsets (nothing was removed).
   - WARN `removals-incomplete`: single-parent thought whose actual
     delta (parent − own) contains assertions not covered by the
     recorded removals — expected for legacy thoughts only when the
     field is present but partial; thoughts WITHOUT the field are
     skipped entirely (legacy readability).

5. **Exposure**: `log --json` thoughts carry `removals` verbatim; recap
   / dump removed rows gain `removal_reason` (null when legacy);
   the viewer shows the reason on removed-belief lines; COG-045
   analytics classification order: structural negation match (always
   `refuted` — structure outranks labels) → recognized recorded reasons
   (`refuted`, `superseded`) → structural fallback for free-text or
   absent reasons (same-family replacement → `superseded`, else
   `retired`). Free-text reasons stay visible verbatim on every
   exposure surface even where classification falls back.

6. **Recovery**: the reason is recoverable from the immutable thought
   alone — no transient index, no message parsing. `cat-object
   <thought>` is the audit surface.

## Consequences

- New thoughts that remove assertions get slightly larger and change
  identity relative to a hypothetical reason-less encoding — acceptable:
  thought identity already covers message/author/timestamp provenance.
- Legacy repositories remain fully readable; analytics keeps its
  structural fallback for pre-ADR history forever.
- Rust and Python must agree byte-for-byte on the sorted encoding
  (guaranteed by canonical JSON + explicit sort at write time).
