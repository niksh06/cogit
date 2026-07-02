# ADR-0008: Claim and assertion model

created_datetime: 2026-05-27T09:41:00+03:00
updated_datetime: 2026-05-27T09:41:00+03:00
status: Proposed

## Context

Earlier documents used `fact` as a convenient term for an atomic belief. During design review, that proved too coarse. The same proposition can be asserted by multiple sources with different confidence, actors, and methods.

Cogit needs stable proposition identity without losing provenance.

## Decision

Use a claim/assertion model.

- `claim`: a structured typed proposition.
- `assertion`: provenance-bearing evidence about a claim.
- Product-level `fact`: shorthand for an active assertion about a claim.

MVP claim kinds:

- `user_preference`
- `tool_observation`
- `document_claim`
- `agent_decision`
- `policy_constraint`

MVP source types:

- `prompt`
- `tool`
- `file`
- `url`
- `system`
- `manual`
- `agent`

Claims use typed statement shape:

```json
{
  "type": "claim",
  "kind": "user_preference",
  "subject": "user",
  "predicate": "prefers_response_style",
  "object": "brief",
  "qualifiers": {
    "scope": "assistant_reply"
  }
}
```

Assertions carry provenance:

```json
{
  "type": "assertion",
  "claim": "sha256:<claim-id>",
  "status": "asserted",
  "source": {
    "type": "prompt",
    "uri": "conversation:current"
  },
  "confidence_bps": 9200,
  "asserted_at": "2026-05-27T06:41:00Z",
  "actor": "agent",
  "method": {
    "type": "user_statement"
  }
}
```

`confidence_bps` is required and must be an integer from `0` to `10000`.

`actor` is a string in MVP. It may become a structured object later.

`method` is an object. Its exact schema remains minimal and may vary by method type, but it must be canonical JSON.

## Negation And Refutation

Refutation uses a separate negated claim object.

A negated claim must explicitly link to the original:

```json
{
  "type": "claim",
  "kind": "document_claim",
  "subject": "doc:api",
  "predicate": "supports_feature",
  "object": false,
  "negates": "sha256:<original-claim-id>",
  "qualifiers": {
    "feature": "semantic_search"
  }
}
```

If a negated claim becomes active in a mindset, the original active assertion must be removed with reason `refuted`.

Allowed removal reasons:

- `obsolete`
- `refuted`
- `scope_changed`
- `no_longer_relevant`
- `superseded`
- `operator_removed`

Removal reason is staged in `index.json.removed_facts[]` as:

```json
{
  "id": "sha256:<assertion-id>",
  "reason": "refuted"
}
```

## Mindset Semantics

A mindset contains active assertion IDs, not raw claims.

This keeps active state tied to provenance: source, confidence, actor, and method remain inspectable.

Removing an assertion from a mindset means it is no longer active. It does not delete the assertion object.

## Thought Parent Semantics

Thought parent order follows Git-like semantics.

For merge thoughts:

- `parents[0]` is current/ours;
- `parents[1]` is merged/theirs;
- additional merge metadata records base/ours/theirs explicitly.

This favors audit readability over lexicographic parent sorting.

## Rationale

The claim/assertion split prevents source and confidence changes from creating entirely unrelated propositions. It also preserves provenance without forcing retrieval-style semantic matching into the core.

Explicit negation avoids fragile inference from subject/predicate/object similarity.

## Consequences

Positive:

- Stable proposition layer.
- Multiple evidence records for one claim.
- Clear place for confidence and source.
- Better audit behavior for refutation and supersession.

Negative:

- More object types than the first KISS sketch.
- MVP CLI may need to explain "fact" as shorthand.
- Claim schema can become too broad if not kept disciplined.

## References

- `docs/spec/object-format-v1.md`
- `docs/spec/claim-assertion-examples.md`
- `docs/glossary.md`
