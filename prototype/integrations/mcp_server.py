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
import traceback
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from cogit import __version__  # noqa: E402
from cogit.bisect import bisect_thought, command_runner  # noqa: E402
from cogit.errors import CogitError  # noqa: E402
from cogit.repo import Repository, init_repository  # noqa: E402
from cogit.verify import verify_repository  # noqa: E402

PROTOCOL_FALLBACK = "2024-11-05"

# One MCP server process serves one Claude Code session, so a per-process
# id makes parallel sessions distinguishable in the journal without any
# caller discipline (COG-052). Override with COGIT_ACTOR for stable names.
INSTANCE_ACTOR = os.environ.get("COGIT_ACTOR") or f"agent-{uuid.uuid4().hex[:8]}"

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
            "Record a belief: write a claim and a provenance-bearing assertion. With commit=true "
            "this is an ATOMIC micro-commit that bypasses the shared index — safe for parallel "
            "agents on one journal. One proposition per claim; object is a value, not a sentence. "
            "In a shared journal always set project."
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
                "project": {"type": "string", "description": "shared-journal convention: project qualifier"},
                "negates": {**OID, "description": "claim id this claim negates"},
                "premises": {"type": "array", "items": OID,
                             "description": "assertion ids this belief derives from (ADR-0013)"},
                "source": {"type": "string", "description": "type[:uri], e.g. agent:session-x"},
                "confidence_bps": {"type": "integer", "minimum": 0, "maximum": 10000},
                "actor": {"type": "string", "description": "default: per-session instance id"},
                "method": {"type": "string", "default": "mcp"},
                "commit": {"type": "boolean", "description": "atomic micro-commit (parallel-safe)"},
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
            {"message": {"type": "string"}, "author": {"type": "string", "description": "default: per-session instance id"}},
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
        "description": (
            "Active beliefs of a thought (default HEAD) with decoded claim content. Filter with "
            "subject (exact URI or trailing-* prefix), predicate, project — exact matching, not search. "
            "Rows with negation:true assert the referenced claim is FALSE (object means NOT <object>); "
            "they do not assert a replacement value."
        ),
        "inputSchema": _schema({
            "ref": REF,
            "subject": {"type": "string", "description": "exact subject URI, or prefix with trailing '*'"},
            "predicate": {"type": "string"},
            "project": {"type": "string"},
        }),
    },
    {
        "name": "recap",
        "description": (
            "Context recovery: thoughts and net belief changes between a past point and now. "
            "Call with NO arguments when resuming work — it starts from the newest anchor. "
            "In a shared journal pass project to scope rows AND thoughts to your project."
        ),
        "inputSchema": _schema({"from": REF, "to": REF,
                                "project": {"type": "string",
                                            "description": "scope to this project qualifier"}}),
    },
    {
        "name": "lint",
        "description": (
            "Claim-modeling linter (COG-047/058): checks ACTIVE beliefs against the cookbook — "
            "prose objects, unstable ids, blob qualifiers, band mismatches, missing project — "
            "plus lifecycle hygiene: R11 competing active values in one claim family, R12 "
            "singleton-state collisions, R13 prose lifecycle markers (heuristic). Output is "
            "bounded (limit=50 default, totals exact); 'since' classifies findings "
            "existing/new against a baseline anchor (ratchet). Read-only, never autofixes — "
            "remediate with supersede_fact/refute_fact/retire_fact."
        ),
        "inputSchema": _schema({
            "ref": REF,
            "project": {"type": "string"},
            "since": {"type": "string", "description": "baseline anchor/ref for the ratchet"},
            "rule": {"type": "string", "description": "show only this rule"},
            "severity": {"type": "string", "enum": ["warn", "info"]},
            "limit": {"type": "integer", "minimum": 0, "default": 50},
            "summary": {"type": "boolean", "description": "totals only"},
        }),
    },
    {
        "name": "analytics",
        "description": (
            "Belief analytics (COG-045): calibration per confidence band and source type "
            "(open/superseded/refuted/retired, survival = open/(open+refuted)) plus claim "
            "families ranked by revision churn. Outcomes from recorded removal reasons "
            "(ADR-0014) with structural inference as fallback. 'project' scopes everything."
        ),
        "inputSchema": _schema({"ref": REF, "top": {"type": "integer", "minimum": 1, "default": 20},
                                "project": {"type": "string"}}),
    },
    {
        "name": "health",
        "description": (
            "One-call project health (COG-059) — THE preferred re-anchor for journal-quality "
            "questions: repository integrity, active/negation/outcome counts, lint totals "
            "(+ new-debt vs a 'since' baseline), lifecycle candidates (bounded, compact "
            "previews), last project thought, newest anchor, top volatile families. On a "
            "shared journal 'project' is required; totals are exact, detail is top-N."
        ),
        "inputSchema": _schema({
            "project": {"type": "string"},
            "since": {"type": "string", "description": "lint baseline anchor/ref"},
            "top": {"type": "integer", "minimum": 0, "default": 10},
        }),
    },
    {
        "name": "record",
        "description": (
            "Batch affordance (COG-044): several facts (same shape as add_fact, minus "
            "commit/message) plus optional removals become ONE thought, atomically — the whole "
            "batch lands or repository state is unchanged (COG-055). Bypasses the shared index "
            "and refuses when it is dirty; removals must target active assertions."
        ),
        "inputSchema": _schema(
            {
                "facts": {"type": "array", "minItems": 1, "items": {"type": "object"}},
                "removals": {"type": "array", "items": _schema(
                    {"assertion_id": OID, "reason": {"type": "string"}},
                    required=("assertion_id", "reason"))},
                "message": {"type": "string"},
                "author": {"type": "string", "description": "default: per-session instance id"},
            },
            required=("facts", "message"),
        ),
    },
    {
        "name": "supersede_fact",
        "description": (
            "Atomic lifecycle transition (COG-056): remove the ACTIVE target assertion with "
            "reason 'superseded' and assert a replacement in the SAME claim family (kind/"
            "subject/predicate/qualifiers preserved, only the object changes) — ONE thought, "
            "all-or-nothing. Stale target -> clean error."
        ),
        "inputSchema": _schema(
            {
                "assertion_id": OID,
                "object": {"type": ["string", "integer", "boolean"],
                           "description": "replacement value"},
                "source": {"type": "string", "description": "type[:uri]"},
                "confidence_bps": {"type": "integer", "minimum": 0, "maximum": 10000},
                "actor": {"type": "string", "description": "default: per-session instance id"},
                "premises": {"type": "array", "items": OID},
                "message": {"type": "string"},
            },
            required=("assertion_id", "object", "source", "confidence_bps"),
        ),
    },
    {
        "name": "refute_fact",
        "description": (
            "Atomic structural refutation (COG-056): remove EVERY active assertion of the "
            "target's claim with reason 'refuted' and activate an explicit negation of that "
            "claim (invariant 25) — ONE thought, all-or-nothing. Prefer this over prose "
            "'REFUTE' markers: analytics only sees structural negations."
        ),
        "inputSchema": _schema(
            {
                "assertion_id": OID,
                "source": {"type": "string", "description": "type[:uri] backing the refutation"},
                "confidence_bps": {"type": "integer", "minimum": 0, "maximum": 10000},
                "actor": {"type": "string", "description": "default: per-session instance id"},
                "premises": {"type": "array", "items": OID},
                "message": {"type": "string"},
            },
            required=("assertion_id", "source", "confidence_bps"),
        ),
    },
    {
        "name": "retire_fact",
        "description": (
            "Atomic retirement (COG-056): remove active assertion(s) with an explicit reason "
            "WITHOUT asserting falsity — no negation, no replacement implied. ONE thought. "
            "Reason 'refuted' is rejected: use refute_fact."
        ),
        "inputSchema": _schema(
            {
                "assertion_ids": {"type": "array", "minItems": 1, "items": OID},
                "reason": {"type": "string"},
                "author": {"type": "string", "description": "default: per-session instance id"},
                "message": {"type": "string"},
            },
            required=("assertion_ids", "reason"),
        ),
    },
    {
        "name": "dump",
        "description": (
            "One-call reader surface (COG-042): active facts (negation-explicit), first "
            "introducer per assertion, anchors, branches, bounded log, and a recap block. "
            "THE way to re-anchor in a single call; use recap when only the delta matters."
        ),
        "inputSchema": _schema({
            "ref": REF,
            "compact": {"type": "boolean",
                        "description": "bounded previews for long prose objects (COG-059)"},
            "project": {"type": "string",
                        "description": "scope facts AND the log to this project (COG-059)"},
            "since": {**REF, "description": "recap-from anchor/ref (default: newest anchor)"},
            "limit_log": {"type": "integer", "minimum": 1, "default": 50},
        }),
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
                "author": {"type": "string", "description": "default: per-session instance id"},
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

    REQUIRED_FACT_FIELDS = ("kind", "subject", "predicate", "object",
                            "source", "confidence_bps")

    def _validated_fact_args(self, fact, where):
        """Shape-check a fact payload BEFORE any repository mutation (COG-055):
        missing or mistyped fields become clean CogitError messages instead of
        Python exceptions escaping the tool boundary."""
        if not isinstance(fact, dict):
            raise CogitError(f"{where} must be an object")
        missing = [key for key in self.REQUIRED_FACT_FIELDS if key not in fact]
        if missing:
            raise CogitError(f"{where} is missing required field(s): {', '.join(missing)}")
        if not isinstance(fact["source"], str) or not fact["source"]:
            raise CogitError(f"{where}.source must be a non-empty string 'type[:uri]'")
        if "qualifiers" in fact and not isinstance(fact["qualifiers"], dict):
            raise CogitError(f"{where}.qualifiers must be an object")
        if "premises" in fact and not isinstance(fact["premises"], list):
            raise CogitError(f"{where}.premises must be an array of assertion ids")
        return fact

    def _build_fact_doc(self, args):
        source_type, _sep, source_uri = args["source"].partition(":")
        source = {"type": source_type}
        if source_uri:
            source["uri"] = source_uri
        qualifiers = dict(args.get("qualifiers", {}))
        if args.get("project"):
            qualifiers.setdefault("project", args["project"])
        claim = {
            "type": "claim",
            "kind": args["kind"],
            "subject": args["subject"],
            "predicate": args["predicate"],
            "object": args["object"],
            "qualifiers": qualifiers,
        }
        if args.get("negates"):
            negates = args["negates"]
            claim["negates"] = negates if negates.startswith("sha256:") else f"sha256:{negates}"
        assertion = {
            "type": "assertion",
            "status": "asserted",
            "source": source,
            "confidence_bps": args["confidence_bps"],
            "asserted_at": _now(),
            "actor": args.get("actor", INSTANCE_ACTOR),
            "method": {"type": args.get("method", "mcp")},
        }
        if args.get("premises"):
            assertion["premises"] = sorted(
                {self.repo.expand_object_id(p) for p in args["premises"]})
        return {"claim": claim, "assertion": assertion}

    def tool_add_fact(self, args):
        doc = self._build_fact_doc(self._validated_fact_args(args, "add_fact"))
        if args.get("commit"):
            # atomic micro-commit: parallel-safe by construction (COG-035)
            return self.repo.micro_commit(doc, message=args.get("message"))
        claim_oid, assertion_oid = self.repo.add_fact(doc)
        return {"claim": claim_oid, "assertion": assertion_oid}

    def tool_record(self, args):
        # COG-055: validate the COMPLETE payload before any repository
        # mutation, then publish through one atomic batch commit — a bad
        # item can no longer leave earlier items staged.
        facts = args.get("facts")
        if not isinstance(facts, list) or not facts:
            raise CogitError("record: 'facts' must be a non-empty array")
        message = args.get("message")
        if not isinstance(message, str) or not message.strip():
            raise CogitError("record: a non-empty 'message' is required")
        removals = args.get("removals") or []
        if not isinstance(removals, list):
            raise CogitError("record: 'removals' must be an array")
        prepared = []
        for pos, removal in enumerate(removals):
            if (not isinstance(removal, dict) or not isinstance(removal.get("assertion_id"), str)
                    or not isinstance(removal.get("reason"), str)):
                raise CogitError(
                    f"record: removals[{pos}] requires string 'assertion_id' and 'reason'")
            prepared.append({
                "id": self.repo.expand_object_id(removal["assertion_id"]),
                "reason": removal["reason"],
            })
        docs = [self._build_fact_doc(self._validated_fact_args(fact, f"record: facts[{pos}]"))
                for pos, fact in enumerate(facts)]
        return self.repo.micro_commit_batch(
            docs, prepared, message, author=args.get("author", INSTANCE_ACTOR))

    def _lifecycle_assertion(self, args, where):
        """Assertion object for supersede/refute (COG-056), validated up front."""
        if not isinstance(args.get("source"), str) or not args["source"]:
            raise CogitError(f"{where}: 'source' must be a non-empty string 'type[:uri]'")
        if "confidence_bps" not in args:
            raise CogitError(f"{where}: 'confidence_bps' is required")
        source_type, _sep, source_uri = args["source"].partition(":")
        source = {"type": source_type}
        if source_uri:
            source["uri"] = source_uri
        assertion = {
            "type": "assertion",
            "status": "asserted",
            "source": source,
            "confidence_bps": args["confidence_bps"],
            "asserted_at": _now(),
            "actor": args.get("actor", INSTANCE_ACTOR),
            "method": {"type": args.get("method", "mcp")},
        }
        if args.get("premises"):
            if not isinstance(args["premises"], list):
                raise CogitError(f"{where}: 'premises' must be an array of assertion ids")
            assertion["premises"] = sorted(
                {self.repo.expand_object_id(p) for p in args["premises"]})
        return assertion

    def tool_supersede_fact(self, args):
        if not isinstance(args.get("assertion_id"), str):
            raise CogitError("supersede_fact: 'assertion_id' is required")
        if "object" not in args:
            raise CogitError("supersede_fact: replacement 'object' is required")
        assertion = self._lifecycle_assertion(args, "supersede_fact")
        return self.repo.supersede_fact(args["assertion_id"], args["object"], assertion,
                                        message=args.get("message"))

    def tool_refute_fact(self, args):
        if not isinstance(args.get("assertion_id"), str):
            raise CogitError("refute_fact: 'assertion_id' is required")
        assertion = self._lifecycle_assertion(args, "refute_fact")
        return self.repo.refute_fact(args["assertion_id"], assertion,
                                     message=args.get("message"))

    def tool_retire_fact(self, args):
        ids = args.get("assertion_ids")
        if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
            raise CogitError("retire_fact: 'assertion_ids' must be a non-empty array of strings")
        if not isinstance(args.get("reason"), str) or not args["reason"].strip():
            raise CogitError("retire_fact: a non-empty 'reason' is required")
        return self.repo.retire_fact(ids, args["reason"],
                                     args.get("author", INSTANCE_ACTOR),
                                     message=args.get("message"))

    def tool_remove_fact(self, args):
        oid = self.repo.expand_object_id(args["assertion_id"])
        return {"outcome": self.repo.remove_fact(oid, args["reason"]), "assertion": oid}

    def tool_commit_thought(self, args):
        return {"thought": self.repo.commit_thought(args["message"], args.get("author", INSTANCE_ACTOR))}

    def tool_status(self, _args):
        return self.repo.status()

    def tool_facts(self, args):
        return self.repo.facts(
            args.get("ref"),
            subject=args.get("subject"),
            predicate=args.get("predicate"),
            project=args.get("project"),
        )

    def tool_recap(self, args):
        return self.repo.recap(args.get("from"), args.get("to"),
                               project=args.get("project"))

    def tool_analytics(self, args):
        from analytics import analyze  # lazy: script-dir import
        return analyze(self.repo, args.get("ref"), top=args.get("top", 20),
                       project=args.get("project"))

    def tool_health(self, args):
        from health import health  # lazy: script-dir import
        return health(self.repo, project=args.get("project"),
                      since=args.get("since"), top=args.get("top", 10))

    def tool_lint(self, args):
        from lint import lint, shape_report  # lazy: script-dir import
        report = lint(self.repo, args.get("ref"), project=args.get("project"),
                      since=args.get("since"))
        # bounded by default (COG-058): full totals, capped detail rows
        return shape_report(report, rule=args.get("rule"),
                            severity=args.get("severity"),
                            limit=args.get("limit", 50),
                            summary=args.get("summary", False))

    def tool_dump(self, args):
        return self.repo.dump(args.get("ref"), project=args.get("project"),
                              since=args.get("since"),
                              log_limit=args.get("limit_log", 50),
                              compact=args.get("compact", False))

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
            author=args.get("author", INSTANCE_ACTOR),
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
        except Exception as exc:  # noqa: BLE001 — the stdio loop must survive tool bugs (COG-055)
            traceback.print_exc(file=sys.stderr)
            return _response(request_id, {
                "content": [{"type": "text", "text": f"internal error ({type(exc).__name__}): "
                             "the tool call failed unexpectedly; details on server stderr"}],
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
