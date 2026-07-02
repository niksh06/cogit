import os
import unittest
import zlib

from tests.helpers import make_repo, fact_doc
from cogit.errors import CorruptionError, UserError


class ObjectStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.repo = make_repo()
        self.addCleanup(self.tmp.cleanup)
        self.store = self.repo.store

    def write_claim(self):
        return self.store.write(fact_doc("store-test")["claim"])

    def test_roundtrip_and_dedup(self):
        oid1 = self.write_claim()
        oid2 = self.write_claim()
        self.assertEqual(oid1, oid2)  # duplicate content deduplicates by hash
        obj = self.store.read(oid1)
        self.assertEqual(obj["predicate"], "store-test")

    def test_missing_object(self):
        with self.assertRaises(UserError):
            self.store.read("sha256:" + "0" * 64)

    def test_corrupt_zlib_body(self):
        oid = self.write_claim()
        with open(self.store.path_for(oid), "wb") as handle:
            handle.write(b"not zlib at all")
        with self.assertRaises(CorruptionError):
            self.store.read(oid)

    def test_malformed_header(self):
        oid = self.write_claim()
        with open(self.store.path_for(oid), "wb") as handle:
            handle.write(zlib.compress(b"claim notasize\x00{}"))
        with self.assertRaises(CorruptionError):
            self.store.read(oid)

    def test_size_mismatch(self):
        oid = self.write_claim()
        with open(self.store.path_for(oid), "wb") as handle:
            handle.write(zlib.compress(b'claim 999\x00{"type":"claim"}'))
        with self.assertRaises(CorruptionError):
            self.store.read(oid)

    def test_hash_path_mismatch(self):
        oid = self.write_claim()
        wrong = "sha256:" + "f" * 64
        wrong_path = self.store.path_for(wrong)
        os.makedirs(os.path.dirname(wrong_path), exist_ok=True)
        os.rename(self.store.path_for(oid), wrong_path)
        with self.assertRaises(CorruptionError):
            self.store.read(wrong)

    def test_non_canonical_body_rejected(self):
        import hashlib

        body = b'{"created_at":"2026-07-02T10:00:00Z","assertions": []}'  # stray space
        preimage = b"mindset %d\x00%s" % (len(body), body)
        oid = "sha256:" + hashlib.sha256(preimage).hexdigest()
        path = self.store.path_for(oid)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(zlib.compress(preimage))
        with self.assertRaises(CorruptionError):
            self.store.read(oid)

    def test_same_path_different_content_collision(self):
        oid = self.write_claim()
        with open(self.store.path_for(oid), "wb") as handle:
            handle.write(zlib.compress(b'claim 15\x00{"type":"claim"}'[:100]))
        with self.assertRaises(CorruptionError):
            self.store.write(fact_doc("store-test")["claim"])

    def test_malformed_object_rejected_before_write(self):
        with self.assertRaises(UserError):
            self.store.write({"type": "claim", "kind": "nope"})


if __name__ == "__main__":
    unittest.main()
