#!/usr/bin/env python3
"""Cogit project health (COG-059): one bounded read-only document.

Aggregates the existing read-only surfaces — verify, analytics, lint,
project-scoped dump — into ONE call sized for a context window: exact
totals, top-N bounded detail, compact previews for long prose. This is
the preferred re-anchor for JOURNAL QUALITY questions; `dump` remains
the full-state reader.

    python3 health.py --repo ~/.cogit-journal/cogit --project cogit [--since A]

On a shared journal `project` is required (never silently mix projects);
a single-project journal may omit it. Unknown project returns an empty
scoped document naming the project — not a global fallback.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from cogit import __version__  # noqa: E402
from cogit.errors import CogitError, UserError  # noqa: E402
from cogit.repo import Repository, compact_rows, normalize_project_slug  # noqa: E402
from cogit.verify import verify_repository  # noqa: E402

from analytics import analyze  # noqa: E402
from lint import lint as run_lint  # noqa: E402

HYGIENE_RULES = ("R11-family-rivalry", "R12-singleton-state", "R13-advisory-marker")

WRITER_SCAN_LIMIT = 50  # newest thoughts consulted for version-skew detection


def _semver_key(version):
    """Comparable (major, minor, patch) or None for non-semver tokens."""
    parts = version.split("+", 1)[0].split(".")
    if len(parts) != 3:
        return None
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        return None


def _writer_report(writers, reader_version):
    """ADR-0016: pick the newest stamped writer and flag reader skew.

    Returns (newest_writer, skew_message_or_None). Only semver-parseable
    stamps compete; a journal ahead of this reader is the actionable case
    (the stale-MCP/stale-container failure mode), older writers are normal.
    """
    newest = None
    newest_key = None
    for token in writers:
        key = _semver_key(token.partition("/")[2])
        if key is not None and (newest_key is None or key > newest_key):
            newest, newest_key = token, key
    reader_key = _semver_key(reader_version)
    if newest_key is not None and reader_key is not None and newest_key > reader_key:
        skew = (f"journal holds thoughts written by {newest}, this reader is "
                f"cogit-py/{reader_version} — restart or upgrade stale readers "
                "(MCP servers, containers)")
        return newest, skew
    return newest, None


def health(repo, project=None, since=None, top=10):
    project = normalize_project_slug(project) if project else project
    status = repo.status()
    rows = repo.facts()["facts"] if status["thought"] else []
    projects = sorted({(row["qualifiers"] or {}).get("project")
                       for row in rows if (row["qualifiers"] or {}).get("project")})
    if project is None:
        if len(projects) > 1:
            raise UserError(
                "health: this journal holds several projects "
                f"({', '.join(projects)}) — pass project=<slug>; mixing them "
                "silently would misstate every count")
        project = projects[0] if projects else None

    scoped_rows = [row for row in rows
                   if project is None
                   or (row["qualifiers"] or {}).get("project") == project]

    findings = verify_repository(repo)
    integrity = {
        "healthy": not any(f["severity"] == "error" for f in findings),
        "errors": sum(1 for f in findings if f["severity"] == "error"),
        "warnings": sum(1 for f in findings if f["severity"] == "warning"),
    }

    report = analyze(repo, project=project)
    outcome_totals = {"open": 0, "superseded": 0, "refuted": 0, "retired": 0}
    for bucket in report["calibration_by_band"].values():
        for key in outcome_totals:
            outcome_totals[key] += bucket[key]

    lint_report = run_lint(repo, project=project, since=since)
    candidates = [f for f in lint_report["findings"] if f["rule"] in HYGIENE_RULES]
    for candidate in candidates:
        compact_rows(candidate.get("rivals", []), max_chars=80)

    dump = repo.dump(project=project, log_limit=1, compact=True)
    last_thought = dump["log"][0] if dump["log"] else None
    recent_writers = [row["writer"] for row in repo.log()[:WRITER_SCAN_LIMIT]
                      if row.get("writer")] if status["thought"] else []
    newest_writer, version_skew = _writer_report(recent_writers, __version__)
    anchors = repo.list_anchors()
    newest_anchor = (max(anchors, key=lambda a: (a["created_at"], a["name"]))
                     if anchors else None)

    active_negations = sum(1 for row in scoped_rows if row["negation"])
    revised_families = sum(1 for f in report["volatility"] if f["revisions"] > 1)

    doc = {
        "project": project,
        # COG-070: name the reader build — version skew is invisible otherwise
        "reader": "cogit-py/" + __version__,
        # ADR-0016: newest stamped writer among recent thoughts (None = pre-0.3.0 history)
        "newest_writer": newest_writer,
        "projects_in_journal": projects,
        "integrity": integrity,
        "beliefs": {
            "active": len(scoped_rows),
            "active_negations": active_negations,
            "outcomes": outcome_totals,
            "families": len(report["volatility"]),
            "revised_families": revised_families,
        },
        "lint": {
            "findings": len(lint_report["findings"]),
            "warnings": lint_report["warnings"],
            "by_rule": lint_report["by_rule"],
            "baseline": lint_report.get("baseline"),
        },
        "lifecycle_candidates": {
            "total": len(candidates),
            "top": candidates[: max(0, top)],
        },
        "last_project_thought": last_thought,
        "newest_anchor": newest_anchor,
        "top_volatile_families": report["volatility"][: max(0, top)],
    }
    if version_skew:
        doc["version_skew"] = version_skew
    return doc


def main(argv=None):
    parser = argparse.ArgumentParser(description="Cogit project health (COG-059)")
    parser.add_argument("--repo", default=os.environ.get("COGIT_REPO", "."))
    parser.add_argument("--project", default=None)
    parser.add_argument("--since", default=None, help="lint baseline anchor/ref (ratchet)")
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args(argv)
    try:
        doc = health(Repository.open(args.repo), project=args.project,
                     since=args.since, top=args.top)
    except CogitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
