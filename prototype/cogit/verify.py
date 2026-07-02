"""Repository health check (docs/spec/repository-layout-v1.md, ADR-0004).

Reports problems; never repairs. Errors mean corruption (exit 3);
warnings alone leave the repository healthy (exit 0).
"""

import os

from .errors import CogitError, CorruptionError, UserError
from .index_state import load_index
from .objects import is_oid
from .refs import validate_ref_name


def _finding(findings, severity, code, message):
    findings.append({"severity": severity, "code": code, "message": message})


def verify_repository(repo):
    """Return a list of findings for a Repository instance."""
    findings = []
    cogit = repo.cogit_dir

    for required in ("HEAD", "config", "index.json"):
        if not os.path.isfile(os.path.join(cogit, required)):
            _finding(findings, "error", "missing-file", f"required file missing: {required}")
    for required_dir in ("objects", "refs/heads", "logs"):
        if not os.path.isdir(os.path.join(cogit, *required_dir.split("/"))):
            _finding(findings, "error", "missing-dir", f"required directory missing: {required_dir}")

    # -- objects: full read verification, collect typed graph --------------------
    objects = {}
    objects_dir = os.path.join(cogit, "objects")
    if os.path.isdir(objects_dir):
        for fanout in sorted(os.listdir(objects_dir)):
            fanout_dir = os.path.join(objects_dir, fanout)
            if not os.path.isdir(fanout_dir):
                continue
            for rest in sorted(os.listdir(fanout_dir)):
                oid = f"sha256:{fanout}{rest}"
                if not is_oid(oid):
                    _finding(findings, "error", "bad-path", f"objects/{fanout}/{rest} is not a valid fanout path")
                    continue
                try:
                    objects[oid] = repo.store.read(oid)
                except CogitError as exc:
                    _finding(findings, "error", "corrupt-object", str(exc))

    def check_link(owner, oid, expected_type, code):
        if oid not in objects:
            _finding(findings, "error", code, f"{owner} references missing object {oid}")
            return False
        if objects[oid]["type"] != expected_type:
            _finding(
                findings, "error", code,
                f"{owner} references {oid} of type {objects[oid]['type']}, expected {expected_type}",
            )
            return False
        return True

    for oid, obj in sorted(objects.items()):
        if obj["type"] == "thought":
            for parent in obj["parents"]:
                check_link(oid, parent, "thought", "missing-parent")
            check_link(oid, obj["mindset"], "mindset", "missing-mindset")
        elif obj["type"] == "mindset":
            for aid in obj["assertions"]:
                check_link(oid, aid, "assertion", "missing-assertion")
        elif obj["type"] == "assertion":
            check_link(oid, obj["claim"], "claim", "missing-claim")
        elif obj["type"] == "claim" and "negates" in obj:
            check_link(oid, obj["negates"], "claim", "missing-negated-claim")
        elif obj["type"] == "anchor":
            check_link(oid, obj["target"], "thought", "missing-anchor-target")

    # -- HEAD and refs -------------------------------------------------------------
    reachable_tips = []
    try:
        kind, value = repo.refs.read_head()
        if kind == "detached":
            if check_link("HEAD", value, "thought", "bad-head"):
                reachable_tips.append(value)
    except CogitError as exc:
        _finding(findings, "error", "bad-head", str(exc))

    for prefix, expected in (("refs/heads", "thought"), ("refs/anchors", "anchor")):
        try:
            for refname, target in repo.refs.list_refs(prefix):
                try:
                    validate_ref_name(refname)
                except UserError as exc:
                    _finding(findings, "error", "bad-ref-name", str(exc))
                    continue
                if check_link(refname, target, expected, "bad-ref-target"):
                    if expected == "thought":
                        reachable_tips.append(target)
                    else:
                        reachable_tips.append(objects[target]["target"])
        except CogitError as exc:
            _finding(findings, "error", "bad-ref", str(exc))

    # -- index -----------------------------------------------------------------------
    try:
        index = load_index(cogit)
        for aid in index["staged_facts"]:
            if aid not in objects:
                _finding(findings, "error", "index-missing-object", f"index stages missing object {aid}")
        if index["base_mindset"] is not None and index["base_mindset"] not in objects:
            _finding(findings, "error", "index-missing-object", f"index base mindset missing: {index['base_mindset']}")
    except CorruptionError as exc:
        _finding(findings, "error", "bad-index", str(exc))

    # -- reflogs ---------------------------------------------------------------------
    logs_dir = os.path.join(cogit, "logs")
    if os.path.isdir(logs_dir):
        for dirpath, _dirs, files in os.walk(logs_dir):
            for filename in files:
                rel = os.path.relpath(os.path.join(dirpath, filename), cogit)
                logname = rel.replace(os.sep, "/")[len("logs/") :]
                try:
                    repo.refs.read_reflog(logname)
                except CogitError as exc:
                    _finding(findings, "error", "bad-reflog", str(exc))

    # -- dangling thoughts (warning, not corruption) -----------------------------------
    reachable = set()
    stack = list(reachable_tips)
    while stack:
        oid = stack.pop()
        if oid in reachable or oid not in objects:
            continue
        reachable.add(oid)
        stack.extend(objects[oid].get("parents", []))
    for oid, obj in sorted(objects.items()):
        if obj["type"] == "thought" and oid not in reachable:
            _finding(findings, "warning", "dangling-thought", f"{oid} is not reachable from any ref")

    return findings
