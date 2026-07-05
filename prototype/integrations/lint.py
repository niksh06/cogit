#!/usr/bin/env python3
"""Cogit claim-modeling linter (COG-047): cookbook rules, mechanically.

Checks the ACTIVE beliefs of a ref against the checkable subset of
docs/claim-modeling.md. The schema cannot stop prose objects or
date-stamped subjects — this linter names them, because they silently
disable claim identity, supersede chains, volatility and calibration
(first real-world case: COG-045's live run found a neighbour project
with every family stuck at 1 revision).

    python3 lint.py --repo ~/.cogit-journal/cogit [--project X] [--strict]

Rules covered: R1 multi-proposition objects, R2 prose objects,
R3 unstable subjects/predicates (dates, whitespace, length),
R4 confidence-band mismatches, R6 blob qualifiers, R8 missing project
qualifier in a shared journal. Read-only; exit 1 only with --strict and
warnings present.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from cogit.errors import CogitError  # noqa: E402
from cogit.repo import Repository  # noqa: E402

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def check_row(row, shared=True):
    findings = []
    subject, predicate = row["subject"], row["predicate"]
    obj = row["object"]

    def add(rule, severity, message):
        findings.append({
            "rule": rule, "severity": severity, "assertion": row["assertion"],
            "project": row["qualifiers"].get("project"),
            "subject": subject, "predicate": predicate, "message": message,
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
    for key, value in row["qualifiers"].items():
        if isinstance(value, str) and len(value) > 80:
            add("R6-blob-qualifier", "warn",
                f"qualifier '{key}' holds a blob ({len(value)} chars) — that is a "
                "separate claim or an annotation")
    if shared and "project" not in row["qualifiers"]:
        add("R8-missing-project", "warn",
            "shared journal: every claim needs the project qualifier")
    return findings


def lint(repo, ref=None, project=None, shared=True):
    status = repo.status()
    if ref is None and status["thought"] is None:
        return {"ref": "HEAD", "facts_checked": 0, "findings": [],
                "by_rule": {}, "warnings": 0, "clean": True}
    rows = repo.facts(ref, project=project)["facts"]
    findings = [finding for row in rows for finding in check_row(row, shared=shared)]
    by_rule = {}
    for finding in findings:
        by_rule[finding["rule"]] = by_rule.get(finding["rule"], 0) + 1
    warnings = sum(1 for f in findings if f["severity"] == "warn")
    return {
        "ref": ref or "HEAD",
        "facts_checked": len(rows),
        "findings": findings,
        "by_rule": dict(sorted(by_rule.items())),
        "warnings": warnings,
        "clean": not findings,
    }


def _print_text(report):
    print(f"cogit lint at {report['ref']}: {report['facts_checked']} active beliefs, "
          f"{len(report['findings'])} finding(s) ({report['warnings']} warn)")
    for rule, count in report["by_rule"].items():
        print(f"  {count:>4}x {rule}")
    for finding in report["findings"]:
        project = finding["project"] or "-"
        print(f"{finding['severity']:4} {finding['rule']:28} [{project}] "
              f"{finding['subject']} {finding['predicate']}: {finding['message']}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Cogit claim-modeling linter (COG-047)")
    parser.add_argument("--repo", default=os.environ.get("COGIT_REPO", "."))
    parser.add_argument("--ref", default=None)
    parser.add_argument("--project", default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 when warn-level findings exist")
    args = parser.parse_args(argv)
    try:
        report = lint(Repository.open(args.repo), args.ref, project=args.project)
    except CogitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        _print_text(report)
    return 1 if (args.strict and report["warnings"]) else 0


if __name__ == "__main__":
    sys.exit(main())
