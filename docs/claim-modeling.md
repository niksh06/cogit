# Claim Modeling Cookbook

> Companion: `docs/journal-discipline.md` — the operating rules AROUND
> the journal (when to write, lifecycle duties, hygiene); this file is
> about shaping one claim well.

created_datetime: 2026-07-02T21:40:00+03:00
updated_datetime: 2026-07-02T21:40:00+03:00
status: Draft (COG-032)

## Why this document exists

The subject/predicate/object claim shape is Cogit's semantic backbone.
The schema cannot stop you from writing
`predicate: "observation", object: "<a paragraph of text>"` — but the
moment you do, claim identity, negation, claim-level merge, and
`blame-fact` stop meaning anything. This cookbook is the guidance layer.

## Rule 1: one proposition per claim

A claim is a single falsifiable statement. If you can put "and" in it,
split it.

Bad:

```json
{"subject": "api", "predicate": "status",
 "object": "returns 500 on POST and the timeout is 30s and retries are off"}
```

Good — three claims:

```json
{"subject": "api:/orders", "predicate": "returns_status_on_post", "object": 500}
{"subject": "api:/orders", "predicate": "timeout_seconds", "object": 30}
{"subject": "api:/orders", "predicate": "retries_enabled", "object": false}
```

## Rule 2: the object is a value, not a sentence

The object is what makes rival assertions COMPARABLE. Two assertions
about `{"api:/orders", "timeout_seconds"}` with objects `30` and `60`
form a legible dispute; two prose blobs do not.

- scalars only (string / integer / boolean); no floats by format rule;
- encode magnitudes in the predicate: `timeout_seconds`, `size_bytes`,
  `confidence_source_count`;
- if the value needs a paragraph, you are writing an annotation, not a
  claim (`cogit annotate` exists for exactly that).

## Rule 3: subjects are stable entity URIs

Pick the granularity you will want to `blame` later, and keep it stable:

- `user` — the human you serve;
- `file:src/auth.py`, `fn:src/auth.py#login` — code entities;
- `api:/orders`, `service:billing` — runtime entities;
- `cogit:COG-015`, `doc:prd` — project entities;
- `self` — the agent's own commitments.

Renaming a subject silently splits history (invariant 4: same semantic
text is not automatically the same fact). Prefer adding a qualifier over
inventing a new subject spelling.

Since 0.5.0 both runtimes enforce the slug shape at write time
(COG-073, same discipline as project qualifiers): subjects are
lowercased and internal whitespace becomes `-` before the claim is
hashed — `"OSV Distro Full-Scope Land"` lands as
`osv-distro-full-scope-land`. Punctuation (`:`, `/`, `.`, `#`) is
untouched, so every URI shape above survives. Read filters match
case-insensitively; history written before 0.5.0 stays one family.
Note the example subjects use lowercase (`cogit:cog-015`-style) on new
writes.

## Rule 4: calibrate confidence_bps honestly

Basis points are cheap; miscalibration poisons downstream arbitration.
Working bands:

| Band | Meaning | Typical source |
| --- | --- | --- |
| 9800–10000 | directly observed this session | tool output, file read |
| 9000–9700 | stated by an authority | user statement, spec |
| 7000–8900 | inferred from strong evidence | passing test implies fix |
| 4000–6900 | plausible working hypothesis | design intuition |
| < 4000 | speculation worth recording | brainstorm branch |

A tool observation at 5000 or a hunch at 9900 are both modeling bugs.

## Rule 5: rival assertion vs negation vs removal

Three different moves — pick deliberately:

- **New rival assertion (same claim, different confidence/source):** the
  proposition still stands; you have another view of it. Merge treats
  rivals about one claim as a conflict — that is the feature.
- **Negating claim (`negates: <claim-id>`):** the proposition itself is
  now believed FALSE. Requires removing the original assertion with
  reason `refuted` (invariant 25); commit enforces this. A negation
  asserts ONLY that the proposition is false — it does not assert any
  replacement value (a replacement is a NEW claim). Porcelain renders
  such rows as `NOT <object>` (COG-040) because readers otherwise
  mistake them for active belief in the value.
- **Removal (`remove-fact --reason superseded`):** the fact stopped
  being relevant without being false (config changed, task ended).

Bad: recording "timeout is now 60" as a negation of "timeout is 30".
That is not a refutation — it is a NEW claim (`timeout_seconds`, 60) plus
removal of the old assertion with reason `superseded`.

## Rule 6: qualifiers scope, they do not hide data

Qualifiers distinguish contexts of the same proposition:

```json
{"subject": "api:/orders", "predicate": "timeout_seconds", "object": 30,
 "qualifiers": {"environment": "staging"}}
```

Anti-pattern: `"qualifiers": {"details": "<json blob>"}`. If a qualifier
value needs structure, it is either a separate claim or an annotation.

## Rule 7: what does NOT belong in Cogit

Cogit records committed beliefs, not everything that happened
(`docs/non-goals.md`):

- raw chat transcripts, token streams, tool noise — observability data,
  not beliefs;
- secrets — rejected at the store, never stored (invariant 21);
- retrieval corpora — Cogit is provenance, not retrieval (ADR-0002);
- per-step scratch reasoning — commit checkpoints, not every token of
  thought. A good thought is "decided X because Y", not "called grep".

Heuristic from the COG-012 experiment: if you would not want to `blame`
it in a week, do not commit it as a fact.

## Worked example: a debugging session

```sh
cogit add-fact --kind tool_observation --subject "test:auth_suite" \
  --predicate failing_count --object 3 --source tool:pytest \
  --confidence 10000 --commit
cogit add-fact --kind agent_decision --subject "bug:auth-timeout" \
  --predicate root_cause --object "session refresh races the token TTL" \
  --source agent:session --confidence 7500 --commit
cogit anchor root-cause-found HEAD
# ...fix lands, suite passes; the hypothesis is CONFIRMED — raise via rival:
cogit add-fact --kind agent_decision --subject "bug:auth-timeout" \
  --predicate root_cause --object "session refresh races the token TTL" \
  --source tool:pytest --confidence 9900 --commit -m "root cause confirmed by green suite"
```

The two assertions share one claim; history shows belief strengthening
from 7500 (inference) to 9900 (verified), each with its own source.

## Rule 8: in a shared journal, always set project

One journal serving several projects (the shared-journal setup) needs
project identity on every claim — otherwise `beliefs about X` mixes
codebases. Use the `project` qualifier (`--project cogit`, MCP `project`
arg): subjects stay natural entity URIs, and claim identity still
separates projects because qualifiers are part of the canonical claim.
Filter with `cogit facts --project cogit` or `--subject 'cogit:*'`.

The project qualifier is a **lowercase slug** and both runtimes enforce
it at write time (COG-063): `Aleph`, `aleph` and ` Aleph Prime ` all
normalize to the same slug before the claim is hashed, and read filters
normalize their input the same way. Field lesson: a case-split once
stranded 56 beliefs in a parallel family nobody was reading.

## Rule 9: tasks — track the state, not the content

Cogit works as the provenance substrate of a task tracker, not as the
tracker itself. Model task STATE as beliefs and keep task CONTENT in
documents:

```sh
cogit add-fact --kind agent_decision --subject "task:COG-045" \
  --predicate status --object in_progress --source agent:session \
  --confidence 9600 --project cogit --commit
# on completion: supersede (remove reason=superseded + new belief done)
```

- predicates: `status`, `owner`, `priority` — one belief each; a status
  transition is a supersede, giving the full audited history for free
  (who moved it, when, on what basis — `blame-fact` per transition).
- the spec text, checklists, descriptions live in files
  (`issues/<ID>.md`) or annotations — never in the object (Rule 2).
- queries/boards/sorting are out of scope by ADR-0002: `facts --subject
  'task:*' --project X` is the ceiling, and that is intentional.

## Rule 10: identity — actor is WHO wrote, source is WHERE it came from

Attribution died in practice when everything wrote `actor: "agent"`
(measured: 82 of 87 live assertions). Keep the two identity fields
separate and specific:

- `actor` — a stable identifier of the WRITER instance:
  `fable`, `claude-code-<session8>`, `aleph-agent`. Never plain
  `agent` (the linter flags it). The MCP server defaults the actor to a
  per-session instance id automatically — override with `COGIT_ACTOR`
  when you want a stable name.
- `source` — provenance of the INFORMATION: `tool:pytest`,
  `prompt:owner-decision`, `agent:<role>` for inferences. Do not smuggle
  session identity here; that is what `actor` is for.
- Unforgeable identity (signatures) is deliberately NOT this rule —
  local journals trust the filesystem user; cryptographic attribution
  arrives with sharing (COG-026).

## References

- `docs/spec/object-format-v1.md` — schemas and canonical rules
- `docs/spec/claim-assertion-examples.md` — enforcement of negation flow
- `docs/adr/0008-claim-assertion-model.md`, `docs/adr/0012-annotations.md`
- `issues/COG-032.md`
