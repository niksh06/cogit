"""Repository pressure metrics (COG-022, US-021, ADR-0006).

count-objects is a metrics scan, not a health check: it reads object
headers only, never mutates, and must not fail on a damaged repository —
unreadable objects are counted as corrupt.
"""

import os
import zlib

from .objects import OBJECT_TYPES
from .repo import _parse_config

DEFAULT_THRESHOLDS = {
    "looseObjectsWarn": 5000,   # ADR-0006 candidate trigger
    "refsWarn": 200,
    "reflogEntriesWarn": 10000,
    # retention has NO default: reflog expiry is always explicit (COG-024)
    "reflogRetainEntries": None,
}


def _thresholds(cogit_dir):
    thresholds = dict(DEFAULT_THRESHOLDS)
    config_path = os.path.join(cogit_dir, "config")
    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            section = _parse_config(handle.read()).get("maintenance", {})
    except OSError:
        section = {}
    for key in thresholds:
        if key.lower() in {k.lower() for k in section}:
            value = next(v for k, v in section.items() if k.lower() == key.lower())
            try:
                thresholds[key] = int(value)
            except ValueError:
                pass
    return thresholds


def _count_files(path):
    total = 0
    for _dirpath, _dirs, files in os.walk(path):
        total += len([f for f in files if not f.endswith(".lock")])
    return total


def count_objects(repo):
    cogit = repo.cogit_dir
    by_type = {obj_type: 0 for obj_type in OBJECT_TYPES}
    corrupt = 0
    disk_bytes = 0
    objects_dir = os.path.join(cogit, "objects")
    if os.path.isdir(objects_dir):
        for dirpath, _dirs, files in os.walk(objects_dir):
            for filename in files:
                path = os.path.join(dirpath, filename)
                disk_bytes += os.path.getsize(path)
                try:
                    with open(path, "rb") as handle:
                        preimage = zlib.decompress(handle.read())
                    obj_type = preimage.split(b"\x00", 1)[0].decode("ascii").split(" ", 1)[0]
                    if obj_type in by_type:
                        by_type[obj_type] += 1
                    else:
                        corrupt += 1
                except (OSError, zlib.error, UnicodeDecodeError, IndexError):
                    corrupt += 1

    heads = _count_files(os.path.join(cogit, "refs", "heads"))
    anchors = _count_files(os.path.join(cogit, "refs", "anchors"))

    reflog_entries = 0
    reflog_bytes = 0
    logs_dir = os.path.join(cogit, "logs")
    if os.path.isdir(logs_dir):
        for dirpath, _dirs, files in os.walk(logs_dir):
            for filename in files:
                path = os.path.join(dirpath, filename)
                reflog_bytes += os.path.getsize(path)
                with open(path, "r", encoding="utf-8", errors="replace") as handle:
                    reflog_entries += sum(1 for line in handle if line.strip())

    tmp_dir = os.path.join(cogit, "tmp")
    tmp_files = len(os.listdir(tmp_dir)) if os.path.isdir(tmp_dir) else 0

    loose_total = sum(by_type.values()) + corrupt
    thresholds = _thresholds(cogit)
    warnings = []
    if loose_total > thresholds["looseObjectsWarn"]:
        warnings.append(
            f"loose objects ({loose_total}) exceed threshold {thresholds['looseObjectsWarn']}; "
            "consider planning maintenance layers (ADR-0006)"
        )
    if heads + anchors > thresholds["refsWarn"]:
        warnings.append(f"refs ({heads + anchors}) exceed threshold {thresholds['refsWarn']}")
    if reflog_entries > thresholds["reflogEntriesWarn"]:
        warnings.append(
            f"reflog entries ({reflog_entries}) exceed threshold {thresholds['reflogEntriesWarn']}; "
            "define a retention policy (OQ-010)"
        )
    if corrupt:
        warnings.append(f"{corrupt} unreadable object file(s); run `cogit verify`")

    return {
        "loose_objects": loose_total,
        "by_type": by_type,
        "corrupt_objects": corrupt,
        "disk_bytes": disk_bytes,
        "heads": heads,
        "anchors": anchors,
        "reflog_entries": reflog_entries,
        "reflog_bytes": reflog_bytes,
        "tmp_files": tmp_files,
        "thresholds": thresholds,
        "warnings": warnings,
    }
