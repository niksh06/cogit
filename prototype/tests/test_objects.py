import unittest

from tests.helpers import TS, fact_doc
from cogit.errors import UserError
from cogit.objects import encode_object, validate_object

OID = "sha256:" + "a" * 64


class ObjectSchemaTests(unittest.TestCase):
    def valid_claim(self):
        return dict(fact_doc("p")["claim"])

    def valid_assertion(self):
        assertion = dict(fact_doc("p")["assertion"])
        assertion["claim"] = OID
        return assertion

    def test_valid_objects_pass(self):
        validate_object(self.valid_claim())
        validate_object(self.valid_assertion())
        validate_object({"type": "mindset", "assertions": [OID], "created_at": TS})
        validate_object(
            {
                "type": "thought",
                "parents": [],
                "mindset": OID,
                "operation": "commit",
                "message": "m",
                "author": "a",
                "timestamp": TS,
            }
        )
        validate_object({"type": "anchor", "name": "plan-approved", "target": OID, "created_at": TS, "author": "a"})

    def test_unknown_field_rejected(self):
        claim = self.valid_claim()
        claim["extra"] = 1
        with self.assertRaises(UserError):
            validate_object(claim)

    def test_unknown_type_rejected(self):
        with self.assertRaises(UserError):
            validate_object({"type": "fact"})

    def test_confidence_bounds(self):
        assertion = self.valid_assertion()
        for bad in (-1, 10001, True, "9200"):
            assertion["confidence_bps"] = bad
            with self.assertRaises(UserError):
                validate_object(assertion)

    def test_timestamp_format(self):
        assertion = self.valid_assertion()
        assertion["asserted_at"] = "2026-05-26 18:00:00"
        with self.assertRaises(UserError):
            validate_object(assertion)

    def test_bad_status_and_source(self):
        assertion = self.valid_assertion()
        assertion["status"] = "believed"
        with self.assertRaises(UserError):
            validate_object(assertion)
        assertion = self.valid_assertion()
        assertion["source"] = {"type": "telepathy"}
        with self.assertRaises(UserError):
            validate_object(assertion)

    def test_mindset_must_be_sorted_unique(self):
        b = "sha256:" + "b" * 64
        with self.assertRaises(UserError):
            validate_object({"type": "mindset", "assertions": [b, OID], "created_at": TS})
        with self.assertRaises(UserError):
            validate_object({"type": "mindset", "assertions": [OID, OID], "created_at": TS})

    def test_thought_parents_semantic_order_allowed(self):
        # parents preserve semantic (ours, theirs) order — unsorted must be legal
        b = "sha256:" + "b" * 64
        validate_object(
            {
                "type": "thought",
                "parents": [b, OID],
                "mindset": OID,
                "operation": "merge",
                "message": "m",
                "author": "a",
                "timestamp": TS,
            }
        )

    def test_encode_object_is_deterministic(self):
        oid1, pre1 = encode_object(self.valid_claim())
        oid2, pre2 = encode_object(self.valid_claim())
        self.assertEqual(oid1, oid2)
        self.assertEqual(pre1, pre2)
        self.assertTrue(oid1.startswith("sha256:"))
        self.assertIn(b"\x00", pre1)
        header = pre1.split(b"\x00", 1)[0].decode()
        self.assertEqual(header, f"claim {len(pre1.split(chr(0).encode(), 1)[1])}")


if __name__ == "__main__":
    unittest.main()
