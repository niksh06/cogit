# Cogit Invariants

created_datetime: 2026-05-26T21:40:00+03:00
updated_datetime: 2026-05-27T09:41:00+03:00
status: Draft

## Purpose

These invariants are the safety rails for Cogit implementation. If a feature violates one, the feature is wrong or the invariant needs an explicit ADR change.

## Core Invariants

1. Immutable objects never change after publication.
2. Same canonical object bytes always produce the same object ID.
3. Object ID is derived only from `<type> <size>\0<canonical-json>`.
4. Same semantic text is not automatically the same fact.
5. Object reads verify hash and schema before returning data.
6. Object writes reject malformed data.
7. Same object path with different bytes is corruption.
8. Refs are mutable pointers, not committed history.
9. Every `HEAD` or branch movement appends a reflog entry.
10. Ref updates must not silently overwrite a newer ref.
11. The index is staged working memory, not long-term memory.
12. A thought commit is created from the index, not directly from live context.
13. A thought points to a mindset snapshot, not to a diff.
14. `blame-fact` means first introducer in selected ancestry.
15. `diff` is exact fact-set comparison in MVP.
16. `verify` is the authority for repository health.
17. Retrieval and semantic search are not part of Cogit core.
18. Raw object view is authoritative.
19. Overlays, annotations, and replacements must be explicit.
20. Performance layers must be derived and removable without corrupting the repository.
21. Secrets and sensitive data must not be stored in Cogit.
22. Checkout with a non-empty index is blocked in MVP.
23. Prune is not part of MVP.
24. A negated claim must explicitly link to the claim it negates.
25. Activating a negated claim requires removing the original active assertion with reason `refuted`.
26. Assertion premises reference existing assertions only; the derivation graph is acyclic by construction (ADR-0013).

## Mutation Invariants

- Object write may happen before ref update.
- Ref update may fail after object write.
- Failed ref update must not leave a partially written ref.
- Unreachable objects are acceptable.
- Index clear happens only after successful thought commit.
- Merge conflicts block commit until resolved.
- Removed assertions require explicit removal reasons.

## Recovery Invariants

- Reflog can recover recent pointer movement.
- Dangling thoughts are not automatically corruption.
- `verify` reports problems but does not repair them in MVP.
- Manual repair must not rewrite existing object bytes.

## Trust Invariants

- Hash integrity is not actor trust.
- `source` metadata is a claim, not proof.
- Imported objects are untrusted until future verification policy says otherwise.
- Suspected secrets are rejected rather than redacted and written.

## Product Boundary Invariants

- Cogit records committed reasoning provenance.
- Cogit does not decide which context should be retrieved for the next prompt.
- Cogit can feed retrieval systems later, but retrieval systems are not the core store.
