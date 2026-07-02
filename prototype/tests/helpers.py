"""Shared fixtures: deterministic repos and fact documents."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cogit.repo import Repository, init_repository  # noqa: E402

TS = "2026-07-02T10:00:00Z"


def ts(n: int) -> str:
    return f"2026-07-02T10:{n // 60:02d}:{n % 60:02d}Z"


def make_repo():
    """Create a temp repository; returns (tmpdir_handle, Repository)."""
    tmp = tempfile.TemporaryDirectory(prefix="cogit-test-")
    init_repository(tmp.name)
    return tmp, Repository.open(tmp.name)


def fact_doc(predicate: str, obj="yes", kind="agent_decision", confidence=9000, when=TS):
    return {
        "claim": {
            "type": "claim",
            "kind": kind,
            "subject": "test",
            "predicate": predicate,
            "object": obj,
            "qualifiers": {},
        },
        "assertion": {
            "type": "assertion",
            "status": "asserted",
            "source": {"type": "manual", "uri": "test:fixture"},
            "confidence_bps": confidence,
            "asserted_at": when,
            "actor": "tester",
            "method": {"type": "fixture"},
        },
    }
