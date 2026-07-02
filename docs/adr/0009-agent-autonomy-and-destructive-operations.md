# ADR-0009: Agent autonomy and destructive operations

created_datetime: 2026-05-27T09:41:00+03:00
updated_datetime: 2026-05-27T09:41:00+03:00
status: Proposed

## Context

Cogit is designed for agents to use directly. If every operation needs human approval, the system is not useful as an agent-local cognitive VCS. If destructive operations are too easy, the audit log loses value.

We need a clear boundary between autonomous append-oriented actions and operations requiring explicit human confirmation.

## Decision

The agent may perform these MVP operations autonomously:

- `init`
- `add-fact` / add assertion
- `commit-thought`
- `branch`
- `checkout`
- `status`
- `log`
- `diff`
- `blame-fact`
- `verify`
- `anchor`

Destructive or history-risking operations are constrained:

- Checkout with a non-empty index is blocked in MVP.
- Future stash may make this smoother, but MVP does not auto-stash.
- Safe repair in MVP is limited to recreating an empty index and cleaning stale temp files.
- `verify` diagnoses; it does not repair.
- Prune is not part of MVP.
- Future unreachable-object deletion requires `verify` plus explicit confirmation.
- Rewrite, replace, graft, and rebase-like behavior are out of scope unless explicitly designed.

## Secrets Policy

Secrets and sensitive data must not be stored in Cogit.

Sensitive data includes:

- credentials;
- tokens;
- private keys;
- passwords;
- personal data;
- confidential documents;
- customer data.

If the agent suspects a secret in a claim, assertion, source, thought message, or reflog reason, it must reject the write rather than redact and store.

Rationale: redaction can fail and still persist sensitive fragments in immutable objects or reflogs.

## Garbage Collection

MVP has no prune command.

Unreachable objects are acceptable. They support recovery from failed ref updates, detached reasoning, and abandoned branches.

Future pruning must require:

- clean `verify`;
- dry-run output;
- explicit confirmation;
- protection for anchors and retained reflog targets.

## Rationale

Append-oriented operations preserve auditability and are safe for agent autonomy. Destructive operations need a higher bar because they can erase recovery paths or hide mistakes.

Blocking dirty-index checkout mirrors the conservative version-control behavior Cogit needs before a stash design exists.

## Consequences

Positive:

- Agents can use Cogit without constant human approval.
- Destructive behavior is hard to trigger accidentally.
- Secret policy is simple and conservative.

Negative:

- MVP may feel strict when switching branches with staged state.
- Secret detection details remain hard.
- Operators must handle some recovery manually.

## References

- `docs/recovery-playbook.md`
- `docs/threat-model.md`
- `docs/non-goals.md`
- `docs/open-questions.md`
