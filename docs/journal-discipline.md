# Journal Discipline (D-rules)

created_datetime: 2026-07-11T13:30:00+03:00

`docs/claim-modeling.md` teaches how to SHAPE one claim. This document
is the operating discipline AROUND the journal: when to write, when not
to, and what keeps a shared journal a belief base instead of a dump.

Every rule below is data-driven: the 2026-07-11 inventory of the live
shared journal (433 active beliefs) found 41% prose objects, 84%
single-use predicates in the busiest project, four naming styles at
once, and ZERO structural refutations — while thought messages, anchors
and supersede semantics were healthy. The rules target exactly those
failure modes.

## D1. The journal is a belief base, not a note log

Write what is TRUE NOW, phrased so a later session can act on it.
Narrative — how you got there, what happened along the way — goes into
`detail=` (same call, lands as an annotation) or into a report. The
test: *"will another session ask for this VALUE, or would they rather
read the story?"* Value → fact. Story → detail/report.

## D2. Predicates are reusable relations, not headlines

`status`, `verdict`, `root_cause`, `owner`, `shipped_commit`,
`suite_status` — a predicate you will write AGAIN for the same subject.
If your predicate reads like a sentence
(`phase2_scorecard_shipped_ticket_closed`), you are writing a headline:
the family can never revise, supersede chains never form, volatility
and calibration stay blind. Ask: *"will I write this exact predicate
again next week?"* No → reformulate (usually `subject=<thing>`,
`predicate=status|verdict`, value in the object, story in detail).

## D3. Objects are values; time and provenance have their own fields

Object ≤ ~12 words. Dates never open an object — assertion time is
`asserted_at`. Commit hashes are provenance — `source: git-commit:...`
or `premises`. Rich context — `detail=`. A 1000-char object is a report
cell, not a belief.

## D4. State changes go through lifecycle operations

- value changed → `supersede_fact` (same family, one atomic thought);
- belief turned out FALSE → `refute_fact` (structural negation;
  "REFUTE:" inside prose is invisible to analytics — the inventory
  found 32 prose-refutes and zero structural ones);
- no longer relevant, not false → `retire_fact` with a reason.

Removal reasons survive on the thought (ADR-0014) — they are the audit
trail; spend one honest word on them.

## D5. One naming style: `project:area:entity`

Lowercase, colon-separated, no spaces (the busiest project ran four
styles at once — colons, dots, `artifact:` paths and free text with
spaces; pick colons and stop). The `project` qualifier is a lowercase
slug and normalizes automatically (COG-063); subjects are on you.

## D6. kind and source agree

`tool_observation` ⇔ `source: tool:...`; `agent_decision`/inference ⇔
`agent:...`; someone's words ⇔ `user_preference`/`document_claim` with
`prompt:`/`doc:`. The inventory found 98 mismatches — every one skews
per-source calibration.

## D7. Anchor milestones, resume from digests

Anchor at epic start/end and before risky operations. Resume with the
session-start digest, `recap(project=...)` or `health(project=...)` —
never by re-reading the whole journal, and never by keeping a parallel
markdown copy of it (that copy is where confabulation lives — measured
in COG-041).

## D8. Know what NOT to write

No chain-of-thought, no intermediate steps, nothing derivable from code
or git history, no one-off observations without a future reader, no
secrets (they are rejected, not redacted). Threshold: *"does this fact
help a different session a week from now?"*

## D9. Leave the journal lint-clean at the ratchet

Before closing an epic: `lint --project X --since <baseline> --strict`
→ zero NEW warnings. Old debt is the baseline's problem; new debt is
yours. Resolve R11 competing-value findings immediately — two active
answers to one question is the definition of a dump.

## D10. Parallel sessions use atomic writes only

`add_fact(commit=true)`, `record`, lifecycle ops — all CAS-atomic, all
safe. The staged flow (`add_fact` + `commit_thought`) owns the shared
index and is for a deliberately solo session. The hook already buffers
per session (COG-062) and never touches the index.

---

**The five-second version**: current truth, reusable predicate, short
value + `detail`, lifecycle for changes, one naming style. If you are
narrating — you wanted a report, not a fact.
