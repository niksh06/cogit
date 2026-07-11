"""Tolerant readers (ADR-0015): objects from a NEWER cogit must load."""

import os
import sys
import unittest
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cogit.canonical import canonical_json  # noqa: E402
from cogit.errors import UserError  # noqa: E402
from cogit.objects import validate_object  # noqa: E402
from cogit.verify import verify_repository  # noqa: E402
from tests.helpers import fact_doc, make_repo, ts  # noqa: E402


def plant_future_object(repo, obj):
    """Write an object the way a NEWER cogit would: valid hash + canonical
    bytes, but carrying a field this version does not know."""
    import hashlib
    body = canonical_json(obj).encode("utf-8")
    preimage = f"{obj['type']} {len(body)}".encode("ascii") + b"\x00" + body
    oid = "sha256:" + hashlib.sha256(preimage).hexdigest()
    fanout = os.path.join(repo.cogit_dir, "objects", oid[7:9])
    os.makedirs(fanout, exist_ok=True)
    with open(os.path.join(fanout, oid[9:]), "wb") as handle:
        handle.write(zlib.compress(preimage))
    return oid


class TolerantReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.repo = make_repo()
        self.addCleanup(self.tmp.cleanup)
        self.base = self.repo.micro_commit(fact_doc("known"), timestamp=ts(0))

    def future_thought(self):
        head = self.repo.status()["thought"]
        return {
            "type": "thought",
            "parents": [head],
            "mindset": self.repo.show(head)["mindset"],
            "operation": "commit",
            "message": "from the future",
            "author": "future-agent",
            "timestamp": ts(1),
            "hypothetical_field_from_v2": {"weight": 3},
        }

    def test_read_tolerates_unknown_fields_and_preserves_bytes(self):
        oid = plant_future_object(self.repo, self.future_thought())
        obj = self.repo.store.read(oid)  # must NOT raise CorruptionError
        self.assertEqual(obj["hypothetical_field_from_v2"], {"weight": 3})
        self.assertEqual(obj["message"], "from the future")

    def test_write_stays_strict(self):
        with self.assertRaises(UserError) as ctx:
            self.repo.store.write(self.future_thought())
        self.assertIn("unknown fields", str(ctx.exception))

    def test_unknown_object_type_is_still_fatal(self):
        with self.assertRaises(UserError):
            validate_object({"type": "prophecy", "text": "?"}, mode="read")

    def test_verify_reports_skew_as_warning_not_error(self):
        oid = plant_future_object(self.repo, self.future_thought())
        findings = verify_repository(self.repo)
        skew = [f for f in findings if f["code"] == "unknown-fields"]
        self.assertEqual(len(skew), 1)
        self.assertEqual(skew[0]["severity"], "warning")
        self.assertIn(oid, skew[0]["message"])
        self.assertEqual([f for f in findings
                          if f["severity"] == "error" and oid in f["message"]], [])

    def test_known_field_checks_still_run_on_read(self):
        broken = self.future_thought()
        broken["timestamp"] = "not-a-timestamp"
        with self.assertRaises(UserError):
            validate_object(broken, mode="read")


if __name__ == "__main__":
    unittest.main()
