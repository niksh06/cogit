import os
import unittest

from tests.helpers import fact_doc, make_repo, ts
from cogit.maintenance import count_objects


class CountObjectsTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.repo = make_repo()
        self.addCleanup(self.tmp.cleanup)

    def build_fixture(self):
        self.repo.add_fact(fact_doc("one"))
        t1 = self.repo.commit_thought("first", "agent", ts(0))
        self.repo.add_fact(fact_doc("two"))
        self.repo.commit_thought("second", "agent", ts(1))
        self.repo.branch("side", timestamp=ts(2))
        self.repo.anchor("m1", t1, timestamp=ts(3))
        return t1

    def test_counts_match_fixture(self):
        self.build_fixture()
        result = count_objects(self.repo)
        # 2 claims, 2 assertions, 2 mindsets, 2 thoughts, 1 anchor
        self.assertEqual(
            result["by_type"],
            {"claim": 2, "assertion": 2, "mindset": 2, "thought": 2, "anchor": 1, "annotation": 0},
        )
        self.assertEqual(result["loose_objects"], 9)
        self.assertEqual(result["corrupt_objects"], 0)
        self.assertGreater(result["disk_bytes"], 0)
        self.assertEqual(result["heads"], 2)   # main + side
        self.assertEqual(result["anchors"], 1)
        # 2 commits x2 (branch+HEAD) + branch create + anchor create = 6 entries
        self.assertEqual(result["reflog_entries"], 6)
        self.assertEqual(result["tmp_files"], 0)
        self.assertEqual(result["warnings"], [])

    def test_threshold_override_warns(self):
        self.build_fixture()
        with open(os.path.join(self.repo.cogit_dir, "config"), "a", encoding="utf-8") as handle:
            handle.write("[maintenance]\n\tlooseObjectsWarn = 2\n\treflogEntriesWarn = 3\n")
        result = count_objects(self.repo)
        self.assertEqual(result["thresholds"]["looseObjectsWarn"], 2)
        self.assertEqual(len(result["warnings"]), 2)
        self.assertIn("loose objects", result["warnings"][0])
        self.assertIn("reflog entries", result["warnings"][1])

    def test_corrupt_objects_counted_not_fatal(self):
        self.build_fixture()
        # damage one object file; metrics must survive and count it
        objects_dir = os.path.join(self.repo.cogit_dir, "objects")
        fanout = sorted(os.listdir(objects_dir))[0]
        target_dir = os.path.join(objects_dir, fanout)
        target = os.path.join(target_dir, sorted(os.listdir(target_dir))[0])
        with open(target, "wb") as handle:
            handle.write(b"garbage")
        result = count_objects(self.repo)
        self.assertEqual(result["corrupt_objects"], 1)
        self.assertEqual(result["loose_objects"], 9)
        self.assertTrue(any("unreadable" in w for w in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
