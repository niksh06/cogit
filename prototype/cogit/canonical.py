"""Canonical JSON encoding (docs/spec/object-format-v1.md, ADR-0010).

Profile: UTF-8, keys sorted by Unicode code point, minimal escaping,
integers only (|n| <= 2^53 - 1), floats forbidden, no insignificant
whitespace. Python's json module natively matches the escaping and
key-ordering rules, so this wrapper only enforces the value restrictions.
"""

import json

from .errors import UserError

MAX_SAFE_INT = 2**53 - 1


def _validate_value(value, path="$"):
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, float):
        raise UserError(f"canonical json: float forbidden at {path}")
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INT:
            raise UserError(f"canonical json: integer out of safe range at {path}")
        return
    if isinstance(value, list):
        for i, item in enumerate(value):
            _validate_value(item, f"{path}[{i}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise UserError(f"canonical json: non-string key at {path}")
            _validate_value(item, f"{path}.{key}")
        return
    raise UserError(f"canonical json: unsupported type {type(value).__name__} at {path}")


def canonical_json(value) -> str:
    """Return the canonical JSON text for a JSON-compatible value."""
    _validate_value(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_json_bytes(value) -> bytes:
    return canonical_json(value).encode("utf-8")


def parse_json(text: str):
    """Parse JSON while rejecting floats, so bad values fail at the boundary."""

    def _reject_float(s: str):
        raise UserError(f"canonical json: float forbidden: {s}")

    return json.loads(text, parse_float=_reject_float)
