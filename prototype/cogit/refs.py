"""Refs, HEAD, and reflogs: lockfile updates with old-target checks.

Protocol (ADR-0010, closes OQ-006): create <path>.lock exclusively, re-check
expected old value under the lock, write + fsync + atomic rename, then append
the reflog line. A reflog append failure after a successful ref move is
surfaced, not rolled back.
"""

import os
import re

from .errors import ConcurrentUpdateError, CorruptionError, UserError
from .objects import is_oid

REF_SEGMENT_RE = re.compile(r"^[a-z0-9._-]+$")
REFLOG_LINE_RE = re.compile(
    r"^(?P<old>\S+) (?P<new>\S+) (?P<ts>\S+) (?P<actor>\S+) (?P<op>[^:]+): (?P<reason>.*)$"
)


def validate_ref_name(name: str):
    """Validate a full ref name like 'refs/heads/main' per repository-layout-v1."""
    if not name or name.startswith("/") or name.endswith("/"):
        raise UserError(f"refs: invalid ref name '{name}'")
    if name.endswith(".lock") or "@{" in name or "\\" in name or ".." in name:
        raise UserError(f"refs: invalid ref name '{name}'")
    for segment in name.split("/"):
        if not segment or not REF_SEGMENT_RE.match(segment):
            raise UserError(f"refs: invalid ref segment '{segment}' in '{name}'")


class RefStore:
    def __init__(self, cogit_dir):
        self.cogit_dir = cogit_dir

    # -- paths -------------------------------------------------------------

    def _ref_path(self, name: str) -> str:
        return os.path.join(self.cogit_dir, *name.split("/"))

    def _log_path(self, name: str) -> str:
        return os.path.join(self.cogit_dir, "logs", *name.split("/"))

    # -- HEAD ---------------------------------------------------------------

    def read_head_raw(self) -> str:
        path = os.path.join(self.cogit_dir, "HEAD")
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return handle.read().strip()
        except FileNotFoundError as exc:
            raise CorruptionError("refs: HEAD missing") from exc

    def parse_head(self, content: str):
        """Return ('symbolic', refname) or ('detached', oid) for raw HEAD content."""
        if content.startswith("ref: "):
            refname = content[len("ref: ") :].strip()
            validate_ref_name(refname)
            return "symbolic", refname
        if is_oid(content):
            return "detached", content
        raise CorruptionError(f"refs: HEAD invalid: '{content}'")

    def read_head(self):
        return self.parse_head(self.read_head_raw())

    def write_head(self, value, old_head_target, actor, operation, reason, timestamp, expected_raw=None):
        """Point HEAD at 'ref: refs/heads/x' or a detached oid, with reflog.

        expected_raw, when given, is the raw HEAD content the caller observed;
        it is re-checked under the lock so a concurrent HEAD move fails with
        exit code 4 instead of being silently overwritten (COG-014).
        """
        if value.startswith("ref: "):
            validate_ref_name(value[len("ref: ") :])
        elif not is_oid(value):
            raise UserError(f"refs: invalid HEAD value '{value}'")
        path = os.path.join(self.cogit_dir, "HEAD")
        self._locked_replace(path, value + "\n", expected=expected_raw)
        self.append_reflog("HEAD", old_head_target, self._head_log_target(value), actor, operation, reason, timestamp)

    def _head_log_target(self, head_value: str) -> str:
        """Reflog records where HEAD logically points (oid when resolvable)."""
        if head_value.startswith("ref: "):
            target = self.read_ref(head_value[len("ref: ") :])
            return target if target else head_value[len("ref: ") :]
        return head_value

    # -- plain refs ----------------------------------------------------------

    def read_ref(self, name: str):
        validate_ref_name(name)
        path = self._ref_path(name)
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as handle:
            content = handle.read().strip()
        if not is_oid(content):
            raise CorruptionError(f"refs: {name} has invalid target '{content}'")
        return content

    def list_refs(self, prefix: str):
        """Yield (refname, target) under a prefix like 'refs/heads'."""
        base = self._ref_path(prefix)
        if not os.path.isdir(base):
            return
        for dirpath, _dirnames, filenames in os.walk(base):
            for filename in sorted(filenames):
                if filename.endswith(".lock"):
                    continue
                full = os.path.join(dirpath, filename)
                rel = os.path.relpath(full, self._ref_path(""))
                refname = rel.replace(os.sep, "/")
                yield refname, self.read_ref(refname)

    def update_ref(self, name, new_target, expected_old, actor, operation, reason, timestamp):
        """Atomically move a ref with an old-target check, then append reflog."""
        validate_ref_name(name)
        if not is_oid(new_target):
            raise UserError(f"refs: invalid target '{new_target}'")
        path = self._ref_path(name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        lock_path = path + ".lock"
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise ConcurrentUpdateError(f"refs: {name} is locked by another process") from exc
        try:
            current = self.read_ref(name)
            if current != expected_old:
                raise ConcurrentUpdateError(
                    f"refs: {name} moved (expected {expected_old or 'null'}, found {current or 'null'})"
                )
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = None
                handle.write(new_target + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.rename(lock_path, path)
        except Exception:
            if fd is not None:
                os.close(fd)
            if os.path.exists(lock_path):
                os.unlink(lock_path)
            raise
        self.append_reflog(name, expected_old, new_target, actor, operation, reason, timestamp)

    def delete_lockfile_safe(self, name):
        lock_path = self._ref_path(name) + ".lock"
        if os.path.exists(lock_path):
            os.unlink(lock_path)

    # -- reflog ---------------------------------------------------------------

    def append_reflog(self, name, old_target, new_target, actor, operation, reason, timestamp):
        if actor and any(ch.isspace() for ch in actor):
            raise UserError("reflog: actor must not contain whitespace")
        reason = " ".join(str(reason).splitlines()) or "-"
        line = f"{old_target or 'null'} {new_target} {timestamp} {actor} {operation}: {reason}\n"
        path = self._log_path(name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise CorruptionError(
                f"reflog: {name} moved but journal append failed; operational history incomplete: {exc}"
            ) from exc

    def read_reflog(self, name):
        """Return parsed reflog entries, oldest first."""
        path = self._log_path(name)
        if not os.path.isfile(path):
            return []
        entries = []
        with open(path, "r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                line = line.rstrip("\n")
                if not line:
                    continue
                match = REFLOG_LINE_RE.match(line)
                if not match:
                    raise CorruptionError(f"reflog: {name}:{line_no} unparseable line")
                entries.append(match.groupdict())
        return entries

    # -- shared helpers ---------------------------------------------------------

    def _locked_replace(self, path, content, expected=None):
        """Replace a mutable file through <path>.lock + atomic rename.

        When expected is not None, the current content is re-read under the
        lock and must match (stripped) or ConcurrentUpdateError is raised.
        """
        lock_path = path + ".lock"
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise ConcurrentUpdateError(f"refs: {path} is locked by another process") from exc
        try:
            if expected is not None:
                try:
                    with open(path, "r", encoding="utf-8") as current_handle:
                        current = current_handle.read().strip()
                except FileNotFoundError:
                    current = None
                if current != expected.strip():
                    raise ConcurrentUpdateError(
                        f"refs: {os.path.basename(path)} moved concurrently "
                        f"(expected '{expected.strip()}', found '{current}')"
                    )
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = None
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.rename(lock_path, path)
        except Exception:
            if fd is not None:
                os.close(fd)
            if os.path.exists(lock_path):
                os.unlink(lock_path)
            raise
