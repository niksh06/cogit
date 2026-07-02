"""Conflict resolution memory (COG-020, US-019, closes OQ-008).

Local preference store in .cogit/rerere.json — analogous to git's
rr-cache: mutable, per-repository, never part of immutable history.
Suggestions are surfaced, never auto-applied.
"""

import hashlib
import json
import os
import tempfile

from .canonical import canonical_json_bytes

RERERE_FILE = "rerere.json"


def conflict_fingerprint(conflict) -> str:
    """Orientation-invariant identity of a conflict shape."""
    sides = sorted([sorted(conflict["ours"]), sorted(conflict["theirs"])])
    shape = {"claim": conflict["claim"], "sides": sides, "base": sorted(conflict["base"])}
    return "sha256:" + hashlib.sha256(canonical_json_bytes(shape)).hexdigest()


def load_rerere(cogit_dir) -> dict:
    path = os.path.join(cogit_dir, RERERE_FILE)
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _save(cogit_dir, data):
    tmp_dir = os.path.join(cogit_dir, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix="rerere-", dir=tmp_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.rename(tmp_path, os.path.join(cogit_dir, RERERE_FILE))
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def record_resolution(cogit_dir, conflict, keep, recorded_at):
    """Remember how a conflict was resolved. keep is an assertion id or None (drop)."""
    store = load_rerere(cogit_dir)
    store[conflict_fingerprint(conflict)] = {
        "claim": conflict["claim"],
        "keep": keep,
        "recorded_at": recorded_at,
    }
    _save(cogit_dir, store)


def suggestion_for(cogit_dir, conflict):
    """Stored resolution for this conflict shape, or None."""
    return load_rerere(cogit_dir).get(conflict_fingerprint(conflict))


def forget(cogit_dir, key) -> int:
    """Drop entries by fingerprint or by claim id. Returns removed count."""
    store = load_rerere(cogit_dir)
    doomed = [fp for fp, rec in store.items() if fp == key or rec["claim"] == key]
    for fp in doomed:
        del store[fp]
    if doomed:
        _save(cogit_dir, store)
    return len(doomed)
