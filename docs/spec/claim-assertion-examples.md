# Claim And Assertion Examples

created_datetime: 2026-05-27T09:41:00+03:00
updated_datetime: 2026-05-27T09:41:00+03:00
status: Draft

## Purpose

These examples show the intended claim/assertion model before implementation. They are not final hash test vectors yet. Final vectors must include canonical JSON, preimage bytes, and SHA-256 object IDs.

## Example 1: User Preference

Claim:

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

Assertion:

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

Meaning: the agent records a user preference with high confidence because the user stated it.

## Example 2: Tool Observation

Claim:

```json
{
  "type": "claim",
  "kind": "tool_observation",
  "subject": "file:/Users/nsh/Downloads/cogit/docs/open-questions.md",
  "predicate": "has_status",
  "object": "Draft",
  "qualifiers": {
    "field": "status"
  }
}
```

Assertion:

```json
{
  "type": "assertion",
  "claim": "sha256:<claim-id>",
  "status": "asserted",
  "source": {
    "type": "file",
    "uri": "file:/Users/nsh/Downloads/cogit/docs/open-questions.md"
  },
  "confidence_bps": 10000,
  "asserted_at": "2026-05-27T06:41:00Z",
  "actor": "agent",
  "method": {
    "type": "read_file",
    "tool": "ReadFile"
  }
}
```

Meaning: the assertion is grounded in a file read, not in model inference alone.

## Example 3: Agent Decision

Claim:

```json
{
  "type": "claim",
  "kind": "agent_decision",
  "subject": "cogit:mvp",
  "predicate": "first_implementation_slice",
  "object": "object_store",
  "qualifiers": {
    "language": "rust"
  }
}
```

Assertion:

```json
{
  "type": "assertion",
  "claim": "sha256:<claim-id>",
  "status": "asserted",
  "source": {
    "type": "manual",
    "uri": "conversation:design-session"
  },
  "confidence_bps": 10000,
  "asserted_at": "2026-05-27T06:41:00Z",
  "actor": "user",
  "method": {
    "type": "explicit_selection"
  }
}
```

Meaning: the product decision came from an explicit user selection.

## Example 4: Policy Constraint

Claim:

```json
{
  "type": "claim",
  "kind": "policy_constraint",
  "subject": "cogit:mvp",
  "predicate": "forbids_storage_of",
  "object": "secrets",
  "qualifiers": {
    "scope": "objects,reflogs,thought_messages"
  }
}
```

Assertion:

```json
{
  "type": "assertion",
  "claim": "sha256:<claim-id>",
  "status": "asserted",
  "source": {
    "type": "manual",
    "uri": "conversation:design-session"
  },
  "confidence_bps": 10000,
  "asserted_at": "2026-05-27T06:41:00Z",
  "actor": "user",
  "method": {
    "type": "explicit_selection"
  }
}
```

Meaning: the no-secrets rule is part of the product contract.

## Example 5: Refutation

Original claim:

```json
{
  "type": "claim",
  "kind": "document_claim",
  "subject": "doc:cogit-mvp",
  "predicate": "supports_feature",
  "object": "semantic_search",
  "qualifiers": {}
}
```

Negated claim:

```json
{
  "type": "claim",
  "kind": "document_claim",
  "subject": "doc:cogit-mvp",
  "predicate": "supports_feature",
  "object": false,
  "negates": "sha256:<original-claim-id>",
  "qualifiers": {
    "feature": "semantic_search"
  }
}
```

Removal staged in index:

```json
{
  "id": "sha256:<original-assertion-id>",
  "reason": "refuted"
}
```

Meaning: activating the negated assertion requires removing the original active assertion with explicit reason.

## Future Test Vector Fields

Each finalized example should add:

- canonical JSON bytes;
- preimage bytes;
- SHA-256 object ID;
- zlib reproducibility check.
