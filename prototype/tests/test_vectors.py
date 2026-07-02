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

    def test_all_five_types_present(self):
        self.assertEqual(
            [v["type"] for v in self.vectors],
            ["claim", "assertion", "mindset", "thought", "anchor"],
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
        by_type = {v["type"]: v for v in self.vectors}
        self.assertEqual(by_type["assertion"]["object"]["claim"], by_type["claim"]["object_id"])
        self.assertEqual(by_type["mindset"]["object"]["assertions"], [by_type["assertion"]["object_id"]])
        self.assertEqual(by_type["thought"]["object"]["mindset"], by_type["mindset"]["object_id"])
        self.assertEqual(by_type["anchor"]["object"]["target"], by_type["thought"]["object_id"])


if __name__ == "__main__":
    unittest.main()
