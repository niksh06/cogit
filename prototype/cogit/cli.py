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
    print(json.dumps({"object_id": oid}) if args.json else oid)
    return 0


def cmd_cat_object(args):
    repo = _open_repo(args)
    obj = repo.store.read(repo.expand_object_id(args.object_id))
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
    if args.fact == "-":
        doc = parse_json(sys.stdin.read())
    elif args.fact is not None:
        doc = _load_json_arg(args.fact)
    elif args.kind is not None:
        doc = _build_shorthand_doc(args)
    else:
        raise UserError("add-fact: provide a JSON document, '-' for stdin, or shorthand flags (--kind ...)")

    if args.commit:
        from .index_state import index_is_empty, load_index

        if not index_is_empty(load_index(repo.cogit_dir)):
            raise UserError(
                "add-fact: --commit refuses with a non-empty index (staged facts, removals, "
                "conflicts, or merge in progress) — a micro-commit must not swallow unrelated state"
            )

    claim_oid, assertion_oid = repo.add_fact(doc)
    thought_oid = None
    if args.commit:
        claim = repo.store.read(claim_oid)
        assertion = repo.store.read(assertion_oid)
        message = args.message or f"{claim['kind']}: {claim['subject']} {claim['predicate']}"
        author = args.author or assertion["actor"]
        thought_oid = repo.commit_thought(message, author, args.timestamp)

    if args.json:
        payload = {"claim": claim_oid, "assertion": assertion_oid}
        if thought_oid:
            payload["thought"] = thought_oid
        print(json.dumps(payload, sort_keys=True))
        return 0
    print(f"claim     {claim_oid}")
    print(f"staged    {assertion_oid}")
    if thought_oid:
        print(f"committed {thought_oid}")
    return 0


def cmd_remove_fact(args):
    repo = _open_repo(args)
    oid = repo.expand_object_id(args.assertion_id)
    outcome = repo.remove_fact(oid, args.reason)
    if args.json:
        print(json.dumps({"outcome": outcome, "assertion": oid}, sort_keys=True))
        return 0
    print(f"{outcome}  {oid}")
    return 0


def cmd_commit_thought(args):
    repo = _open_repo(args)
    thought_oid = repo.commit_thought(args.message, args.author, args.timestamp)
    if args.json:
        print(json.dumps({"thought": thought_oid}, sort_keys=True))
        return 0
    print(f"committed {thought_oid}")
    return 0


def cmd_branch(args):
    repo = _open_repo(args)
    if args.name is None:
        branches = repo.list_branches()
        if args.json:
            print(json.dumps(branches, indent=2, sort_keys=True))
            return 0
        for branch in branches:
            marker = "*" if branch["current"] else " "
            print(f"{marker} {branch['name']} {_short(branch['target'])}")
        return 0
    target = repo.branch(args.name, args.thought, actor=args.actor, timestamp=args.timestamp)
    if args.json:
        print(json.dumps({"branch": args.name, "target": target}, sort_keys=True))
        return 0
    print(f"branch {args.name} -> {_short(target)}")
    return 0


def cmd_checkout(args):
    repo = _open_repo(args)
    mode, thought = repo.checkout(args.target, actor=args.actor, timestamp=args.timestamp)
    if args.json:
        print(json.dumps({"mode": mode, "thought": thought}, sort_keys=True))
        return 0
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
        hint = "  (remembered resolution available: --suggested)" if "suggestion" in conflict else ""
        print(f"  ! claim {conflict['claim']}{hint}")
    if status["merge_in_progress"]:
        print("merge in progress")
    return 0


def cmd_log(args):
    repo = _open_repo(args)
    fact_filter = args.introduced_fact or args.removed_fact
    if fact_filter:
        if args.reflog or (args.introduced_fact and args.removed_fact):
            raise UserError("log: --introduced-fact/--removed-fact are mutually exclusive and incompatible with -g")
        wanted = "introduced" if args.introduced_fact else "removed"
        events = [e for e in repo.fact_events(fact_filter, args.ref) if e["event"] == wanted]
        if args.json:
            print(json.dumps(events, indent=2, sort_keys=True))
            return 0
        for event in events:
            print(f"{event['event']}  {event['id']}")
            print(f"author:   {event['author']}")
            print(f"date:     {event['timestamp']}")
            print(f"\n    {event['message']}\n")
        return 0
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
    annotations = repo.annotations_index() if args.annotations else {}
    if args.json:
        if args.annotations:
            thoughts = [{**t, "annotations": annotations.get(t["id"], [])} for t in thoughts]
        print(json.dumps(thoughts, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    for thought in thoughts:
        print(f"thought {thought['id']}")
        if len(thought["parents"]) > 1:
            print(f"merge:    {' '.join(_short(p) for p in thought['parents'])}")
        print(f"author:   {thought['author']}")
        print(f"date:     {thought['timestamp']}")
        print(f"op:       {thought['operation']}")
        print(f"\n    {thought['message']}\n")
        for entry in annotations.get(thought["id"], []):
            _print_annotation(entry, indent="    ")
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
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1 if result.get("conflicts") else 0
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
            if "suggestion" in conflict:
                remembered = conflict["suggestion"]["keep"] or "drop"
                print(f"  remembered resolution: {remembered}")
                print(f"  apply with: cogit resolve {_short(conflict['claim'])} --suggested")
        print("resolve conflicts, then run `cogit commit-thought`")
        return 1
    print("run `cogit commit-thought` to record the merge thought")
    return 0


def cmd_resolve(args):
    repo = _open_repo(args)
    claim = repo.expand_object_id(args.claim_id)
    keep = repo.expand_object_id(args.keep) if args.keep else None
    remaining = repo.resolve_conflict(claim, keep=keep, drop=args.drop, use_suggestion=args.suggested)
    if args.json:
        print(json.dumps({"remaining_conflicts": remaining}, sort_keys=True))
        return 0
    print(f"resolved; {remaining} conflict(s) remaining")
    return 0


def cmd_rerere(args):
    repo = _open_repo(args)
    from .rerere import forget, load_rerere

    if args.forget:
        key = args.forget
        removed = forget(repo.cogit_dir, key)
        if removed == 0 and not key.startswith("sha256:"):
            try:
                removed = forget(repo.cogit_dir, repo.expand_object_id(key))
            except UserError:
                pass
        if args.json:
            print(json.dumps({"forgotten": removed}, sort_keys=True))
            return 0
        print(f"forgot {removed} stored resolution(s)")
        return 0
    store = load_rerere(repo.cogit_dir)
    if args.json:
        print(json.dumps(store, indent=2, sort_keys=True))
        return 0
    if not store:
        print("(no stored resolutions)")
        return 0
    for fingerprint, record in sorted(store.items()):
        outcome = record["keep"] or "drop"
        print(f"{_short(fingerprint)}  claim {_short(record['claim'])}  -> {outcome}  ({record['recorded_at']})")
    return 0


def cmd_blame_fact(args):
    repo = _open_repo(args)
    oid = repo.expand_object_id(args.fact_id)
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


def _print_fact_rows(rows):
    if not rows:
        print("(no active facts)")
        return
    for row in rows:
        neg = " negates!" if row["negates"] else ""
        print(
            f"{_short(row['assertion'])}  {row['kind']}  "
            f"{row['subject']} {row['predicate']} {json.dumps(row['object'], ensure_ascii=False)}"
            f"  conf={row['confidence_bps']} src={row['source']}{neg}"
        )


def cmd_facts(args):
    repo = _open_repo(args)
    result = repo.facts(args.ref)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    print(f"facts at {_short(result['thought'])} ({len(result['facts'])} active)")
    _print_fact_rows(result["facts"])
    return 0


def cmd_recap(args):
    repo = _open_repo(args)
    result = repo.recap(args.source, args.target)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    position = result["position"]
    where = f"branch {position['branch']}" if not position["detached"] else "detached HEAD"
    print(f"recap {_short(result['from'])} -> {_short(result['to'])} ({len(result['thoughts'])} thought(s))")
    for thought in result["thoughts"]:
        print(f"  {_short(thought['id'])} {thought['timestamp']} {thought['operation']:7} {thought['message']}")
    print(f"beliefs: +{len(result['added'])} -{len(result['removed'])}")
    for row in result["added"]:
        print(f"  + {row['kind']}  {row['subject']} {row['predicate']} "
              f"{json.dumps(row['object'], ensure_ascii=False)}  conf={row['confidence_bps']}")
    for row in result["removed"]:
        print(f"  - {row['kind']}  {row['subject']} {row['predicate']} "
              f"{json.dumps(row['object'], ensure_ascii=False)}")
    merge_note = ", merge in progress" if position["merge_in_progress"] else ""
    print(f"position: {where} at {_short(position['thought'])}{merge_note}")
    return 0


def cmd_show(args):
    repo = _open_repo(args)
    result = repo.show(args.ref)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    print(f"thought {result['id']}")
    if len(result["parents"]) > 1:
        print(f"merge:    {' '.join(_short(p) for p in result['parents'])}")
    print(f"author:   {result['author']}")
    print(f"date:     {result['timestamp']}")
    print(f"op:       {result['operation']}")
    print(f"\n    {result['message']}\n")
    _print_fact_rows(result["facts"])
    return 0


def cmd_annotate(args):
    repo = _open_repo(args)
    annotation_oid = repo.annotate(
        args.target, args.message, namespace=args.namespace,
        author=args.author, timestamp=args.timestamp,
    )
    if args.json:
        print(json.dumps({"annotation": annotation_oid, "namespace": args.namespace}, sort_keys=True))
        return 0
    print(f"annotated {annotation_oid} ({args.namespace})")
    return 0


def _print_annotation(entry, indent=""):
    print(f"{indent}[{entry['namespace']}] {_short(entry['id'])} {entry['author']} {entry['created_at']}")
    print(f"{indent}  {entry['body']}")


def cmd_annotations(args):
    repo = _open_repo(args)
    entries = repo.annotations_for(args.target, namespace=args.namespace)
    if args.json:
        print(json.dumps(entries, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    if not entries:
        print("(no annotations)")
        return 0
    for entry in entries:
        _print_annotation(entry)
    return 0


def cmd_reflog_expire(args):
    repo = _open_repo(args)
    if bool(args.ref) == bool(args.all):
        raise UserError("reflog-expire: pass exactly one of --ref <name> or --all")
    keep = args.keep
    if keep is None:
        from .maintenance import _thresholds  # config-backed default

        keep = _thresholds(repo.cogit_dir).get("reflogRetainEntries")
        if keep is None:
            raise UserError("reflog-expire: no --keep given and no [maintenance] reflogRetainEntries configured")
    names = list(repo.refs.list_reflogs()) if args.all else [args.ref]
    results = []
    for name in names:
        kept, dropped = repo.refs.expire_reflog(name, keep, dry_run=args.dry_run)
        results.append({"ref": name, "kept": kept, "dropped": dropped})
    if args.json:
        print(json.dumps({"dry_run": args.dry_run, "results": results}, indent=2, sort_keys=True))
        return 0
    for row in results:
        action = "would drop" if args.dry_run else "dropped"
        print(f"{row['ref']}: {action} {row['dropped']}, kept {row['kept']}")
    if args.dry_run:
        print("dry run: nothing was changed")
    return 0


def cmd_count_objects(args):
    repo = _open_repo(args)
    from .maintenance import count_objects

    result = count_objects(repo)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    types = ", ".join(f"{t} {n}" for t, n in sorted(result["by_type"].items()) if n)
    print(f"objects:  {result['loose_objects']} loose ({types or 'none'}), {result['corrupt_objects']} corrupt")
    print(f"disk:     {result['disk_bytes']} bytes")
    print(f"refs:     {result['heads']} heads, {result['anchors']} anchors")
    print(f"reflog:   {result['reflog_entries']} entries, {result['reflog_bytes']} bytes")
    print(f"tmp:      {result['tmp_files']} stale files")
    for warning in result["warnings"]:
        print(f"warning: {warning}")
    return 0


def cmd_bisect_thought(args):
    repo = _open_repo(args)
    from .bisect import bisect_thought, command_runner

    result = bisect_thought(repo, args.good, args.bad, command_runner(repo, args.run))
    log_lines = [f"{entry['thought']} {entry['verdict']}" for entry in result["log"]]
    if args.log_file:
        with open(args.log_file, "w", encoding="utf-8") as handle:
            handle.write(f"# bisect-thought good={args.good} bad={args.bad} run={args.run}\n")
            handle.write("\n".join(log_lines) + "\n")
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["result"] == "found" else 1
    for line in log_lines:
        print(line)
    if result["result"] == "inconclusive":
        print("inconclusive: every remaining candidate was skipped")
        for oid in result["range"]:
            print(f"  ? {oid}")
        return 1
    thought = repo.store.read(result["first_bad"])
    print(f"first bad thought: {result['first_bad']}")
    print(f"message:  {thought['message']}")
    print(f"author:   {thought['author']}")
    print(f"date:     {thought['timestamp']}")
    for oid in result["skipped_suspects"]:
        print(f"warning: skipped candidate could be earlier: {oid}")
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
        anchors = repo.list_anchors()
        if args.json:
            print(json.dumps(anchors, indent=2, sort_keys=True))
            return 0
        for anchor in anchors:
            print(f"{anchor['name']} -> {_short(anchor['target'])} (anchor {_short(anchor['anchor'])})")
        return 0
    if args.thought_id is None:
        raise UserError("anchor: usage `cogit anchor <name> <thought-id>`")
    anchor_oid = repo.anchor(args.name, args.thought_id, author=args.author, timestamp=args.timestamp)
    if args.json:
        print(json.dumps({"name": args.name, "anchor": anchor_oid}, sort_keys=True))
        return 0
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
    p.add_argument("--json", action="store_true")
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
    p.add_argument("--commit", action="store_true", help="commit a thought immediately (micro-commit)")
    p.add_argument("--message", "-m", help="thought message for --commit (default: derived from claim)")
    p.add_argument("--author", help="thought author for --commit (default: assertion actor)")
    p.add_argument("--timestamp", help="thought timestamp for --commit (tests)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_add_fact)

    p = sub.add_parser("remove-fact", help="stage removal of an active assertion")
    p.add_argument("assertion_id")
    p.add_argument("--reason", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_remove_fact)

    p = sub.add_parser("commit-thought", help="commit staged facts as a thought")
    p.add_argument("--message", "-m", required=True)
    p.add_argument("--author", required=True)
    p.add_argument("--timestamp", help="ISO-8601 UTC override (tests)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_commit_thought)

    p = sub.add_parser("branch", help="create a branch (or list branches)")
    p.add_argument("name", nargs="?")
    p.add_argument("thought", nargs="?")
    p.add_argument("--actor", default="agent")
    p.add_argument("--timestamp")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_branch)

    p = sub.add_parser("checkout", help="switch HEAD to a branch or detach at a thought")
    p.add_argument("target")
    p.add_argument("--actor", default="agent")
    p.add_argument("--timestamp")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_checkout)

    p = sub.add_parser("status", help="show current position and staged state")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("log", help="walk thought history (or reflog with -g)")
    p.add_argument("-g", dest="reflog", action="store_true", help="walk reflog instead of ancestry")
    p.add_argument("ref", nargs="?")
    p.add_argument("--introduced-fact", metavar="FACT_ID", help="thoughts that introduced this fact")
    p.add_argument("--removed-fact", metavar="FACT_ID", help="thoughts that removed this fact")
    p.add_argument("--annotations", action="store_true", help="display annotations inline")
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
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser("resolve", help="resolve a recorded merge conflict for a claim")
    p.add_argument("claim_id")
    p.add_argument("--keep", help="assertion id to keep")
    p.add_argument("--drop", action="store_true", help="keep none of the candidates")
    p.add_argument("--suggested", action="store_true", help="apply the remembered resolution (rerere)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_resolve)

    p = sub.add_parser("rerere", help="list or forget remembered conflict resolutions")
    p.add_argument("--forget", metavar="CLAIM_OR_FINGERPRINT", help="forget stored resolutions")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_rerere)

    p = sub.add_parser("blame-fact", help="first thought that introduced a fact")
    p.add_argument("fact_id")
    p.add_argument("ref", nargs="?")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_blame_fact)

    p = sub.add_parser("annotate", help="append an annotation to a thought/assertion/claim")
    p.add_argument("target")
    p.add_argument("--message", "-m", required=True)
    p.add_argument("--namespace", default="notes")
    p.add_argument("--author", default="agent")
    p.add_argument("--timestamp")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_annotate)

    p = sub.add_parser("annotations", help="list annotations for a target (newest first)")
    p.add_argument("target", nargs="?")
    p.add_argument("--namespace")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_annotations)

    p = sub.add_parser("reflog-expire", help="trim reflogs to the newest N entries (explicit, destructive)")
    p.add_argument("--keep", type=int, help="entries to keep (default: [maintenance] reflogRetainEntries)")
    p.add_argument("--ref", help="one reflog name, e.g. HEAD or refs/heads/main")
    p.add_argument("--all", action="store_true", help="expire every reflog")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_reflog_expire)

    p = sub.add_parser("count-objects", help="repository pressure metrics (never mutates)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_count_objects)

    p = sub.add_parser("bisect-thought", help="binary-search the first bad thought between good and bad")
    p.add_argument("--good", required=True, help="known-good thought or ref")
    p.add_argument("--bad", required=True, help="known-bad thought or ref")
    p.add_argument("--run", required=True, help="oracle command: exit 0 good, 125 skip, else bad; gets COGIT_THOUGHT/COGIT_MINDSET/COGIT_REPO env")
    p.add_argument("--log", dest="log_file", help="write a replayable probe log to this file")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_bisect_thought)

    p = sub.add_parser("facts", help="list active facts of a thought (default: HEAD)")
    p.add_argument("ref", nargs="?")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_facts)

    p = sub.add_parser("recap", help="belief-state digest between two points (context recovery)")
    p.add_argument("source", help="anchor, ref, or thought to recap from")
    p.add_argument("target", nargs="?", help="default: HEAD")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_recap)

    p = sub.add_parser("show", help="thought header plus its active facts")
    p.add_argument("ref", nargs="?")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("verify", help="check repository health (reports, never repairs)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("anchor", help="record a named milestone (or list anchors)")
    p.add_argument("name", nargs="?")
    p.add_argument("thought_id", nargs="?")
    p.add_argument("--author", default="agent")
    p.add_argument("--timestamp")
    p.add_argument("--json", action="store_true")
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
