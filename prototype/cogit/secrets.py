"""Suspected-secret rejection (ADR-0009, invariant 21; v2 per COG-023).

Policy: reject the write, never redact-and-store. Detection layers:

1. Known-shape patterns (high precision).
2. Credential-in-URL and credential-assignment shapes.
3. Entropy heuristic for opaque random tokens, with explicit
   false-positive guards: Cogit object IDs (sha256:<hex>), plain hex,
   and code identifiers must never trigger.

OQ-013 stays open for scanner-grade detection; this is the local layer.
"""

import math
import re

from .errors import UserError

_SECRET_PATTERNS = (
    ("aws access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("aws secret access key", re.compile(r"(?i)\baws_?secret[^\n]{0,20}[=:]\s*['\"]?[A-Za-z0-9/+=]{40}\b")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("openai-style key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("anthropic key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("credential assignment", re.compile(r"(?i)\b(password|passwd|api[_-]?key|secret[_-]?key|access[_-]?token)\s*[=:]\s*\S{8,}")),
    ("credentials in url", re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]{4,}@")),
)

_TOKEN_RE = re.compile(r"[A-Za-z0-9+/_=-]{24,}")
_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")
_ENTROPY_THRESHOLD = 4.2  # bits/char: random hex stays below, random base64 above


def _shannon_entropy(text: str) -> float:
    counts = {}
    for ch in text:
        counts[ch] = counts.get(ch, 0) + 1
    total = len(text)
    return -sum((n / total) * math.log2(n / total) for n in counts.values())


def _looks_like_random_token(token: str) -> bool:
    """High-entropy opaque token check with false-positive guards."""
    if _HEX_RE.match(token):
        return False  # covers Cogit object ids and other hashes
    has_upper = any(c.isupper() for c in token)
    has_lower = any(c.islower() for c in token)
    has_digit = any(c.isdigit() for c in token)
    # identifiers/prose rarely mix all three; random base64 almost always does
    if not (has_upper and has_lower and has_digit):
        return False
    return _shannon_entropy(token) >= _ENTROPY_THRESHOLD


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
        for token in _TOKEN_RE.findall(text):
            if _looks_like_random_token(token):
                raise UserError(
                    f"{where}: rejected — high-entropy token looks like a secret "
                    f"('{token[:8]}…', {len(token)} chars); secrets must not be stored in Cogit"
                )
