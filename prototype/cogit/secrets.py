"""Suspected-secret rejection (ADR-0009, invariant 21).

Policy: reject the write, never redact-and-store. Detection is a conservative
pattern list (OQ-013 keeps the full detection design open); patterns aim for
high precision so normal reasoning text is not blocked.
"""

import re

from .errors import UserError

_SECRET_PATTERNS = (
    ("aws access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("openai-style key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("anthropic key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("credential assignment", re.compile(r"(?i)\b(password|passwd|api[_-]?key|secret[_-]?key|access[_-]?token)\s*[=:]\s*\S{8,}")),
)


def _iter_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)


def reject_suspected_secrets(value, where="write"):
    """Raise UserError if any string in the value looks like a secret."""
    for text in _iter_strings(value):
        for label, pattern in _SECRET_PATTERNS:
            if pattern.search(text):
                raise UserError(
                    f"{where}: rejected — content matches suspected secret ({label}); "
                    "secrets must not be stored in Cogit"
                )
