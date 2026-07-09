#!/usr/bin/env python3
"""Cogit belief analytics (COG-045): calibration and volatility, read-only.

Answers two auditor questions from data the journal already holds:

- calibration: whose confidence to trust — per confidence band and per
  source type, how many beliefs survived vs were refuted;
- volatility: which knowledge areas keep changing — claim families
  ranked by revision count.

Outcomes are inferred STRUCTURALLY from history (never from message
text): a removed assertion is `refuted` when the removing thought
activates a claim negating its claim, `superseded` when the same thought
adds a belief of the same claim family with a different value (or a
rival on the same claim), `retired` otherwise. Assertions still active
at the ref are `open`.

    python3 analytics.py --repo ~/.cogit-journal/cogit [--ref R] [--json]

Integrations-level (Python only) on public porcelain; promotion to the
core CLI contract is deferred until the report shape proves itself.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from cogit.errors import CogitError, CorruptionError  # noqa: E402
from cogit.repo import Repository  # noqa: E402

BANDS = [  # cookbook bands, docs/claim-modeling.md Rule 4
    ("observed", 9800, 10001),
    ("stated", 9000, 9800),
    ("inferred", 7000, 9000),
    ("hypothesis", 4000, 7000),
    ("speculation", 0, 4000),
]


def band_of(confidence_bps):
    for name, lo, hi in BANDS:
        if lo <= confidence_bps < hi:
            return name
    return "speculation"


def _topo_oldest_first(thoughts):
    pending = {oid: [p for p in t["parents"] if p in thoughts] for oid, t in thoughts.items()}
    done, emitted = set(), []
    while pending:
        ready = sorted(
            (oid for oid, parents in pending.items() if all(p in done for p in parents)),
            key=lambda oid: (thoughts[oid]["timestamp"], oid),
        )
        if not ready:
            raise CorruptionError("analytics: cycle detected in thought graph")
        for oid in ready:
            emitted.append(oid)
            done.add(oid)
            del pending[oid]
    return emitted


def family_key(row):
    return (row["subject"], row["predicate"],
            json.dumps(row["qualifiers"], sort_keys=True, ensure_ascii=False))


def belief_outcomes(repo, ref=None):
    """Classify the lifecycle outcome of every assertion in the ancestry.

    Returns (outcomes, rows, families): outcome per assertion id
    (open|superseded|refuted|retired), the decoded row per assertion id,
    and per-family revision history (oldest first).
    """
    status = repo.status()
    if ref is None and status["thought"] is None:
        return {}, {}, {}
    thought_oid = repo.resolve(ref or "HEAD")
    thoughts = {entry["id"]: entry for entry in repo.log(thought_oid)}
    order = _topo_oldest_first(thoughts)

    rows_by_thought, rows = {}, {}
    for oid in order:
        fact_rows = repo.facts(oid)["facts"]
        rows_by_thought[oid] = {row["assertion"]: row for row in fact_rows}
        for row in fact_rows:
            rows.setdefault(row["assertion"], row)

    outcomes = {}
    families = {}
    for oid in order:
        current = rows_by_thought[oid]
        parent_union = {}
        for parent in thoughts[oid]["parents"]:
            parent_union.update(rows_by_thought.get(parent, {}))
        added = [row for aid, row in current.items() if aid not in parent_union]
        removed = [row for aid, row in parent_union.items() if aid not in current]

        for row in added:
            outcomes.setdefault(row["assertion"], "open")
            families.setdefault(family_key(row), []).append(
                {"assertion": row["assertion"], "object": row["object"],
                 "negation": row["negation"], "thought": oid,
                 "timestamp": thoughts[oid]["timestamp"]})

        added_negates = {row["negates"] for row in added if row["negates"]}
        added_families = {family_key(row): row for row in added}
        # ADR-0014: recorded removal reasons on the thought take precedence
        # for the recognized lifecycle labels; structure outranks labels for
        # refutation, and free-text reasons fall back to structural inference.
        recorded = {entry["assertion"]: entry["reason"]
                    for entry in thoughts[oid].get("removals", [])}
        for row in removed:
            if row["claim"] in added_negates:
                outcomes[row["assertion"]] = "refuted"
                continue
            reason = recorded.get(row["assertion"])
            if reason == "refuted":
                outcomes[row["assertion"]] = "refuted"
                continue
            if reason == "superseded":
                outcomes[row["assertion"]] = "superseded"
                continue
            replacement = added_families.get(family_key(row))
            if replacement is not None:
                outcomes[row["assertion"]] = "superseded"
            else:
                outcomes[row["assertion"]] = "retired"

    active = repo.facts(thought_oid)["facts"]
    for row in active:
        outcomes[row["assertion"]] = "open"
    return outcomes, rows, families


def _bucket():
    return {"n": 0, "open": 0, "superseded": 0, "refuted": 0, "retired": 0,
            "confidence_sum": 0}


def _finish(bucket):
    n = bucket["n"]
    resolved = bucket["open"] + bucket["refuted"]
    return {
        "n": n,
        "open": bucket["open"],
        "superseded": bucket["superseded"],
        "refuted": bucket["refuted"],
        "retired": bucket["retired"],
        "avg_confidence_bps": round(bucket["confidence_sum"] / n) if n else None,
        "survival_rate": round(bucket["open"] / resolved, 3) if resolved else None,
    }


def analyze(repo, ref=None, top=20):
    outcomes, rows, families = belief_outcomes(repo, ref)
    by_band, by_source = {}, {}
    for aid, outcome in outcomes.items():
        row = rows[aid]
        for group, key in ((by_band, band_of(row["confidence_bps"])),
                           (by_source, row["source"])):
            bucket = group.setdefault(key, _bucket())
            bucket["n"] += 1
            bucket[outcome] += 1
            bucket["confidence_sum"] += row["confidence_bps"]

    band_order = [name for name, _lo, _hi in BANDS]
    volatility = []
    for key, revisions in families.items():
        subject, predicate, qualifiers = key
        refuted = sum(1 for r in revisions
                      if outcomes.get(r["assertion"]) == "refuted")
        current = next((f"NOT {r['object']}" if r["negation"] else r["object"]
                        for r in reversed(revisions)
                        if outcomes.get(r["assertion"]) == "open"), None)
        volatility.append({
            "subject": subject,
            "predicate": predicate,
            "qualifiers": json.loads(qualifiers),
            "revisions": len(revisions),
            "refuted": refuted,
            "current_object": current,
            "last_changed": revisions[-1]["timestamp"],
        })
    volatility.sort(key=lambda v: (-v["revisions"], v["subject"], v["predicate"]))

    return {
        "ref": ref or "HEAD",
        "assertions_seen": len(outcomes),
        "calibration_by_band": {name: _finish(by_band[name])
                                for name in band_order if name in by_band},
        "calibration_by_source": {name: _finish(bucket)
                                  for name, bucket in sorted(by_source.items())},
        "volatility": volatility[:top],
    }


def _print_text(report):
    print(f"belief analytics at {report['ref']} "
          f"({report['assertions_seen']} assertions seen)")
    print("\ncalibration by confidence band "
          "(survival = open/(open+refuted); superseded/retired = value churn)")
    header = f"{'band':12} {'n':>4} {'open':>5} {'sup':>4} {'ref':>4} {'ret':>4} {'avg_conf':>8} {'survival':>8}"
    print(header)
    for name, row in report["calibration_by_band"].items():
        survival = "-" if row["survival_rate"] is None else f"{row['survival_rate']:.3f}"
        print(f"{name:12} {row['n']:>4} {row['open']:>5} {row['superseded']:>4} "
              f"{row['refuted']:>4} {row['retired']:>4} {row['avg_confidence_bps']:>8} {survival:>8}")
    print("\ncalibration by source type")
    for name, row in report["calibration_by_source"].items():
        survival = "-" if row["survival_rate"] is None else f"{row['survival_rate']:.3f}"
        print(f"{name:12} {row['n']:>4} {row['open']:>5} {row['superseded']:>4} "
              f"{row['refuted']:>4} {row['retired']:>4} {row['avg_confidence_bps']:>8} {survival:>8}")
    print(f"\nvolatility (top {len(report['volatility'])} claim families by revisions)")
    for entry in report["volatility"]:
        project = entry["qualifiers"].get("project", "-")
        print(f"  {entry['revisions']:>3}x  {entry['subject']} {entry['predicate']} "
              f"[{project}] = {json.dumps(entry['current_object'], ensure_ascii=False)} "
              f"(refuted {entry['refuted']}, last {entry['last_changed']})")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Cogit belief analytics (COG-045)")
    parser.add_argument("--repo", default=os.environ.get("COGIT_REPO", "."))
    parser.add_argument("--ref", default=None)
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = analyze(Repository.open(args.repo), args.ref, top=args.top)
    except CogitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        _print_text(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
