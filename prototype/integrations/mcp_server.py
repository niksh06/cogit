#!/usr/bin/env python3
"""Cogit MCP server (COG-029): stdio JSON-RPC, zero dependencies.

One server per journal. The repository comes from $COGIT_REPO (or --repo);
it is initialized on first use if missing. The tool surface mirrors the
agent-facing porcelain; destructive maintenance (prune, reflog-expire,
rerere --forget) is NOT exposed per ADR-0009.

Register with Claude Code:

    claude mcp add cogit -e COGIT_REPO=$HOME/.cogit-journal/my-project \
        -- python3 /ABS/PATH/prototype/integrations/mcp_server.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from cogit import __version__  # noqa: E402
from cogit.bisect import bisect_thought, command_runner  # noqa: E402
from cogit.errors import CogitError  # noqa: E402
from cogit.repo import Repository, init_repository  # noqa: E402
from cogit.verify import verify_repository  # noqa: E402

PROTOCOL_FALLBACK = "2024-11-05"

OID = {"type": "string", "description": "object id (sha256:<hex> or unique prefix >= 6 hex chars)"}
REF = {"type": "string", "description": "branch, anchor, HEAD, or thought id"}


def _schema(properties, required=()):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


TOOLS = [
    {
        "name": "add_fact",
        "description": (
            "Record a belief: write a claim and a provenance-bearing assertion, stage it, and "
            "optionally commit a thought immediately (micro-commit). One proposition per claim; "
            "object is a value, not a sentence."
        ),
        "inputSchema": _schema(
            {
                "kind": {"type": "string", "enum": [
                    "user_preference", "tool_observation", "document_claim",
                    "agent_decision", "policy_constraint"]},
                "subject": {"type": "string"},
                "predicate": {"type": "string"},
                "object": {"type": ["string", "integer", "boolean"]},
                "qualifiers": {"type": "object"},
                "negates": {**OID, "description": "claim id this claim negates"},
                "source": {"type": "string", "description": "type[:uri], e.g. agent:session-x"},
                "confidence_bps": {"type": "integer", "minimum": 0, "maximum": 10000},
                "actor": {"type": "string", "default": "agent"},
                "method": {"type": "string", "default": "mcp"},
                "commit": {"type": "boolean", "description": "commit a thought immediately"},
                "message": {"type": "string", "description": "thought message when commit=true"},
            },
            required=("kind", "subject", "predicate", "object", "source", "confidence_bps"),
        ),
    },
    {
        "name": "remove_fact",
        "description": "Stage removal of an active assertion with an explicit reason (e.g. refuted, superseded).",
        "inputSchema": _schema({"assertion_id": OID, "reason": {"type": "string"}},
                               required=("assertion_id", "reason")),
    },
    {
        "name": "commit_thought",
        "description": "Commit staged facts as a reasoning checkpoint (thought).",
        "inputSchema": _schema(
            {"message": {"type": "string"}, "author": {"type": "string", "default": "agent"}},
            required=("message",),
        ),
    },
    {
        "name": "status",
        "description": "Current position: branch/detached, staged facts, conflicts, merge state.",
        "inputSchema": _schema({}),
    },
    {
        "name": "facts",
        "description": "Active beliefs of a thought (default HEAD) with decoded claim content.",
        "inputSchema": _schema({"ref": REF}),
    },
    {
        "name": "recap",
        "description": (
            "Context recovery: thoughts and net belief changes between a past point "
            "(anchor/thought) and now. Use this first when resuming work."
        ),
        "inputSchema": _schema({"from": REF, "to": REF}, required=("from",)),
    },
    {
        "name": "log",
        "description": "Thought history, newest first.",
        "inputSchema": _schema({"ref": REF, "limit": {"type": "integer", "minimum": 1}}),
    },
    {
        "name": "blame_fact",
        "description": "Which thought FIRST introduced this fact, and from which source.",
        "inputSchema": _schema({"fact_id": OID, "ref": REF}, required=("fact_id",)),
    },
    {
        "name": "diff",
        "description": "Exact fact-set difference between two thoughts or mindsets.",
        "inputSchema": _schema({"a": REF, "b": REF}, required=("a", "b")),
    },
    {
        "name": "branch",
        "description": "Create a hypothesis branch at a thought (or list branches when name is omitted).",
        "inputSchema": _schema({"name": {"type": "string"}, "thought": REF}),
    },
    {
        "name": "checkout",
        "description": "Switch to a branch or detach at a thought. Blocked while the index is dirty.",
        "inputSchema": _schema({"target": REF}, required=("target",)),
    },
    {
        "name": "merge",
        "description": (
            "Conservative claim-level merge of another branch into HEAD. Conflicts are recorded, "
            "never auto-resolved; remembered resolutions are suggested but must be applied via resolve."
        ),
        "inputSchema": _schema({"target": REF}, required=("target",)),
    },
    {
        "name": "resolve",
        "description": "Resolve one recorded merge conflict: keep an assertion, drop all, or apply the remembered suggestion.",
        "inputSchema": _schema(
            {
                "claim_id": OID,
                "keep": OID,
                "drop": {"type": "boolean"},
                "suggested": {"type": "boolean"},
            },
            required=("claim_id",),
        ),
    },
    {
        "name": "anchor",
        "description": "Mark a milestone thought with a fixed name (or list anchors when name is omitted).",
        "inputSchema": _schema({"name": {"type": "string"}, "thought_id": REF}),
    },
    {
        "name": "annotate",
        "description": "Attach a post-hoc note (review verdict, eval result) to a thought/assertion/claim without rewriting it.",
        "inputSchema": _schema(
            {
                "target": OID,
                "message": {"type": "string"},
                "namespace": {"type": "string", "default": "notes"},
                "author": {"type": "string", "default": "agent"},
            },
            required=("target", "message"),
        ),
    },
    {
        "name": "annotations",
        "description": "List annotations, newest first, optionally filtered by target and namespace.",
        "inputSchema": _schema({"target": OID, "namespace": {"type": "string"}}),
    },
    {
        "name": "verify",
        "description": "Repository health check: hashes, schemas, refs, graph links. Reports, never repairs.",
        "inputSchema": _schema({}),
    },
    {
        "name": "bisect_thought",
        "description": (
            "Binary-search the first thought where reasoning went wrong. The oracle is a shell "
            "command run per probe with COGIT_THOUGHT/COGIT_MINDSET/COGIT_REPO env; exit 0 good, "
            "125 skip, other bad. Probes never mutate the repository."
        ),
        "inputSchema": _schema(
            {"good": REF, "bad": REF, "run": {"type": "string", "description": "oracle shell command"}},
            required=("good", "bad", "run"),
        ),
    },
]


class CogitTools:
    def __init__(self, repo_path):
        self.repo_path = repo_path
        init_repository(repo_path)  # idempotent; one server per journal
        self.repo = Repository.open(repo_path)

    def call(self, name, args):
        handler = getattr(self, f"tool_{name}", None)
        if handler is None:
            raise CogitError(f"unknown tool: {name}")
        return handler(args)

    # -- tools -----------------------------------------------------------------

    def tool_add_fact(self, args):
        source_type, _sep, source_uri = args["source"].partition(":")
        source = {"type": source_type}
        if source_uri:
            source["uri"] = source_uri
        claim = {
            "type": "claim",
            "kind": args["kind"],
            "subject": args["subject"],
            "predicate": args["predicate"],
            "object": args["object"],
            "qualifiers": args.get("qualifiers", {}),
        }
        if args.get("negates"):
            negates = args["negates"]
            claim["negates"] = negates if negates.startswith("sha256:") else f"sha256:{negates}"
        doc = {
            "claim": claim,
            "assertion": {
                "type": "assertion",
                "status": "asserted",
                "source": source,
                "confidence_bps": args["confidence_bps"],
                "asserted_at": _now(),
                "actor": args.get("actor", "agent"),
                "method": {"type": args.get("method", "mcp")},
            },
        }
        claim_oid, assertion_oid = self.repo.add_fact(doc)
        result = {"claim": claim_oid, "assertion": assertion_oid}
        if args.get("commit"):
            message = args.get("message") or f"{args['kind']}: {args['subject']} {args['predicate']}"
            result["thought"] = self.repo.commit_thought(message, args.get("actor", "agent"))
        return result

    def tool_remove_fact(self, args):
        oid = self.repo.expand_object_id(args["assertion_id"])
        return {"outcome": self.repo.remove_fact(oid, args["reason"]), "assertion": oid}

    def tool_commit_thought(self, args):
        return {"thought": self.repo.commit_thought(args["message"], args.get("author", "agent"))}

    def tool_status(self, _args):
        return self.repo.status()

    def tool_facts(self, args):
        return self.repo.facts(args.get("ref"))

    def tool_recap(self, args):
        return self.repo.recap(args["from"], args.get("to"))

    def tool_log(self, args):
        thoughts = self.repo.log(args.get("ref"))
        limit = args.get("limit")
        return {"thoughts": thoughts[:limit] if limit else thoughts}

    def tool_blame_fact(self, args):
        oid = self.repo.expand_object_id(args["fact_id"])
        return self.repo.blame_fact(oid, args.get("ref"))

    def tool_diff(self, args):
        return self.repo.diff(args["a"], args["b"])

    def tool_branch(self, args):
        if not args.get("name"):
            return {"branches": self.repo.list_branches()}
        target = self.repo.branch(args["name"], args.get("thought"))
        return {"branch": args["name"], "target": target}

    def tool_checkout(self, args):
        mode, thought = self.repo.checkout(args["target"])
        return {"mode": mode, "thought": thought}

    def tool_merge(self, args):
        return self.repo.merge(args["target"])

    def tool_resolve(self, args):
        claim = self.repo.expand_object_id(args["claim_id"])
        keep = self.repo.expand_object_id(args["keep"]) if args.get("keep") else None
        remaining = self.repo.resolve_conflict(
            claim, keep=keep, drop=bool(args.get("drop")), use_suggestion=bool(args.get("suggested"))
        )
        return {"remaining_conflicts": remaining}

    def tool_anchor(self, args):
        if not args.get("name"):
            return {"anchors": self.repo.list_anchors()}
        if not args.get("thought_id"):
            raise CogitError("anchor: thought_id is required when creating an anchor")
        oid = self.repo.anchor(args["name"], args["thought_id"])
        return {"name": args["name"], "anchor": oid}

    def tool_annotate(self, args):
        oid = self.repo.annotate(
            args["target"], args["message"],
            namespace=args.get("namespace", "notes"),
            author=args.get("author", "agent"),
        )
        return {"annotation": oid, "namespace": args.get("namespace", "notes")}

    def tool_annotations(self, args):
        return {"annotations": self.repo.annotations_for(args.get("target"), namespace=args.get("namespace"))}

    def tool_verify(self, _args):
        findings = verify_repository(self.repo)
        errors = [f for f in findings if f["severity"] == "error"]
        return {"healthy": not errors, "findings": findings}

    def tool_bisect_thought(self, args):
        return bisect_thought(self.repo, args["good"], args["bad"], command_runner(self.repo, args["run"]))


def _now():
    from cogit.repo import now_utc

    return now_utc()


# -- JSON-RPC over stdio -----------------------------------------------------------


def _response(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle(tools, message):
    """Return a response dict, or None for notifications."""
    request_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}
    if method is None:
        return None
    if method.startswith("notifications/"):
        return None
    if method == "initialize":
        return _response(request_id, {
            "protocolVersion": params.get("protocolVersion", PROTOCOL_FALLBACK),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "cogit", "version": __version__},
        })
    if method == "ping":
        return _response(request_id, {})
    if method == "tools/list":
        return _response(request_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        try:
            result = tools.call(name, arguments)
            return _response(request_id, {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                "isError": False,
            })
        except CogitError as exc:
            return _response(request_id, {
                "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
                "isError": True,
            })
    return _error(request_id, -32601, f"Method not found: {method}")


def main():
    repo_path = os.environ.get("COGIT_REPO")
    if "--repo" in sys.argv:
        repo_path = sys.argv[sys.argv.index("--repo") + 1]
    if not repo_path:
        print("cogit-mcp: set COGIT_REPO or pass --repo <path>", file=sys.stderr)
        return 2
    tools = CogitTools(repo_path)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            print(json.dumps(_error(None, -32700, "Parse error")), flush=True)
            continue
        response = handle(tools, message)
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
