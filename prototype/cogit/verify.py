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
        elif obj["type"] == "annotation":
            target = obj["target"]
            if target not in objects:
                _finding(findings, "error", "missing-annotation-target",
                         f"{oid} annotates missing object {target}")
            elif objects[target]["type"] not in ("thought", "assertion", "claim"):
                _finding(findings, "error", "bad-annotation-target",
                         f"{oid} annotates a {objects[target]['type']}")
            for parent in obj["parents"]:
                check_link(oid, parent, "annotation", "missing-annotation-parent")

    # -- removal provenance consistency (ADR-0014) ---------------------------------
    def mindset_of(thought_oid):
        thought = objects.get(thought_oid)
        if thought is None or thought.get("type") != "thought":
            return set()
        mindset = objects.get(thought["mindset"])
        if mindset is None or mindset.get("type") != "mindset":
            return set()
        return set(mindset["assertions"])

    for oid, obj in sorted(objects.items()):
        if obj["type"] != "thought" or "removals" not in obj:
            continue
        own = mindset_of(oid)
        parent_union = set()
        for parent in obj["parents"]:
            parent_union |= mindset_of(parent)
        recorded = {entry["assertion"] for entry in obj["removals"]}
        for aid in sorted(recorded):
            if aid in own:
                _finding(findings, "error", "removal-not-removed",
                         f"{oid} records removal of {aid} but its mindset still holds it")
            elif aid not in parent_union:
                _finding(findings, "error", "removal-not-in-parents",
                         f"{oid} records removal of {aid} which no parent mindset held")
        if len(obj["parents"]) == 1:
            uncovered = sorted(parent_union - own - recorded)
            if uncovered:
                _finding(findings, "warning", "removals-incomplete",
                         f"{oid} removed {len(uncovered)} assertion(s) without a recorded reason")

    # -- contradictory mindsets (invariants 24-25; warning, not corruption) --------
    for oid, obj in sorted(objects.items()):
        if obj["type"] != "mindset":
            continue
        active_claims = set()
        for aid in obj["assertions"]:
            assertion = objects.get(aid)
            if assertion is not None and assertion["type"] == "assertion":
                active_claims.add(assertion["claim"])
        for claim_oid in sorted(active_claims):
            claim = objects.get(claim_oid)
            if claim is not None and claim.get("negates") in active_claims:
                _finding(
                    findings, "warning", "contradictory-mindset",
                    f"{oid} holds a claim and its negation together "
                    f"({claim_oid} negates {claim['negates']})",
                )

    # -- HEAD and refs -------------------------------------------------------------
    reachable_tips = []
    try:
        kind, value = repo.refs.read_head()
        if kind == "detached":
            if check_link("HEAD", value, "thought", "bad-head"):
                reachable_tips.append(value)
    except CogitError as exc:
        _finding(findings, "error", "bad-head", str(exc))

    # notes refs: target type + chain namespace consistency (ADR-0012)
    try:
        for refname, target in repo.refs.list_refs("refs/notes"):
            namespace = refname.rsplit("/", 1)[-1]
            if not check_link(refname, target, "annotation", "bad-ref-target"):
                continue
            tip = target
            seen = set()
            while tip is not None and tip not in seen and tip in objects:
                seen.add(tip)
                annotation = objects[tip]
                if annotation["namespace"] != namespace:
                    _finding(findings, "error", "namespace-mismatch",
                             f"{tip} carries namespace '{annotation['namespace']}' but is reachable from {refname}")
                parents = annotation["parents"]
                tip = parents[0] if parents else None
    except CogitError as exc:
        _finding(findings, "error", "bad-ref", str(exc))

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
