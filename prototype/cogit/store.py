"""Content-addressed object store: zlib(<type> <size>\\0<canonical-json>).

Write path: validate -> canonicalize -> hash -> tmp file -> atomic rename.
Read path: decompress -> parse header -> verify size, hash, canonical bytes,
schema. Contract: docs/spec/object-format-v1.md.
"""

import hashlib
import os
import re
import zlib

from .canonical import canonical_json, parse_json
from .errors import CorruptionError, UserError
from .objects import OBJECT_TYPES, encode_object, is_oid, validate_object


class ObjectStore:
    def __init__(self, cogit_dir):
        self.objects_dir = os.path.join(cogit_dir, "objects")
        self.tmp_dir = os.path.join(cogit_dir, "tmp")

    def path_for(self, oid: str) -> str:
        if not is_oid(oid):
            raise UserError(f"object store: invalid object id '{oid}'")
        hexpart = oid.split(":", 1)[1]
        return os.path.join(self.objects_dir, hexpart[:2], hexpart[2:])

    def exists(self, oid: str) -> bool:
        return os.path.isfile(self.path_for(oid))

    PREFIX_RE = re.compile(r"^[0-9a-f]{6,64}$")

    def expand_prefix(self, name: str) -> str:
        """Expand a unique object-id prefix (>= 6 hex chars) to a full oid (COG-025)."""
        hexpart = name[len("sha256:") :] if name.startswith("sha256:") else name
        if not self.PREFIX_RE.match(hexpart):
            raise UserError(
                f"object store: '{name}' is not an object id or unique prefix (>= 6 hex chars)"
            )
        if len(hexpart) == 64:
            return "sha256:" + hexpart
        fanout_dir = os.path.join(self.objects_dir, hexpart[:2])
        rest = hexpart[2:]
        matches = []
        if os.path.isdir(fanout_dir):
            matches = [entry for entry in sorted(os.listdir(fanout_dir)) if entry.startswith(rest)]
        if not matches:
            raise UserError(f"object store: no object matches prefix '{name}'")
        if len(matches) > 1:
            raise UserError(f"object store: prefix '{name}' is ambiguous ({len(matches)} matches)")
        return f"sha256:{hexpart[:2]}{matches[0]}"

    def write(self, obj) -> str:
        """Write an object; deduplicates by hash. Returns the object ID."""
        oid, preimage = encode_object(obj)
        target = self.path_for(oid)
        if os.path.exists(target):
            # Same path must mean same content; anything else is corruption.
            existing = self._read_preimage(oid, target)
            if existing != preimage:
                raise CorruptionError(
                    f"object store: {oid} exists with different content (collision/corruption)"
                )
            return oid
        os.makedirs(os.path.dirname(target), exist_ok=True)
        os.makedirs(self.tmp_dir, exist_ok=True)
        compressed = zlib.compress(preimage)
        fd, tmp_path = self._mkstemp()
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(compressed)
                handle.flush()
                os.fsync(handle.fileno())
            os.rename(tmp_path, target)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        return oid

    def read(self, oid: str) -> dict:
        """Read and fully verify an object."""
        target = self.path_for(oid)
        if not os.path.isfile(target):
            raise UserError(f"object store: {oid} not found")
        preimage = self._read_preimage(oid, target)
        return self._decode_preimage(oid, preimage)

    def _mkstemp(self):
        import tempfile

        return tempfile.mkstemp(prefix="obj-", dir=self.tmp_dir)

    def _read_preimage(self, oid: str, path: str) -> bytes:
        with open(path, "rb") as handle:
            compressed = handle.read()
        try:
            return zlib.decompress(compressed)
        except zlib.error as exc:
            raise CorruptionError(f"object store: {oid} corrupt zlib body: {exc}") from exc

    def _decode_preimage(self, oid: str, preimage: bytes) -> dict:
        nul = preimage.find(b"\x00")
        if nul < 0:
            raise CorruptionError(f"object store: {oid} malformed header (no NUL)")
        header = preimage[:nul]
        body = preimage[nul + 1 :]
        try:
            type_text, size_text = header.decode("ascii").split(" ", 1)
            declared_size = int(size_text)
        except (UnicodeDecodeError, ValueError) as exc:
            raise CorruptionError(f"object store: {oid} malformed header") from exc
        if type_text not in OBJECT_TYPES:
            raise CorruptionError(f"object store: {oid} unknown object type '{type_text}'")
        if declared_size != len(body):
            raise CorruptionError(
                f"object store: {oid} size mismatch (declared {declared_size}, actual {len(body)})"
            )
        computed = "sha256:" + hashlib.sha256(preimage).hexdigest()
        if computed != oid:
            raise CorruptionError(f"object store: hash-path mismatch (path {oid}, content {computed})")
        try:
            obj = parse_json(body.decode("utf-8"))
        except UserError:
            raise
        except (UnicodeDecodeError, ValueError) as exc:
            raise CorruptionError(f"object store: {oid} invalid JSON body") from exc
        try:
            # ADR-0015: reads tolerate unknown fields (forward compatibility);
            # writes stay strict — see ObjectStore.write
            validate_object(obj, mode="read")
        except UserError as exc:
            raise CorruptionError(f"object store: {oid} schema invalid: {exc}") from exc
        if canonical_json(obj).encode("utf-8") != body:
            raise CorruptionError(f"object store: {oid} body is not canonical JSON")
        if obj["type"] != type_text:
            raise CorruptionError(f"object store: {oid} header/body type mismatch")
        return obj
