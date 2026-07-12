"""Writer provenance on thoughts (ADR-0016, COG-071)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cogit.errors import UserError  # noqa: E402
from cogit.objects import validate_object  # noqa: E402
from cogit.repo import WRITER  # noqa: E402
from tests.helpers import fact_doc, make_repo, ts  # noqa: E402


class WriterProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.repo = make_repo()
        self.addCleanup(self.tmp.cleanup)

    def _thought(self, oid):
        return self.repo.store.read(oid)

    def test_micro_commit_stamps_writer(self):
        result = self.repo.micro_commit(fact_doc("first", when=ts(0)), timestamp=ts(0))
        self.assertEqual(self._thought(result["thought"])["writer"], WRITER)

    def test_staged_commit_and_batch_stamp_writer(self):
        self.repo.add_fact(fact_doc("staged", when=ts(1)))
        staged = self.repo.commit_thought("staged path", "agent", timestamp=ts(1))
        self.assertEqual(self._thought(staged)["writer"], WRITER)
        batch = self.repo.micro_commit_batch(
            [fact_doc("batched", when=ts(2))], [], message="batch path",
            author="agent", timestamp=ts(2))
        self.assertEqual(self._thought(batch["thought"])["writer"], WRITER)

    def test_writer_matches_package_version(self):
        from cogit import __version__
        self.assertEqual(WRITER, f"cogit-py/{__version__}")

    def test_malformed_writer_rejected_on_write(self):
        result = self.repo.micro_commit(fact_doc("base", when=ts(3)), timestamp=ts(3))
        good = self._thought(result["thought"])
        for bad in ("", "no-slash", "two/sl/ash", "has space/1.0.0",
                    "cogit-py/" + "9" * 60, "/0.3.0", "cogit-py/"):
            doc = dict(good, writer=bad)
            with self.subTest(writer=bad):
                with self.assertRaises(UserError):
                    validate_object(doc)
        validate_object(dict(good, writer="cogit-rs/0.3.0+abc123"))  # build suffix ok

    def test_pre_adr_thoughts_without_writer_stay_valid(self):
        result = self.repo.micro_commit(fact_doc("old", when=ts(4)), timestamp=ts(4))
        doc = self._thought(result["thought"])
        doc.pop("writer")
        validate_object(doc)  # the entire pre-0.3.0 history has no writer

    def test_log_exposes_writer(self):
        self.repo.micro_commit(fact_doc("seen", when=ts(5)), timestamp=ts(5))
        self.assertEqual(self.repo.log()[0]["writer"], WRITER)


if __name__ == "__main__":
    unittest.main()
