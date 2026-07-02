"""Bisect over thought history: find where reasoning first went wrong.

Contract: issues/COG-021.md (closes OQ-009). Probes are non-mutating —
the oracle inspects a candidate thought via env vars, no checkout happens.
"""

import os
import subprocess

from .errors import UserError

GOOD = "good"
BAD = "bad"
SKIP = "skip"


def command_runner(repo, command: str):
    """Oracle runner: exit 0 good, 125 skip, other < 128 bad, >= 128 aborts."""

    def run(thought_oid: str) -> str:
        thought = repo.store.read(thought_oid)
        env = {
            **os.environ,
            "COGIT_THOUGHT": thought_oid,
            "COGIT_MINDSET": thought["mindset"],
            "COGIT_REPO": os.path.dirname(repo.cogit_dir),
        }
        proc = subprocess.run(command, shell=True, env=env, capture_output=True)
        code = proc.returncode
        if code == 0:
            return GOOD
        if code == 125:
            return SKIP
        if 0 < code < 128:
            return BAD
        raise UserError(
            f"bisect-thought: oracle died (exit {code}) on {thought_oid}; aborting"
        )

    return run


def bisect_thought(repo, good: str, bad: str, runner):
    """Binary search for the first bad thought between good and bad.

    Assumes a monotonic predicate along the topological order of thoughts
    reachable from bad but not from good (MVP: linear histories).
    """
    good_oid = repo.resolve(good)
    bad_oid = repo.resolve(bad)
    ancestry_bad = repo._ancestry(bad_oid)
    if good_oid == bad_oid:
        raise UserError("bisect-thought: good and bad are the same thought")
    if good_oid not in ancestry_bad:
        raise UserError("bisect-thought: good must be an ancestor of bad")
    good_set = set(repo._ancestry(good_oid))
    candidates = {oid: t for oid, t in ancestry_bad.items() if oid not in good_set}
    order = repo._topo_oldest_first(candidates)
    # bad is the only candidate without descendants in the set -> emitted last
    assert order[-1] == bad_oid

    verdicts = {bad_oid: BAD}
    log = []
    lo, hi = 0, len(order) - 1
    while lo < hi:
        window = [i for i in range(lo, hi) if order[i] not in verdicts]
        if not window:
            return {
                "result": "inconclusive",
                "first_bad": None,
                "range": order[lo : hi + 1],
                "log": log,
                "candidates": len(order),
            }
        mid = window[len(window) // 2]
        verdict = runner(order[mid])
        log.append({"thought": order[mid], "verdict": verdict})
        verdicts[order[mid]] = verdict
        if verdict == SKIP:
            continue
        if verdict == BAD:
            hi = mid
        else:
            lo = mid + 1

    last_good = max(
        (i for i in range(hi) if verdicts.get(order[i]) == GOOD), default=-1
    )
    suspects = [
        order[i] for i in range(last_good + 1, hi) if verdicts.get(order[i]) == SKIP
    ]
    return {
        "result": "found",
        "first_bad": order[hi],
        "skipped_suspects": suspects,
        "log": log,
        "candidates": len(order),
    }
