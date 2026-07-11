#!/usr/bin/env python3
"""Cogit derivation-graph queries (COG-050): taint and support, read-only.

The premises field (ADR-0013) makes beliefs a DAG. Two questions that
graph answers:

- `taint`: a source turned out poisoned (broken tool, prompt injection,
  wrong document) — which conclusions rest on it, transitively? Output
  is ready to feed a recall cascade (refute/retire with explicit ids).
- `support`: how strong is the evidence behind a conclusion? Maximin /
  widest-path semantics — the classic Dijkstra relative: over all
  derivation paths from evidence leaves to the conclusion, take the one
  whose WEAKEST link is strongest; report that bottleneck.

    python3 derivation.py --repo ~/.cogit-journal/cogit taint <id|source-uri>
    python3 derivation.py --repo ... support <assertion-id>

Integrations-level (Python, like analytics/lint/health); core-CLI
promotion once the query shapes stabilize. Cycles are impossible by
construction (content addressing), so the DFS needs no cycle guard.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from cogit.errors import CogitError, UserError  # noqa: E402
from cogit.repo import Repository  # noqa: E402


def _corpus(repo, ref=None, history=False):
    """Assertion rows in scope: the ref's ACTIVE beliefs, or (history=True)
    everything the ancestry ever held. Returns (rows_by_id, active_ids)."""
    status = repo.status()
    if ref is None and status["thought"] is None:
        return {}, set()
    thought_oid = repo.resolve(ref or "HEAD")
    active = repo.mindset_assertions(thought_oid)
    ids = set(active)
    if history:
        for thought in repo.log(thought_oid):
            ids |= repo.mindset_assertions(thought["id"])
    return {aid: repo.fact_row(aid) for aid in ids}, active


def _adoption(rows):
    with_premises = sum(1 for row in rows.values() if row.get("premises"))
    return {"assertions": len(rows), "with_premises": with_premises,
            "share": round(with_premises / len(rows), 3) if rows else 0.0}


def _seed_ids(repo, rows, source):
    """A taint seed is an assertion id/prefix OR a source-uri substring —
    'this tool/document/session was poisoned' taints everything it fed."""
    try:
        oid = repo.expand_object_id(source)
        return {oid}, "assertion"
    except CogitError:
        pass
    needle = source.lower()
    seeds = {aid for aid, row in rows.items()
             if needle in f"{row['source']}:{row['source_uri'] or ''}".lower()}
    return seeds, "source"


def taint(repo, source, ref=None, history=False):
    rows, active = _corpus(repo, ref=ref, history=history)
    seeds, matched_by = _seed_ids(repo, rows, source)
    if not seeds:
        raise UserError(
            f"taint: '{source}' matches no assertion id and no source uri in scope")
    # reverse premise edges over the corpus: premise -> dependents
    dependents = {}
    for aid, row in rows.items():
        for premise in row.get("premises", []):
            dependents.setdefault(premise, set()).add(aid)
    depth = {aid: 0 for aid in seeds}
    queue = sorted(seeds)
    while queue:
        current = queue.pop(0)
        for dependent in sorted(dependents.get(current, ())):
            if dependent not in depth:
                depth[dependent] = depth[current] + 1
                queue.append(dependent)
    tainted = [
        {**rows[aid], "depth": level, "active": aid in active}
        for aid, level in sorted(depth.items(), key=lambda kv: (kv[1], kv[0]))
        if aid in rows and level > 0
    ]
    return {
        "source": source,
        "matched_by": matched_by,
        "seeds": sorted(seeds),
        "tainted": tainted,
        "total": len(tainted),
        "adoption": _adoption(rows),
    }


def support(repo, assertion_id, ref=None):
    """Maximin evidence strength: max over derivation paths of the min
    confidence along the path. Premises are read from the immutable
    objects, so superseded evidence still counts as the recorded basis;
    inactive links are flagged in the chain."""
    target = repo.expand_object_id(assertion_id)
    _rows, active = _corpus(repo, ref=ref)
    memo = {}

    def strength(aid):
        if aid in memo:
            return memo[aid]
        row = repo.fact_row(aid)
        own = row["confidence_bps"]
        premises = row.get("premises", [])
        if not premises:
            memo[aid] = (own, [aid])
            return memo[aid]
        best_value, best_path = -1, []
        for premise in sorted(premises):
            value, path = strength(premise)
            if value > best_value:
                best_value, best_path = value, path
        memo[aid] = (min(own, best_value), [aid] + best_path)
        return memo[aid]

    value, path = strength(target)
    chain = []
    for aid in path:
        row = repo.fact_row(aid)
        chain.append({
            "assertion": aid,
            "subject": row["subject"],
            "predicate": row["predicate"],
            "confidence_bps": row["confidence_bps"],
            "active": aid in active,
        })
    bottleneck = min(chain, key=lambda link: link["confidence_bps"])
    return {
        "assertion": target,
        "support_bps": value,
        "bottleneck": bottleneck["assertion"],
        "chain": chain,
        "premise_count": len(repo.fact_row(target).get("premises", [])),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Cogit derivation queries (COG-050)")
    parser.add_argument("--repo", default=os.environ.get("COGIT_REPO", "."))
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("taint", help="downstream closure of a poisoned assertion/source")
    p.add_argument("source", help="assertion id/prefix, or a source-uri substring")
    p.add_argument("--ref", default=None)
    p.add_argument("--history", action="store_true")
    p = sub.add_parser("support", help="maximin (bottleneck) evidence strength")
    p.add_argument("assertion_id")
    p.add_argument("--ref", default=None)
    args = parser.parse_args(argv)
    try:
        repo = Repository.open(args.repo)
        if args.command == "taint":
            doc = taint(repo, args.source, ref=args.ref, history=args.history)
        else:
            doc = support(repo, args.assertion_id, ref=args.ref)
    except CogitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
