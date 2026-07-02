# ADR-0002: Cogit is provenance, not retrieval memory

created_datetime: 2026-05-26T21:28:00+03:00
updated_datetime: 2026-05-26T21:28:00+03:00
status: Proposed

## Context

The agent memory ecosystem already has strong patterns for retrieval memory: checkpoints, session stores, vector search, graph memory, and context assembly. Cogit should not compete with those systems as another way to retrieve relevant memories.

The useful Git-inspired niche is different: a local, inspectable, content-addressed audit trail of what an agent committed as state, which reasoning checkpoint introduced it, and how active hypothesis pointers moved over time.

## Decision

Cogit is a provenance system for agent state and reasoning, not a retrieval memory system.

Cogit answers questions such as:

- What did the agent believe at this thought?
- Which thought first introduced this fact?
- Which source did the fact claim to come from?
- How did `HEAD` or a hypothesis branch move?
- Which branch or detached thought can recover an abandoned reasoning path?

Cogit does not answer, in the MVP:

- Which memories are semantically relevant to the next prompt?
- Which facts should be embedded or reranked?
- How should context be assembled for a model call?
- How should conversational history be compressed?

Retrieval systems may read from Cogit later, but they are separate layers.

## Rationale

Git's deepest architectural lesson is not "store everything forever"; it is "make committed state content-addressed, move refs deliberately, and derive history queries from that graph." Cogit should copy that lesson for agent reasoning.

If Cogit tries to be both provenance and retrieval, it will inherit two conflicting optimization targets. Provenance wants immutable, inspectable, auditable records. Retrieval wants semantic compression, ranking, rewriting, and query latency. Keeping the boundary clear preserves the strongest product idea.

## Consequences

Positive:

- Clearer positioning for pet-project, open-source, and enterprise use.
- Smaller MVP surface.
- Better fit for local debugging, incident review, and reproducible agent decisions.
- Easier integration with existing memory systems as an audit backend.

Negative:

- Cogit will not make an agent "remember better" by itself.
- Users may need an adapter to pair Cogit with a retrieval memory layer.
- Product messaging must avoid generic "agent memory" claims.

## References

- `docs/adr/0001-cogit-kiss-filesystem-architecture.md`
- `docs/prd/cogit-mvp.md`
- `git/Documentation/glossary-content.adoc`
- `git/Documentation/gitcore-tutorial.adoc`
