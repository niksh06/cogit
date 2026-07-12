"""Golden tests: the implementation must reproduce the frozen test vectors."""

import json
import os
import unittest
import zlib

from tests.helpers import *  # noqa: F401,F403 (sys.path setup)
from cogit.canonical import canonical_json
from cogit.objects import encode_object

VECTORS_PATH = os.path.join(os.path.dirname(__file__), "..", "vectors", "object-vectors-v1.json")


class VectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(VECTORS_PATH, "r", encoding="utf-8") as handle:
            cls.vectors = json.load(handle)["vectors"]

    def test_all_types_present(self):
        self.assertEqual(
            [v["type"] for v in self.vectors],
            # trailing additions: premises assertion (ADR-0013), removals
            # thought (ADR-0014), writer thought (ADR-0016) — the frozen
            # earlier vectors never change
            ["claim", "assertion", "mindset", "thought", "anchor", "annotation",
             "assertion", "thought", "thought"],
        )

    def test_vectors_reproduce(self):
        for vector in self.vectors:
            with self.subTest(type=vector["type"]):
                self.assertEqual(canonical_json(vector["object"]), vector["canonical_json"])
                oid, preimage = encode_object(vector["object"])
                self.assertEqual(preimage.decode("utf-8"), vector["preimage"])
                self.assertEqual(oid, vector["object_id"])
                # zlib reproducibility: compression round-trips to the same preimage
                self.assertEqual(zlib.decompress(zlib.compress(preimage)), preimage)

    def test_chain_references_are_consistent(self):
        by_type = {}
        for vector in self.vectors:
            by_type.setdefault(vector["type"], vector)  # first occurrence wins
        self.assertEqual(by_type["assertion"]["object"]["claim"], by_type["claim"]["object_id"])
        premises_vector = self.vectors[6]
        self.assertEqual(premises_vector["object"]["premises"],
                         [by_type["assertion"]["object_id"]])
        self.assertEqual(premises_vector["object"]["claim"], by_type["claim"]["object_id"])
        removals_vector = self.vectors[7]
        self.assertEqual(removals_vector["object"]["removals"],
                         [{"assertion": by_type["assertion"]["object_id"],
                           "reason": "superseded"}])
        self.assertEqual(removals_vector["object"]["parents"],
                         [by_type["thought"]["object_id"]])
        self.assertEqual(removals_vector["object"]["mindset"],
                         by_type["mindset"]["object_id"])
        writer_vector = self.vectors[8]  # ADR-0016
        self.assertEqual(writer_vector["object"]["writer"], "cogit-py/0.3.0")
        self.assertEqual(writer_vector["object"]["parents"],
                         [removals_vector["object_id"]])
        self.assertEqual(writer_vector["object"]["mindset"],
                         by_type["mindset"]["object_id"])
        self.assertEqual(by_type["mindset"]["object"]["assertions"], [by_type["assertion"]["object_id"]])
        self.assertEqual(by_type["thought"]["object"]["mindset"], by_type["mindset"]["object_id"])
        self.assertEqual(by_type["anchor"]["object"]["target"], by_type["thought"]["object_id"])
        self.assertEqual(by_type["annotation"]["object"]["target"], by_type["thought"]["object_id"])


if __name__ == "__main__":
    unittest.main()
