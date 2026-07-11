"""Belief search — cogit's git-grep (COG-068)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cogit.errors import UserError  # noqa: E402
from tests.helpers import fact_doc, make_repo, ts  # noqa: E402


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.repo = make_repo()
        self.addCleanup(self.tmp.cleanup)
        cache = fact_doc("root_cause", obj="cache invalidation storm", when=ts(0))
        cache["claim"]["subject"] = "bug:orders-500"
        cache["claim"]["qualifiers"]["project"] = "alpha"
        self.cache = self.repo.micro_commit(cache, timestamp=ts(0))
        other = fact_doc("owner", obj="infra", when=ts(1))
        other["claim"]["subject"] = "svc:queue"
        other["claim"]["qualifiers"]["project"] = "beta"
        self.repo.micro_commit(other, timestamp=ts(1))

    def test_matches_across_fields_case_insensitive(self):
        result = self.repo.search("CACHE")
        self.assertEqual(result["total"], 1)
        match = result["matches"][0]
        self.assertEqual(match["subject"], "bug:orders-500")
        self.assertEqual(match["matched_in"], ["object"])
        self.assertTrue(match["active"])
        by_subject = self.repo.search("orders-500")
        self.assertEqual(by_subject["matches"][0]["matched_in"], ["subject"])
        by_qualifier = self.repo.search("alpha")
        self.assertIn("qualifier:project", by_qualifier["matches"][0]["matched_in"])

    def test_project_scope_and_no_match(self):
        self.assertEqual(self.repo.search("cache", project="beta")["total"], 0)
        self.assertEqual(self.repo.search("nonexistent-token")["total"], 0)

    def test_annotation_bodies_are_searchable(self):
        self.repo.annotate(self.cache["assertion"],
                           "confirmed via grafana saturation panel",
                           namespace="detail", timestamp=ts(2))
        result = self.repo.search("grafana")
        self.assertEqual(result["total"], 1)
        self.assertIn("annotation", result["matches"][0]["matched_in"])

    def test_history_finds_superseded_with_active_flag(self):
        assertion = {"type": "assertion", "status": "asserted",
                     "source": {"type": "tool", "uri": "test:grep"},
                     "confidence_bps": 9800, "asserted_at": ts(3),
                     "actor": "tester", "method": {"type": "fixture"}}
        self.repo.supersede_fact(self.cache["assertion"],
                                 "retry storm exhausted the pool", assertion,
                                 timestamp=ts(3))
        self.assertEqual(self.repo.search("invalidation")["total"], 0)  # active only
        history = self.repo.search("invalidation", history=True)
        self.assertEqual(history["total"], 1)
        self.assertFalse(history["matches"][0]["active"])

    def test_limit_keeps_totals_exact(self):
        for n in range(4):
            doc = fact_doc(f"needle_case_{n}", obj="needle in here", when=ts(10 + n))
            doc["claim"]["subject"] = f"spot:{n}"
            self.repo.micro_commit(doc, timestamp=ts(10 + n))
        result = self.repo.search("needle", limit=2)
        self.assertEqual(result["total"], 4)
        self.assertEqual(len(result["matches"]), 2)
        self.assertEqual(result["truncated"], 2)

    def test_empty_pattern_rejected_and_empty_repo_ok(self):
        with self.assertRaises(UserError):
            self.repo.search("  ")
        tmp2, repo2 = make_repo()
        self.addCleanup(tmp2.cleanup)
        self.assertEqual(repo2.search("anything")["total"], 0)


if __name__ == "__main__":
    unittest.main()
