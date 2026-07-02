# ADR-0005: First-introducer blame semantics

created_datetime: 2026-05-26T21:28:00+03:00
updated_datetime: 2026-05-26T21:28:00+03:00
status: Proposed

## Context

Git blame answers a line-oriented question: which commit last changed each line. Cogit facts are not lines in a file, and reasoning provenance needs a different default question: which thought first introduced a fact into the selected ancestry?

If Cogit copies Git blame literally, it will create a misleading product contract. Agent audit usually needs the origin of a belief, not the last checkpoint that still contained it.

## Decision

`blame-fact` returns the first introducing thought for a fact in the selected ancestry.

For MVP:

- input is a fact object ID and optional starting thought/ref;
- traversal walks parent thoughts backward;
- the answer is the earliest thought in that ancestry whose mindset contains the fact while its parent mindset does not;
- linear traversal is acceptable;
- semantic similarity over fact text is out of scope.

Questions about appearance or disappearance over time should use log-style queries, such as future `log --introduced-fact <fact-id>` or `log --removed-fact <fact-id>`.

## Rationale

The audit use case is "why does the agent believe this?" That requires tracing the belief to the thought that introduced it and then to the fact source, not identifying the last state that touched nearby text.

Separating `blame-fact` from log/pickaxe-style queries keeps command semantics honest and testable.

## Consequences

Positive:

- Clearer provenance semantics.
- Simpler MVP implementation.
- Better fit for incident review and reasoning audit.

Negative:

- Renamed or rephrased facts become different histories unless fact identity is stable.
- Confidence-only changes need explicit modeling as new fact objects or assertion objects.
- Future indexes may be required when linear walks become slow.

## Future Work

- `fact -> first_thought` index as a performance layer.
- Pickaxe-style history queries for introduction, removal, and confidence changes.
- Stable structured fact identity for semantically equivalent claims.

## References

- `git/Documentation/git-blame.adoc`
- `git/Documentation/gitdiffcore.adoc`
- `git/blame.c`
