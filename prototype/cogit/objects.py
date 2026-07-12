"""Object schemas, validation, and preimage/ID computation.

Contract: docs/spec/object-format-v1.md. Unknown fields are rejected.
"""

import hashlib
import re

from .canonical import canonical_json_bytes
from .errors import UserError

OBJECT_TYPES = ("claim", "assertion", "mindset", "thought", "anchor", "annotation")

CLAIM_KINDS = (
    "user_preference",
    "tool_observation",
    "document_claim",
    "agent_decision",
    "policy_constraint",
)
ASSERTION_STATUSES = ("asserted", "refuted", "superseded")
SOURCE_TYPES = ("prompt", "tool", "file", "url", "system", "manual", "agent")
THOUGHT_OPERATIONS = ("commit", "merge", "checkout", "anchor", "import", "repair")

OID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
REF_SEGMENT_RE = re.compile(r"^[a-z0-9._-]+$")


def is_oid(value) -> bool:
    return isinstance(value, str) and bool(OID_RE.match(value))


def _require(obj, field, message=None):
    if field not in obj:
        raise UserError(message or f"object: missing required field '{field}'")
    return obj[field]


_MODE = __import__("threading").local()  # per-thread read/write validation mode


def _tolerant() -> bool:
    return getattr(_MODE, "tolerant", False)


def _check_keys(obj, allowed, optional=(), where="object"):
    if _tolerant():
        # ADR-0015: read mode tolerates unknown fields on known types —
        # an object written by a NEWER cogit is version skew, not corruption
        # (hash and known-field checks still apply; verify reports the skew)
        return
    unknown = set(obj) - set(allowed) - set(optional)
    if unknown:
        raise UserError(f"{where}: unknown fields rejected: {sorted(unknown)}")


def _check_str(value, field, nonempty=True):
    if not isinstance(value, str) or (nonempty and not value):
        raise UserError(f"object: field '{field}' must be a non-empty string")
    return value


def _check_oid(value, field):
    if not is_oid(value):
        raise UserError(f"object: field '{field}' must be a 'sha256:<64-hex>' reference")
    return value


def _check_timestamp(value, field):
    if not isinstance(value, str) or not TIMESTAMP_RE.match(value):
        raise UserError(f"object: field '{field}' must be ISO-8601 UTC with 'Z' suffix")
    return value


def _check_sorted_unique_oids(value, field):
    if not isinstance(value, list):
        raise UserError(f"object: field '{field}' must be a list")
    for item in value:
        _check_oid(item, field)
    if len(set(value)) != len(value):
        raise UserError(f"object: field '{field}' must not contain duplicates")
    if value != sorted(value):
        raise UserError(f"object: field '{field}' must be sorted lexicographically")
    return value


def _check_flat_object(value, field):
    """Qualifier/method-style maps: string keys, scalar values."""
    if not isinstance(value, dict):
        raise UserError(f"object: field '{field}' must be an object")
    for key, item in value.items():
        _check_str(key, f"{field} key")
        if not isinstance(item, (str, int, bool)) and item is not None:
            raise UserError(f"object: field '{field}.{key}' must be a scalar")
    return value


def _validate_claim(obj):
    _check_keys(
        obj,
        ("type", "kind", "subject", "predicate", "object", "qualifiers"),
        optional=("negates",),
        where="claim",
    )
    if _require(obj, "kind") not in CLAIM_KINDS:
        raise UserError(f"claim: kind must be one of {CLAIM_KINDS}")
    _check_str(_require(obj, "subject"), "subject")
    _check_str(_require(obj, "predicate"), "predicate")
    obj_value = _require(obj, "object")
    if not isinstance(obj_value, (str, int, bool)):
        raise UserError("claim: object must be a scalar (string, integer, or boolean)")
    _check_flat_object(_require(obj, "qualifiers"), "qualifiers")
    if "negates" in obj:
        _check_oid(obj["negates"], "negates")


def _validate_assertion(obj):
    _check_keys(
        obj,
        ("type", "claim", "status", "source", "confidence_bps", "asserted_at", "actor", "method"),
        optional=("premises",),
        where="assertion",
    )
    if "premises" in obj:
        premises = obj["premises"]
        if not isinstance(premises, list) or not premises:
            raise UserError("assertion: premises must be a non-empty array of assertion ids")
        for premise in premises:
            _check_oid(premise, "premises[]")
        if premises != sorted(set(premises)):
            raise UserError("assertion: premises must be sorted and unique")
    _check_oid(_require(obj, "claim"), "claim")
    if _require(obj, "status") not in ASSERTION_STATUSES:
        raise UserError(f"assertion: status must be one of {ASSERTION_STATUSES}")
    source = _require(obj, "source")
    if not isinstance(source, dict):
        raise UserError("assertion: source must be an object")
    _check_keys(source, ("type",), optional=("uri",), where="assertion.source")
    if _require(source, "type", "assertion.source: missing 'type'") not in SOURCE_TYPES:
        raise UserError(f"assertion: source.type must be one of {SOURCE_TYPES}")
    if "uri" in source:
        _check_str(source["uri"], "source.uri")
    confidence = _require(obj, "confidence_bps")
    if isinstance(confidence, bool) or not isinstance(confidence, int) or not 0 <= confidence <= 10000:
        raise UserError("assertion: confidence_bps must be an integer from 0 to 10000")
    _check_timestamp(_require(obj, "asserted_at"), "asserted_at")
    actor = _check_str(_require(obj, "actor"), "actor")
    if any(ch.isspace() for ch in actor):
        raise UserError("assertion: actor must not contain whitespace")
    method = _check_flat_object(_require(obj, "method"), "method")
    _check_str(method.get("type", ""), "method.type")


def _validate_mindset(obj):
    _check_keys(obj, ("type", "assertions", "created_at"), where="mindset")
    _check_sorted_unique_oids(_require(obj, "assertions"), "assertions")
    _check_timestamp(_require(obj, "created_at"), "created_at")


def _validate_thought(obj):
    _check_keys(
        obj,
        ("type", "parents", "mindset", "operation", "message", "author", "timestamp",
         "removals", "writer"),
        where="thought",
    )
    parents = _require(obj, "parents")
    if not isinstance(parents, list):
        raise UserError("thought: parents must be a list")
    for parent in parents:
        _check_oid(parent, "parents")
    if len(set(parents)) != len(parents):
        raise UserError("thought: parents must not contain duplicates")
    _check_oid(_require(obj, "mindset"), "mindset")
    if _require(obj, "operation") not in THOUGHT_OPERATIONS:
        raise UserError(f"thought: operation must be one of {THOUGHT_OPERATIONS}")
    _check_str(_require(obj, "message"), "message")
    _check_str(_require(obj, "author"), "author")
    _check_timestamp(_require(obj, "timestamp"), "timestamp")
    if "removals" in obj:
        # ADR-0014: durable removal provenance — optional, additive
        removals = obj["removals"]
        if not isinstance(removals, list) or not removals:
            raise UserError("thought: removals must be a non-empty list when present")
        seen = []
        for entry in removals:
            if not isinstance(entry, dict) or set(entry) != {"assertion", "reason"}:
                raise UserError("thought: each removal needs exactly {assertion, reason}")
            _check_oid(entry["assertion"], "removals.assertion")
            reason = entry["reason"]
            if not isinstance(reason, str) or not reason:
                raise UserError("thought: removal reason must be a non-empty string")
            seen.append(entry["assertion"])
        if seen != sorted(seen) or len(set(seen)) != len(seen):
            raise UserError("thought: removals must be sorted by assertion and unique")
    if "writer" in obj:
        # ADR-0016: writer provenance — optional, additive
        writer = obj["writer"]
        if not isinstance(writer, str) or not 0 < len(writer) <= 64:
            raise UserError("thought: writer must be a non-empty string of at most 64 chars")
        impl_part, sep, version_part = writer.partition("/")
        if not sep or not impl_part or not version_part or "/" in version_part \
                or any(ch.isspace() or not ch.isprintable() for ch in writer):
            raise UserError("thought: writer must be a single '<impl>/<version>' token")


def _validate_anchor(obj):
    _check_keys(obj, ("type", "name", "target", "created_at", "author"), where="anchor")
    name = _check_str(_require(obj, "name"), "name")
    if not REF_SEGMENT_RE.match(name):
        raise UserError("anchor: name must be a valid ref segment")
    _check_oid(_require(obj, "target"), "target")
    _check_timestamp(_require(obj, "created_at"), "created_at")
    _check_str(_require(obj, "author"), "author")


def _validate_annotation(obj):
    _check_keys(
        obj,
        ("type", "target", "namespace", "body", "author", "created_at", "parents"),
        where="annotation",
    )
    _check_oid(_require(obj, "target"), "target")
    namespace = _check_str(_require(obj, "namespace"), "namespace")
    if not REF_SEGMENT_RE.match(namespace):
        raise UserError("annotation: namespace must be a valid ref segment")
    _check_str(_require(obj, "body"), "body")
    _check_str(_require(obj, "author"), "author")
    _check_timestamp(_require(obj, "created_at"), "created_at")
    parents = _require(obj, "parents")
    if not isinstance(parents, list):
        raise UserError("annotation: parents must be a list")
    for parent in parents:
        _check_oid(parent, "parents")
    if len(set(parents)) != len(parents):
        raise UserError("annotation: parents must not contain duplicates")


_VALIDATORS = {
    "claim": _validate_claim,
    "assertion": _validate_assertion,
    "mindset": _validate_mindset,
    "thought": _validate_thought,
    "anchor": _validate_anchor,
    "annotation": _validate_annotation,
}


def validate_object(obj, mode="write") -> str:
    """Validate an object against its schema; return the object type.

    mode="write" (default) is STRICT: unknown fields are rejected — we only
    ever write what we understand. mode="read" is tolerant of unknown fields
    on known types (ADR-0015): additive format extensions must not turn
    older readers' view of newer objects into CorruptionError; integrity is
    still guaranteed by the hash and the known-field checks.
    """
    if not isinstance(obj, dict):
        raise UserError("object: must be a JSON object")
    obj_type = obj.get("type")
    if obj_type not in OBJECT_TYPES:
        raise UserError(f"object: type must be one of {OBJECT_TYPES}")
    _MODE.tolerant = mode == "read"
    try:
        _VALIDATORS[obj_type](obj)
    finally:
        _MODE.tolerant = False
    return obj_type


def encode_object(obj):
    """Return (object_id, preimage_bytes) for a validated object."""
    obj_type = validate_object(obj)
    body = canonical_json_bytes(obj)
    preimage = f"{obj_type} {len(body)}".encode("ascii") + b"\x00" + body
    oid = "sha256:" + hashlib.sha256(preimage).hexdigest()
    return oid, preimage
