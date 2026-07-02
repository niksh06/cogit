"""Staged working memory: .cogit/index.json (docs/spec/repository-layout-v1.md)."""

import json
import os

from .errors import CorruptionError
from .objects import is_oid

EMPTY_INDEX = {
    "base_mindset": None,
    "staged_facts": [],
    "removed_facts": [],
    "conflicts": [],
    "merge": None,
}


def load_index(cogit_dir):
    path = os.path.join(cogit_dir, "index.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise CorruptionError("index: index.json missing") from exc
    except ValueError as exc:
        raise CorruptionError(f"index: index.json malformed: {exc}") from exc
    if not isinstance(data, dict) or set(EMPTY_INDEX) - set(data):
        raise CorruptionError("index: index.json missing required fields")
    if data["base_mindset"] is not None and not is_oid(data["base_mindset"]):
        raise CorruptionError("index: base_mindset invalid")
    for oid in data["staged_facts"]:
        if not is_oid(oid):
            raise CorruptionError(f"index: staged fact id invalid: {oid}")
    for entry in data["removed_facts"]:
        if not isinstance(entry, dict) or not is_oid(entry.get("id")) or not entry.get("reason"):
            raise CorruptionError("index: removed_facts entries need 'id' and 'reason'")
    return data


def save_index(cogit_dir, data):
    """Write index atomically (tmp file + rename)."""
    path = os.path.join(cogit_dir, "index.json")
    tmp_dir = os.path.join(cogit_dir, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    import tempfile

    fd, tmp_path = tempfile.mkstemp(prefix="index-", dir=tmp_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.rename(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def index_is_empty(data) -> bool:
    return (
        not data["staged_facts"]
        and not data["removed_facts"]
        and not data["conflicts"]
        and data["merge"] is None
    )
