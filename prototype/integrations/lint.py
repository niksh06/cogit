#!/usr/bin/env python3
"""Cogit claim-modeling linter (COG-047): cookbook rules, mechanically.

Checks the ACTIVE beliefs of a ref against the checkable subset of
docs/claim-modeling.md. The schema cannot stop prose objects or
date-stamped subjects — this linter names them, because they silently
disable claim identity, supersede chains, volatility and calibration
(first real-world case: COG-045's live run found a neighbour project
with every family stuck at 1 revision).

    python3 lint.py --repo ~/.cogit-journal/cogit [--project X] [--strict]
    python3 lint.py --repo ... --since pre-clean --strict   # ratchet: new debt only

Rules covered: R1 multi-proposition objects, R2 prose objects,
R3 unstable subjects/predicates (dates, whitespace, length),
R4 confidence-band mismatches, R6 blob qualifiers, R8 missing project
qualifier in a shared journal; lifecycle hygiene (COG-058): R11 exact-family
rivalry (competing active values; same-object corroboration is NOT flagged),
R12 singleton-state collisions across families for known state predicates,
R13 advisory lifecycle markers in prose (heuristic, labeled as such).
Baseline ratchet: --since <anchor|ref> classifies findings existing/new;
--strict then fails only on NEW warnings. Read-only, no autofix ever —
remediation is an explicit COG-056 transition.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from cogit.errors import CogitError, UserError  # noqa: E402
from cogit.repo import Repository  # noqa: E402

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
STATE_PREDICATES = frozenset({"status", "state", "owner", "priority", "phase", "stage"})
MARKER_RE = re.compile(
    r"\b(refuted?|supersed\w*|correct(?:ion|ed)|deprecated|obsolete|stale)\b",
    re.IGNORECASE,
)


def check_row(row, shared=True):
    findings = []
    subject, predicate = row["subject"], row["predicate"]
    obj = row["object"]

    def add(rule, severity, message, heuristic=False):
        findings.append({
            "rule": rule, "severity": severity, "assertion": row["assertion"],
            "project": row["qualifiers"].get("project"),
            "subject": subject, "predicate": predicate, "message": message,
            "heuristic": heuristic,
            "key": f"{rule}:{row['assertion']}",
        })

    if isinstance(obj, str):
        words = len(obj.split())
        if words > 12 or len(obj) > 100:
            add("R2-prose-object", "warn",
                f"object is prose ({words} words, {len(obj)} chars) — the object is a "
                "value; long detail belongs in an annotation or a document")
        elif ";" in obj or " and " in obj:
            add("R1-multi-proposition", "warn",
                "object joins several propositions — split into separate claims")
    if DATE_RE.search(subject):
        add("R3-ephemeral-subject", "warn",
            "date inside the subject splits history — dates live in asserted_at or a "
            "qualifier; supersede the same stable subject instead")
    if " " in subject:
        add("R3-subject-whitespace", "warn",
            "subject contains whitespace — use a stable URI-like id")
    elif len(subject) > 60:
        add("R3-subject-length", "info",
            f"subject is {len(subject)} chars — hard to blame later")
    if " " in predicate:
        add("R3-predicate-whitespace", "warn",
            "predicate should be a single snake_case token")
    elif DATE_RE.search(predicate):
        add("R3-ephemeral-predicate", "warn",
            "date inside the predicate splits history")
    confidence = row["confidence_bps"]
    if row["source"] == "tool" and confidence < 9000:
        add("R4-underconfident-observation", "info",
            f"tool observation at {confidence} bps — direct observations sit at 9800+")
    if row["source"] == "agent" and confidence >= 9800 and not row["negation"]:
        add("R4-overconfident-inference", "info",
            f"agent-sourced belief at {confidence} bps — 9800+ is the observation band")
    if row.get("actor") == "agent":
        add("R10-generic-actor", "info",
            "actor 'agent' defeats attribution — use a stable instance id (Rule 10)")
    for key, value in row["qualifiers"].items():
        if isinstance(value, str) and len(value) > 80:
            add("R6-blob-qualifier", "warn",
                f"qualifier '{key}' holds a blob ({len(value)} chars) — that is a "
                "separate claim or an annotation")
    if shared and "project" not in row["qualifiers"]:
        add("R8-missing-project", "warn",
            "shared journal: every claim needs the project qualifier")
    if (isinstance(obj, str) and not row["negation"] and len(obj.split()) > 3
            and MARKER_RE.search(obj)):
        add("R13-advisory-marker", "info",
            "object narrates a lifecycle transition in prose — if the old belief "
            "really changed state, use supersede-fact/refute-fact/retire-fact so "
            "analytics can see it (HEURISTIC: prose match, not evidence of falsity)",
            heuristic=True)
    return findings


def _rival_detail(row):
    return {"assertion": row["assertion"], "claim": row["claim"],
            "object": row["object"], "actor": row.get("actor"),
            "source": row.get("source"), "confidence_bps": row["confidence_bps"]}


def _family_id(row):
    return (row["kind"], row["subject"], row["predicate"],
            json.dumps(row.get("qualifiers", {}), sort_keys=True, ensure_ascii=False))


def hygiene_findings(rows):
    """Lifecycle hygiene candidates (COG-058): structural, read-only.

    R11: one exact family (kind, subject, predicate, qualifiers) holds
    DISTINCT active objects — competing current values. Multiple assertions
    of the same object are corroboration and are never flagged.
    R12: a known singleton-state predicate (status/owner/…) holds distinct
    active values for one subject ACROSS families (e.g. modeled with
    different qualifiers) — R11 cannot see it, a reader still gets two
    answers to one question.
    """
    findings = []
    families = {}
    for row in rows:
        if row["negation"]:
            continue  # an active negation asserts falsity, not a rival value
        families.setdefault(_family_id(row), []).append(row)
    rivalrous_state_groups = set()
    for fam, members in sorted(families.items()):
        objects = sorted({json.dumps(m["object"], ensure_ascii=False) for m in members})
        if len(objects) < 2:
            continue
        head = members[0]
        findings.append({
            "rule": "R11-family-rivalry", "severity": "warn", "heuristic": False,
            "key": "R11:" + "|".join(fam),
            "project": head["qualifiers"].get("project"),
            "subject": head["subject"], "predicate": head["predicate"],
            "message": f"{len(objects)} competing active values in one claim family: "
                       + " | ".join(o[:60] for o in objects)
                       + " — supersede or retire the stale one (COG-056)",
            "rivals": [_rival_detail(m) for m in sorted(members, key=lambda r: r["assertion"])],
        })
        if head["predicate"] in STATE_PREDICATES:
            rivalrous_state_groups.add(
                (head["subject"], head["predicate"], head["qualifiers"].get("project")))
    state_groups = {}
    for row in rows:
        if row["negation"] or row["predicate"] not in STATE_PREDICATES:
            continue
        group = (row["subject"], row["predicate"], row["qualifiers"].get("project"))
        state_groups.setdefault(group, []).append(row)
    for group, members in sorted(state_groups.items()):
        objects = sorted({json.dumps(m["object"], ensure_ascii=False) for m in members})
        spans_families = len({_family_id(m) for m in members}) > 1
        if len(objects) < 2 or not spans_families or group in rivalrous_state_groups:
            continue
        subject, predicate, project = group
        findings.append({
            "rule": "R12-singleton-state", "severity": "warn", "heuristic": False,
            "key": f"R12:{subject}|{predicate}|{project}",
            "project": project, "subject": subject, "predicate": predicate,
            "message": f"singleton-state predicate '{predicate}' answers with "
                       f"{len(objects)} different values across claim families: "
                       + " | ".join(o[:60] for o in objects),
            "rivals": [_rival_detail(m) for m in sorted(members, key=lambda r: r["assertion"])],
        })
    return findings


def _collect_findings(repo, ref, project, shared):
    rows = repo.facts(ref, project=project)["facts"]
    findings = [finding for row in rows for finding in check_row(row, shared=shared)]
    findings.extend(hygiene_findings(rows))
    return rows, findings


def lint(repo, ref=None, project=None, shared=True, since=None):
    status = repo.status()
    if ref is None and status["thought"] is None:
        return {"ref": "HEAD", "facts_checked": 0, "findings": [],
                "by_rule": {}, "by_severity": {}, "warnings": 0, "clean": True}
    rows, findings = _collect_findings(repo, ref, project, shared)
    if since is not None:
        # baseline ratchet (COG-058): old debt is 'existing', regressions 'new'
        since_oid = repo.resolve(since)
        to_oid = repo.resolve(ref or "HEAD")
        if since_oid != to_oid and not repo.is_ancestor(since_oid, to_oid):
            raise UserError(
                f"lint: --since {since} is not an ancestor of {ref or 'HEAD'} — "
                "the baseline must lie on this history")
        _rows, base_findings = _collect_findings(repo, since_oid, project, shared)
        baseline_keys = {f["key"] for f in base_findings}
        for finding in findings:
            finding["age"] = "existing" if finding["key"] in baseline_keys else "new"
    by_rule, by_severity = {}, {}
    for finding in findings:
        by_rule[finding["rule"]] = by_rule.get(finding["rule"], 0) + 1
        by_severity[finding["severity"]] = by_severity.get(finding["severity"], 0) + 1
    warnings = sum(1 for f in findings if f["severity"] == "warn")
    report = {
        "ref": ref or "HEAD",
        "facts_checked": len(rows),
        "findings": findings,
        "by_rule": dict(sorted(by_rule.items())),
        "by_severity": dict(sorted(by_severity.items())),
        "warnings": warnings,
        "clean": not findings,
    }
    if since is not None:
        new = [f for f in findings if f["age"] == "new"]
        report["baseline"] = {
            "since": since,
            "existing": len(findings) - len(new),
            "new": len(new),
            "new_warnings": sum(1 for f in new if f["severity"] == "warn"),
        }
    return report


def shape_report(report, rule=None, severity=None, limit=None, summary=False):
    """Bounded views (COG-058): totals stay exact, only detail rows shrink."""
    shown = report["findings"]
    if rule is not None:
        shown = [f for f in shown if f["rule"] == rule]
    if severity is not None:
        shown = [f for f in shown if f["severity"] == severity]
    matched = len(shown)
    if summary:
        shown = []
    elif limit is not None and limit >= 0:
        shown = shown[:limit]
    shaped = dict(report)
    shaped["findings"] = shown
    shaped["shown"] = len(shown)
    shaped["matched"] = matched
    shaped["truncated"] = matched - len(shown)
    return shaped


def _print_text(report):
    print(f"cogit lint at {report['ref']}: {report['facts_checked']} active beliefs, "
          f"{report['matched'] if 'matched' in report else len(report['findings'])} "
          f"finding(s) ({report['warnings']} warn total)")
    if "baseline" in report:
        base = report["baseline"]
        print(f"  baseline {base['since']}: {base['existing']} existing, "
              f"{base['new']} new ({base['new_warnings']} new warn)")
    for rule, count in report["by_rule"].items():
        print(f"  {count:>4}x {rule}")
    for finding in report["findings"]:
        project = finding["project"] or "-"
        age = f" [{finding['age']}]" if "age" in finding else ""
        print(f"{finding['severity']:4} {finding['rule']:28} [{project}]{age} "
              f"{finding['subject']} {finding['predicate']}: {finding['message']}")
    if report.get("truncated"):
        print(f"  … {report['truncated']} more finding(s) not shown (totals above are exact)")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Cogit claim-modeling linter (COG-047/058)")
    parser.add_argument("--repo", default=os.environ.get("COGIT_REPO", "."))
    parser.add_argument("--ref", default=None)
    parser.add_argument("--project", default=None)
    parser.add_argument("--since", default=None,
                        help="baseline anchor/ref: classify findings existing/new (ratchet)")
    parser.add_argument("--rule", default=None, help="show only this rule's findings")
    parser.add_argument("--severity", default=None, choices=("warn", "info"),
                        help="show only findings of this severity")
    parser.add_argument("--limit", type=int, default=None, help="cap detail rows (totals stay exact)")
    parser.add_argument("--summary", action="store_true", help="totals only, no detail rows")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 on warn findings (with --since: on NEW warns only)")
    args = parser.parse_args(argv)
    try:
        report = lint(Repository.open(args.repo), args.ref, project=args.project,
                      since=args.since)
    except CogitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    shaped = shape_report(report, rule=args.rule, severity=args.severity,
                          limit=args.limit, summary=args.summary)
    if args.json:
        print(json.dumps(shaped, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        _print_text(shaped)
    if args.strict:
        if args.since is not None:
            return 1 if report["baseline"]["new_warnings"] else 0
        return 1 if report["warnings"] else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
