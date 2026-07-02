"""Cogit CLI (docs/spec/cli-contract.md). Porcelain over Repository operations."""

import argparse
import json
import os
import sys

from .canonical import parse_json
from .errors import CogitError, UserError
from .objects import CLAIM_KINDS
from .repo import Repository, init_repository, now_utc
from .verify import verify_repository


def _short(oid):
    return oid[len("sha256:") : len("sha256:") + 12] if oid else "null"


def _load_json_arg(value: str):
    """Accept inline JSON or a path to a JSON file."""
    if os.path.isfile(value):
        with open(value, "r", encoding="utf-8") as handle:
            return parse_json(handle.read())
    stripped = value.strip()
    if stripped.startswith("{"):
        try:
            return parse_json(stripped)
        except ValueError as exc:
            raise UserError(f"invalid JSON input: {exc}") from exc
    raise UserError(f"'{value}' is neither a JSON object nor an existing file")


def _open_repo(args) -> Repository:
    return Repository.open(args.repo or ".")


# -- command handlers ------------------------------------------------------------


def cmd_init(args):
    path = args.path or "."
    cogit_dir = init_repository(path)
    print(f"initialized cogit repository at {cogit_dir}")
    return 0


def cmd_hash_object(args):
    obj = _load_json_arg(args.file)
    if not isinstance(obj, dict):
        raise UserError("hash-object: input must be a JSON object")
    obj.setdefault("type", args.type)
    if obj["type"] != args.type:
        raise UserError(f"hash-object: --type {args.type} does not match object type {obj['type']}")
    if args.write:
        repo = _open_repo(args)
        oid = repo.store.write(obj)
    else:
        from .objects import encode_object

        oid, _preimage = encode_object(obj)
    print(oid)
    return 0


def cmd_cat_object(args):
    repo = _open_repo(args)
    obj = repo.store.read(args.object_id if args.object_id.startswith("sha256:") else "sha256:" + args.object_id)
    print(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


def _build_shorthand_doc(args):
    """Build a claim+assertion document from add-fact shorthand flags (COG-027)."""
    required = {"--kind": args.kind, "--subject": args.subject, "--predicate": args.predicate,
                "--source": args.source, "--confidence": args.confidence}
    missing = [flag for flag, value in required.items() if value is None]
    if args.object_value is None and args.object_json is None:
        missing.append("--object (or --object-json)")
    if missing:
        raise UserError(f"add-fact: shorthand form requires {', '.join(missing)}")
    if args.object_value is not None and args.object_json is not None:
        raise UserError("add-fact: use either --object or --object-json, not both")

    obj_value = args.object_value if args.object_value is not None else parse_json(args.object_json)
    qualifiers = {}
    for pair in args.qualifier or []:
        if "=" not in pair:
            raise UserError(f"add-fact: --qualifier expects K=V, got '{pair}'")
        key, value = pair.split("=", 1)
        qualifiers[key] = value
    source_type, _sep, source_uri = args.source.partition(":")
    source = {"type": source_type}
    if source_uri:
        source["uri"] = source_uri

    claim = {
        "type": "claim",
        "kind": args.kind,
        "subject": args.subject,
        "predicate": args.predicate,
        "object": obj_value,
        "qualifiers": qualifiers,
    }
    if args.negates:
        claim["negates"] = args.negates if args.negates.startswith("sha256:") else "sha256:" + args.negates
    assertion = {
        "type": "assertion",
        "status": "asserted",
        "source": source,
        "confidence_bps": args.confidence,
        "asserted_at": args.asserted_at or now_utc(),
        "actor": args.actor,
        "method": {"type": args.method},
    }
    return {"claim": claim, "assertion": assertion}


def cmd_add_fact(args):
    repo = _open_repo(args)
    if args.fact is not None and args.kind is not None:
        raise UserError("add-fact: use either a JSON document or shorthand flags, not both")
    if args.fact is not None:
        doc = _load_json_arg(args.fact)
    elif args.kind is not None:
        doc = _build_shorthand_doc(args)
    else:
        raise UserError("add-fact: provide a JSON document or shorthand flags (--kind ...)")
    claim_oid, assertion_oid = repo.add_fact(doc)
    print(f"claim     {claim_oid}")
    print(f"staged    {assertion_oid}")
    return 0


def cmd_remove_fact(args):
    repo = _open_repo(args)
    oid = args.assertion_id if args.assertion_id.startswith("sha256:") else "sha256:" + args.assertion_id
    outcome = repo.remove_fact(oid, args.reason)
    print(f"{outcome}  {oid}")
    return 0


def cmd_commit_thought(args):
    repo = _open_repo(args)
    thought_oid = repo.commit_thought(args.message, args.author, args.timestamp)
    print(f"committed {thought_oid}")
    return 0


def cmd_branch(args):
    repo = _open_repo(args)
    if args.name is None:
        for branch in repo.list_branches():
            marker = "*" if branch["current"] else " "
            print(f"{marker} {branch['name']} {_short(branch['target'])}")
        return 0
    target = repo.branch(args.name, args.thought, actor=args.actor, timestamp=args.timestamp)
    print(f"branch {args.name} -> {_short(target)}")
    return 0


def cmd_checkout(args):
    repo = _open_repo(args)
    mode, thought = repo.checkout(args.target, actor=args.actor, timestamp=args.timestamp)
    if mode == "branch":
        print(f"switched to branch {args.target} at {_short(thought)}")
    else:
        print(f"detached HEAD at {_short(thought)}")
    return 0


def cmd_status(args):
    repo = _open_repo(args)
    status = repo.status()
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
        return 0
    if status["detached"]:
        print(f"detached HEAD at {_short(status['thought'])}")
    else:
        print(f"on branch {status['branch']} at {_short(status['thought'])}")
    print(f"staged facts:   {len(status['staged'])}")
    for oid in status["staged"]:
        print(f"  + {oid}")
    print(f"removed facts:  {len(status['removed'])}")
    for entry in status["removed"]:
        print(f"  - {entry['id']} ({entry['reason']})")
    print(f"conflicts:      {len(status['conflicts'])}")
    for conflict in status["conflicts"]:
        print(f"  ! claim {conflict['claim']}")
    if status["merge_in_progress"]:
        print("merge in progress")
    return 0


def cmd_log(args):
    repo = _open_repo(args)
    if args.reflog:
        entries = repo.reflog(args.ref or "HEAD")
        if args.json:
            print(json.dumps(entries, indent=2, sort_keys=True))
            return 0
        for i, entry in enumerate(entries):
            print(
                f"{_short(entry['new'])} {args.ref or 'HEAD'}@{{{i}}}: {entry['op']}: {entry['reason']}"
                f" ({entry['actor']} {entry['ts']}, was {_short(entry['old']) if entry['old'] != 'null' else 'null'})"
            )
        return 0
    thoughts = repo.log(args.ref)
    if args.json:
        print(json.dumps(thoughts, indent=2, sort_keys=True))
        return 0
    for thought in thoughts:
        print(f"thought {thought['id']}")
        if len(thought["parents"]) > 1:
            print(f"merge:    {' '.join(_short(p) for p in thought['parents'])}")
        print(f"author:   {thought['author']}")
        print(f"date:     {thought['timestamp']}")
        print(f"op:       {thought['operation']}")
        print(f"\n    {thought['message']}\n")
    return 0


def cmd_diff(args):
    repo = _open_repo(args)
    result = repo.diff(args.a, args.b)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    for oid in result["added"]:
        print(f"+ {oid}")
    for oid in result["removed"]:
        print(f"- {oid}")
    if args.unchanged:
        for oid in result["unchanged"]:
            print(f"= {oid}")
    return 0


def cmd_merge(args):
    repo = _open_repo(args)
    result = repo.merge(args.target, actor=args.actor, timestamp=args.timestamp)
    if result["result"] == "already-up-to-date":
        print("already up to date")
        return 0
    if result["result"] == "fast-forward":
        print(f"fast-forward to {_short(result['thought'])}")
        return 0
    print(f"merge staged: +{len(result['staged'])} -{len(result['removed'])}")
    if result["conflicts"]:
        for conflict in result["conflicts"]:
            print(f"CONFLICT claim {conflict['claim']}")
            print(f"  ours:   {conflict['ours']}")
            print(f"  theirs: {conflict['theirs']}")
        print("resolve conflicts, then run `cogit commit-thought`")
        return 1
    print("run `cogit commit-thought` to record the merge thought")
    return 0


def cmd_resolve(args):
    repo = _open_repo(args)
    claim = args.claim_id if args.claim_id.startswith("sha256:") else "sha256:" + args.claim_id
    keep = None
    if args.keep:
        keep = args.keep if args.keep.startswith("sha256:") else "sha256:" + args.keep
    remaining = repo.resolve_conflict(claim, keep=keep, drop=args.drop)
    print(f"resolved; {remaining} conflict(s) remaining")
    return 0


def cmd_blame_fact(args):
    repo = _open_repo(args)
    oid = args.fact_id if args.fact_id.startswith("sha256:") else "sha256:" + args.fact_id
    result = repo.blame_fact(oid, args.ref)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    print(f"introduced by {result['thought']}")
    print(f"message:  {result['message']}")
    print(f"author:   {result['author']}")
    print(f"date:     {result['timestamp']}")
    print(f"claim:    {result['claim']}")
    print(f"source:   {json.dumps(result['source'], sort_keys=True)}")
    return 0


def cmd_verify(args):
    repo = _open_repo(args)
    findings = verify_repository(repo)
    if args.json:
        print(json.dumps(findings, indent=2, sort_keys=True))
    else:
        for finding in findings:
            print(f"{finding['severity']}: [{finding['code']}] {finding['message']}")
    errors = [f for f in findings if f["severity"] == "error"]
    if errors:
        print(f"verify: {len(errors)} error(s) detected")
        return 3
    print("verify: repository is healthy" + (f" ({len(findings)} warning(s))" if findings else ""))
    return 0


def cmd_anchor(args):
    repo = _open_repo(args)
    if args.name is None:
        for anchor in repo.list_anchors():
            print(f"{anchor['name']} -> {_short(anchor['target'])} (anchor {_short(anchor['anchor'])})")
        return 0
    if args.thought_id is None:
        raise UserError("anchor: usage `cogit anchor <name> <thought-id>`")
    anchor_oid = repo.anchor(args.name, args.thought_id, author=args.author, timestamp=args.timestamp)
    print(f"anchor {args.name} {anchor_oid}")
    return 0


# -- parser -------------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(
        prog="cogit",
        description="Cogit: version control for agent cognition and reasoning provenance.",
    )
    parser.add_argument("--repo", help="repository path (default: nearest .cogit upward)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create a .cogit repository")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("hash-object", help="compute (and optionally write) an object id")
    p.add_argument("--type", required=True, choices=["claim", "assertion", "mindset", "thought", "anchor"])
    p.add_argument("--write", action="store_true")
    p.add_argument("file", help="JSON file or inline JSON")
    p.set_defaults(func=cmd_hash_object)

    p = sub.add_parser("cat-object", help="print a decoded, verified object")
    p.add_argument("object_id")
    p.set_defaults(func=cmd_cat_object)

    p = sub.add_parser("add-fact", help="write claim+assertion and stage the assertion")
    p.add_argument("fact", nargs="?", help='JSON file or inline {"claim": {...}, "assertion": {...}}')
    p.add_argument("--kind", choices=list(CLAIM_KINDS), help="shorthand: claim kind")
    p.add_argument("--subject", help="shorthand: claim subject")
    p.add_argument("--predicate", help="shorthand: claim predicate")
    p.add_argument("--object", dest="object_value", help="shorthand: claim object (string)")
    p.add_argument("--object-json", help="shorthand: claim object as JSON (bool/int/string)")
    p.add_argument("--qualifier", action="append", metavar="K=V", help="shorthand: claim qualifier (repeatable)")
    p.add_argument("--negates", help="shorthand: claim id this claim negates")
    p.add_argument("--source", help="shorthand: source as type[:uri], e.g. agent:session-x")
    p.add_argument("--confidence", type=int, help="shorthand: confidence in basis points (0-10000)")
    p.add_argument("--actor", default="agent", help="shorthand: asserting actor")
    p.add_argument("--method", default="cli", help="shorthand: method type")
    p.add_argument("--asserted-at", dest="asserted_at", help="shorthand: ISO-8601 UTC override (default: now)")
    p.set_defaults(func=cmd_add_fact)

    p = sub.add_parser("remove-fact", help="stage removal of an active assertion")
    p.add_argument("assertion_id")
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_remove_fact)

    p = sub.add_parser("commit-thought", help="commit staged facts as a thought")
    p.add_argument("--message", "-m", required=True)
    p.add_argument("--author", required=True)
    p.add_argument("--timestamp", help="ISO-8601 UTC override (tests)")
    p.set_defaults(func=cmd_commit_thought)

    p = sub.add_parser("branch", help="create a branch (or list branches)")
    p.add_argument("name", nargs="?")
    p.add_argument("thought", nargs="?")
    p.add_argument("--actor", default="agent")
    p.add_argument("--timestamp")
    p.set_defaults(func=cmd_branch)

    p = sub.add_parser("checkout", help="switch HEAD to a branch or detach at a thought")
    p.add_argument("target")
    p.add_argument("--actor", default="agent")
    p.add_argument("--timestamp")
    p.set_defaults(func=cmd_checkout)

    p = sub.add_parser("status", help="show current position and staged state")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("log", help="walk thought history (or reflog with -g)")
    p.add_argument("-g", dest="reflog", action="store_true", help="walk reflog instead of ancestry")
    p.add_argument("ref", nargs="?")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_log)

    p = sub.add_parser("diff", help="compare two thoughts or mindsets")
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--unchanged", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_diff)

    p = sub.add_parser("merge", help="conservative fact-set merge into HEAD")
    p.add_argument("target")
    p.add_argument("--actor", default="agent")
    p.add_argument("--timestamp")
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser("resolve", help="resolve a recorded merge conflict for a claim")
    p.add_argument("claim_id")
    p.add_argument("--keep", help="assertion id to keep")
    p.add_argument("--drop", action="store_true", help="keep none of the candidates")
    p.set_defaults(func=cmd_resolve)

    p = sub.add_parser("blame-fact", help="first thought that introduced a fact")
    p.add_argument("fact_id")
    p.add_argument("ref", nargs="?")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_blame_fact)

    p = sub.add_parser("verify", help="check repository health (reports, never repairs)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("anchor", help="record a named milestone (or list anchors)")
    p.add_argument("name", nargs="?")
    p.add_argument("thought_id", nargs="?")
    p.add_argument("--author", default="agent")
    p.add_argument("--timestamp")
    p.set_defaults(func=cmd_anchor)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CogitError as exc:
        print(f"cogit {args.command}: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    sys.exit(main())
